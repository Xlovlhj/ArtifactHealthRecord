"""下载官方公开视觉预训练权重，固定提交并核对 LFS SHA256；不包含病害分类权重。"""
from __future__ import annotations
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import requests

MODELS = {
    "dinov2": "facebook/dinov2-small",
    "clip": "openai/clip-vit-base-patch32",
    "chinese_clip": "OFA-Sys/chinese-clip-vit-base-patch16",
    "sam": "facebook/sam-vit-base",
}


def download_model(name, output, revision=None):
    repo = MODELS[name]
    session = requests.Session()
    endpoint = f"https://huggingface.co/api/models/{repo}" + (f"/revision/{revision}" if revision else "")
    metadata_response = session.get(endpoint, params={"blobs": "true"}, timeout=30)
    metadata_response.raise_for_status()
    metadata = metadata_response.json()
    commit = metadata["sha"]
    if revision and len(revision) == 40 and revision != commit:
        raise ValueError("模型仓库实际提交与指定提交不一致")
    license_name = metadata.get("cardData", {}).get("license")
    if license_name not in {"apache-2.0", "mit"}:
        raise ValueError(f"许可为 {license_name!r}，需要先人工核对模型卡后扩展允许列表")
    siblings = {item["rfilename"]: item for item in metadata["siblings"]}
    weights = "model.safetensors" if "model.safetensors" in siblings else "pytorch_model.bin"
    names = ["config.json", "preprocessor_config.json", weights, "README.md"]
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for name in names:
        if name not in siblings:
            raise ValueError(f"官方仓库缺少 {name}，需更新适配器而非猜测文件")
        expected = siblings[name].get("lfs", {}).get("sha256")
        target, temporary = destination / name, destination / (name + ".part")
        if target.exists() and expected and hashlib.file_digest(target.open("rb"), "sha256").hexdigest() == expected:
            digest = expected
        else:
            response = session.get(f"https://huggingface.co/{repo}/resolve/{commit}/{name}", stream=True, timeout=(30, 120))
            response.raise_for_status()
            digestor = hashlib.sha256()
            try:
                with temporary.open("wb") as stream:
                    for block in response.iter_content(1024 * 1024):
                        if block:
                            stream.write(block)
                            digestor.update(block)
                digest = digestor.hexdigest()
                if expected and digest != expected:
                    raise ValueError(f"{name} SHA256 校验失败")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
                response.close()
        files.append({"name": name, "sha256": digest, "bytes": target.stat().st_size,
                      "remote_lfs_sha256": expected})
        print(json.dumps(files[-1], ensure_ascii=False), flush=True)
    record = {"repository": repo, "revision": commit, "license": license_name, "files": files,
              "source": f"https://huggingface.co/{repo}/tree/{commit}",
              "downloaded_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "purpose": "通用视觉特征/SAM区域候选，不是经过本项目验证的六类病害模型"}
    (destination / "provenance.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    session.close()
    return record


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=MODELS, default="dinov2")
    parser.add_argument("--output", required=True)
    parser.add_argument("--revision", help="推荐填已核对的40位提交；未填则首次解析后立即固定实际提交")
    args = parser.parse_args()
    download_model(args.model, args.output, args.revision)
