"""显式执行才下载；默认下载已核验许可和固定版本的 DINOv2-small + SAM-base。"""
from pathlib import Path
import argparse
import hashlib
import json
import requests
from download_models import download_model

PINNED = {
    "dinov2": {"revision": "ed25f3a31f01632728cabb09d1542f84ab7b0056", "directory": "dinov2-small",
               "weight_sha256": "ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1"},
    "sam": {"revision": "70c1a07f894ebb5b307fd9eaaee97b9dfc16068f", "directory": "sam-vit-base",
            "weight_sha256": "892c410e496344e527255ccdcb2cb7244a609acb5389c7c4fdba1288f861c579"},
    "resnet34": {"directory": "resnet34", "url": "https://download.pytorch.org/models/resnet34-b627a593.pth",
                 "sha256_prefix": "b627a593"},
}


def fetch_resnet34(root):
    config = PINNED["resnet34"]
    directory = Path(root) / config["directory"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "resnet34-b627a593.pth"
    def digest():
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()
    if not path.is_file() or not digest().startswith(config["sha256_prefix"]):
        response = requests.get(config["url"], stream=True, timeout=(30, 120))
        response.raise_for_status()
        temporary = path.with_suffix(".part")
        try:
            checksum = hashlib.sha256()
            with temporary.open("wb") as stream:
                for block in response.iter_content(1024*1024):
                    if block:
                        stream.write(block)
                        checksum.update(block)
            if not checksum.hexdigest().startswith(config["sha256_prefix"]):
                raise ValueError("ResNet34官方文件SHA256前缀校验失败")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
            response.close()
    record = {"model": "torchvision ResNet34 IMAGENET1K_V1 encoder", "url": config["url"],
              "sha256": digest(), "bytes": path.stat().st_size, "upstream_hash_prefix": config["sha256_prefix"],
              "source": "https://docs.pytorch.org/vision/0.20/models/generated/torchvision.models.resnet34.html",
              "license_context": "torchvision BSD-3-Clause；通用ImageNet预训练编码器不是文物病害模型"}
    (directory / "provenance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False), flush=True)
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", choices=PINNED, default=["dinov2", "sam"])
    parser.add_argument("--output-root", default="runtime/models")
    args = parser.parse_args()
    for name in args.models:
        if name == "resnet34":
            fetch_resnet34(args.output_root)
            continue
        config = PINNED[name]
        result = download_model(name, Path(args.output_root) / config["directory"], config["revision"])
        if config.get("weight_sha256") and not any(f["sha256"] == config["weight_sha256"] for f in result["files"]):
            raise ValueError("下载结果与项目固定权重SHA256不符")
