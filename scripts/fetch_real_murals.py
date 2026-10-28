"""下载方案指定公开敦煌图像集的原始GT图；不把修复遮罩当六病害标注。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
from pathlib import Path
import random
import requests
from PIL import Image

REPO = "lkljty/Dunhuang_Grottoes_Painting"
REVISION = "29ba7558766647398afca71c49657aa16e778d64"


def fetch_real_murals(output, count=60, seed=42):
    if not 1 <= count <= 600:
        raise ValueError("count 必须在 1..600，按原始GT图计数，不包括masked衍生图")
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    api = f"https://huggingface.co/api/datasets/{REPO}/revision/{REVISION}"
    response = requests.get(api, params={"blobs": "true"}, timeout=30)
    response.raise_for_status()
    metadata = response.json()
    if metadata.get("sha") != REVISION or metadata.get("cardData", {}).get("license") != "mit":
        raise ValueError("数据提交或上传者许可声明变化，停止下载等待人工复核")
    (destination / "upstream_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    readme_url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/README.md"
    readme = requests.get(readme_url, timeout=30)
    readme.raise_for_status()
    (destination / "upstream_README.md").write_bytes(readme.content)
    candidates = [entry for entry in metadata["siblings"]
                  if entry["rfilename"].startswith(("train/train_GT/", "test/test_GT/"))
                  and entry["rfilename"].lower().endswith((".jpg", ".jpeg", ".png"))]
    candidates = sorted(candidates, key=lambda entry: entry["rfilename"])
    random.Random(seed).shuffle(candidates)
    chosen = sorted(candidates[:count], key=lambda entry: entry["rfilename"])
    def download(entry):
        remote = entry["rfilename"]
        target = destination / "originals" / remote
        target.parent.mkdir(parents=True, exist_ok=True)
        expected = entry["lfs"]["sha256"]
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{remote}"
        data = target.read_bytes() if target.exists() else None
        if data is None or hashlib.sha256(data).hexdigest() != expected:
            response = requests.get(url, timeout=(30, 120))
            response.raise_for_status()
            data = response.content
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"图像 SHA256 与上游LFS不一致: {remote}")
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.write_bytes(data)
            temporary.replace(target)
        with Image.open(target) as image:
            width, height = image.size
            image.verify()
        return {"id": "dunhuang-hf-" + Path(remote).stem, "path": str(target.relative_to(destination)),
                "filename": Path(remote).name, "width": width, "height": height, "sha256": expected,
                "source_url": f"https://huggingface.co/datasets/{REPO}/blob/{REVISION}/{remote}",
                "download_url": url, "repository": REPO, "revision": REVISION,
                "dataset_original_split": remote.split("/")[0], "data_kind": "real_image_unannotated",
                "region": "甘肃省敦煌市", "material": "壁画影像", "period": "中唐（原数据集论文记载）",
                "site_id": "mogao-cave-007", "mural_id": None, "group_id": "mogao-cave-007", "diseases": [],
                "site_basis": "原论文§1/§2明确600张来自莫高窟第7窟南北壁；镜像逐张对应关系未另附证明，保守整体同组",
                "six_class_annotation": None, "expert_reviewed": False,
                "license": "MIT（Hugging Face上传者声明）", "license_evidence": readme_url,
                "rights_status": "公开研究数据集；原始摄影者/逐图授权链未在镜像卡中列出，保留本地研究、不自动纳入GitHub发行包",
                "caption": f"莫高窟第7窟壁画公开研究影像 {Path(remote).stem}；具体墙面位置与病害待专家核实",
                "notes": "GT是上游图像修复任务参考照片，不是六类病害真值；未下载masked合成衍生图。"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(download, chosen))
    hashes = [row["sha256"] for row in rows]
    manifest = {"dataset": REPO, "revision": REVISION, "retrieved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "count": len(rows), "unique_file_sha256_count": len(set(hashes)), "sampling": {"method": "seeded_shuffle_original_GT_only", "seed": seed, "population": len(candidates)},
                "license_declaration": "MIT", "license_status": "uploaded_dataset_card_declaration",
                "original_paper": "https://arxiv.org/abs/1907.04589", "mirror_linked_paper": "https://arxiv.org/abs/2508.07140",
                "upstream_author_project": "https://github.com/CXH-Research/CMAMRNet",
                "six_class_ground_truth_count": 0, "independent_groups": 1,
                "group_basis": "原论文2019 §1/§2：莫高窟第7窟南北壁600张裁片；整体同组防止裁片泄漏",
                "training_eligible": False, "github_redistribution": False,
                "reason": "仅一洞窟组、缺六类专家标注和逐图完整权利链；可本地资料浏览、检索/交互工程验证，不能报告真实病害精度。",
                "records": rows}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ["dataset", "revision", "count", "unique_file_sha256_count", "six_class_ground_truth_count"]}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="runtime/real-data/dunhuang_hf")
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    fetch_real_murals(args.output, args.count, args.seed)
