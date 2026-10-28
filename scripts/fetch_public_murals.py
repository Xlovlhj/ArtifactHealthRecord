"""Collect an explicitly curated, redistributable reference set from The Met.

These are photographs of real mural objects, with museum metadata and CC0
evidence. They contain no disease labels and are never a six-class benchmark.
Run: python3 scripts/fetch_public_murals.py
"""
from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_ROOT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
LICENSE_EVIDENCE = "https://www.metmuseum.org/hubs/open-access"
PROVIDER = "The Metropolitan Museum of Art"
# Curated by object type and substrate, not keyword search alone: wood panels,
# paper/silk paintings, sculpture and unspecified Central Asian origins excluded.
OBJECTS = {
    40323: "宋代壁画残片", 40345: "宋代菩萨壁画残片",
    42716: "广胜寺药师佛法会图壁画", 61855: "佛像壁画（馆方标注北魏时期）",
    39906: "佛像壁画残片", 44794: "持莲僧人壁画残片",
    49570: "菩萨壁画残片", 49571: "三位天人壁画残片",
    49572: "两位菩萨壁画残片", 49573: "三位菩萨壁画残片",
    49574: "佛与两位弟子壁画残片", 51677: "菩萨头部壁画残片",
    54210: "佛像壁画残片", 54211: "坐姿菩萨壁画残片",
    54212: "佛头壁画残片", 54213: "佛教人物头部壁画残片",
    60654: "武士壁画残片", 60655: "侍从壁画残片",
}
EXCLUDED_IMAGE_NAMES = {"SC-LC_65_29_2-01.jpg": "馆方线描说明图，不是真实摄影影像"}
REVERSE_IMAGE_NAMES = {"DP357166.jpg", "DP356933.jpg", "DP360995.jpg", "DP356770.jpg",
                       "DP357275.jpg", "DP356769.jpg", "DP356768.jpg", "DP357162.jpg"}
MONOCHROME_IMAGE_NAMES = {"63648.jpg", "29_76.JPG", "47_18_132.JPG", "18_56_84-87_O.JPG", "51_94_3.jpg"}


def write_support_files(output, manifest):
    fields = ["image_id", "artifact_id", "image", "view_type", "image_sha256", "source_url", "license", "group_id",
              "group_verified", "six_class_annotation", "rater_a_id", "rater_b_id", "adjudicator_id",
              "expert_reviewed", "training_eligible"]
    with (output / "annotation_intake.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in manifest["records"]:
            writer.writerow({"image_id": row["id"], "artifact_id": row["artifact_id"], "image": row["path"],
                             "view_type": row["view_type"], "image_sha256": row["sha256"],
                             "source_url": row["source_url"], "license": row["license"], "group_id": row["group_id"],
                             "group_verified": "false", "expert_reviewed": "false", "training_eligible": "false"})
    (output / "LICENSE.txt").write_text(
        "The Metropolitan Museum of Art Open Access photographs and object metadata\n"
        f"License: CC0 1.0 Universal\n{LICENSE_URL}\nOfficial policy: {LICENSE_EVIDENCE}\n"
        "Each object has isPublicDomain=true in its accompanying metadata/met-OBJECT_ID.json.\n"
        "The manifest preserves original image URLs, object accession numbers, credit lines and SHA256 hashes.\n"
        "The files are reference photographs of real mural objects, not expert disease annotations.\n", encoding="utf-8")


def _get(url, limit=32 * 1024 * 1024):
    response = requests.get(url, timeout=(20, 90), stream=True,
                            headers={"User-Agent": "ArtifactHealthRecord/1.0 (Open Access reference collection)"})
    try:
        response.raise_for_status()
        blocks, size = [], 0
        for block in response.iter_content(65536):
            size += len(block)
            if size > limit:
                raise ValueError(f"Resource exceeds {limit} bytes: {url}")
            blocks.append(block)
        return b"".join(blocks)
    finally:
        response.close()


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _photo_metadata(content):
    with Image.open(io.BytesIO(content)) as image:
        if image.format != "JPEG" or image.width * image.height > 60_000_000:
            raise ValueError("官方图像必须为有效JPEG且不超过6000万像素")
        width, height = image.size
        image.verify()
    return {"width": width, "height": height, "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest()}


def fetch_public_murals(output, object_ids=None, refresh=False):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ids = list(OBJECTS) if object_ids is None else list(dict.fromkeys(object_ids))
    if not ids or any(i not in OBJECTS for i in ids):
        raise ValueError("只接受已核查为中国壁画的固定对象ID")
    retrieved_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lock_path = Path(__file__).resolve().parents[1] / "data/public/mural_reference/source_lock.json"
    locked = ({row["id"]: row for row in json.loads(lock_path.read_text(encoding="utf-8"))["records"]}
              if lock_path.is_file() else {})
    previous = {}
    if (output / "manifest.json").is_file():
        previous = {row["id"]: row for row in json.loads((output / "manifest.json").read_text())["records"]}

    def collect(object_id):
        source = f"https://www.metmuseum.org/art/collection/search/{object_id}"
        api = API_ROOT + str(object_id)
        metadata_path = output / "metadata" / f"met-{object_id}.json"
        data = (json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.is_file() and not refresh
                else json.loads(_get(api, limit=2 * 1024 * 1024)))
        if data.get("objectID") != object_id or data.get("isPublicDomain") is not True:
            raise ValueError(f"对象 {object_id} 缺少官方 Public Domain 声明，停止发布")
        if not any(term in data.get("medium", "").lower() for term in ("fresco", "plaster", "clay mixed", "wall painting")):
            raise ValueError(f"对象 {object_id} 材质不属于已核查壁画范围")
        urls = [url for url in dict.fromkeys([data["primaryImage"], *data.get("additionalImages", [])])
                if Path(urlparse(url).path).name not in EXCLUDED_IMAGE_NAMES]
        if not urls or not urls[0]:
            raise ValueError(f"对象 {object_id} 无官方开放影像")
        _json(metadata_path, data)
        region = ("山西省" if object_id == 42716 else "新疆维吾尔自治区"
                  if "Xinjiang" in data.get("culture", "") else "中国（具体原址待核）")
        # Museum accession numbers are object identities, not proof of separate
        # source murals. Unknown origins deliberately share one conservative group.
        group = "guangsheng-lower-temple" if object_id == 42716 else "met-source-sites-unresolved"
        group_basis = ("馆方对象页History明确山西广胜下寺大殿东壁" if object_id == 42716 else
                       "馆藏号不等于独立壁画或洞窟；原址关系未逐件核清，保守同组且禁止评测")
        rows = []
        for index, url in enumerate(urls):
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname not in {"images.metmuseum.org", "collectionapi.metmuseum.org"}:
                raise ValueError("拒绝下载不在博物馆官方域名上的影像")
            identifier = f"met-{object_id}-{index + 1:02d}"
            if locked and (identifier not in locked or locked[identifier]["download_url"] != url):
                raise ValueError(f"官方影像列表发生变化，需先核图并更新source_lock：{identifier}")
            relative = Path("images") / f"{identifier}.jpg"
            target = output / relative
            previous_row = previous.get(identifier)
            if target.is_file() and previous_row and not refresh:
                content = target.read_bytes()
                if hashlib.sha256(content).hexdigest() != previous_row["sha256"]:
                    raise ValueError(f"本地文件已改动：{relative}；使用--refresh重新获取官方原图")
            else:
                content = _get(url)
            photo = _photo_metadata(content)
            if locked and photo["sha256"] != locked[identifier]["sha256"]:
                raise ValueError(f"原图SHA256与固定版本不一致：{identifier}")
            remote_name = Path(parsed.path).name
            view_type = ("reverse" if remote_name in REVERSE_IMAGE_NAMES else
                         "front_monochrome" if remote_name in MONOCHROME_IMAGE_NAMES else "front")
            view_label = {"front": "彩色正面", "front_monochrome": "正面（黑白旧照）", "reverse": "背面与装裱结构"}[view_type]
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".jpg.part")
            temporary.write_bytes(content)
            temporary.replace(target)
            provenance = {
                "source_type": "public_dataset", "source_title": f"{PROVIDER} · {data['title']}",
                "source_url": source, "creator": data.get("artistDisplayName") or "馆方未列出创作者",
                "license_name": "CC0-1.0", "license_url": LICENSE_URL,
                "rights_holder": PROVIDER, "permission_evidence": f"{LICENSE_EVIDENCE} ; {api} (isPublicDomain=true)",
                "allowed_uses": ["internal_display", "research", "redistribution"],
                "captured_at": None, "site_group": group,
                "notes": f"官方开放实物照片（{view_label}）；无六类病害真值、无专家审核，不是合作馆试点数据；采集日期未知。"
            }
            rows.append({"id": identifier, "artifact_id": f"met-{object_id}",
                         "title": data["title"], "title_zh": OBJECTS[object_id],
                         "view_index": index + 1, "view_count": len(urls), "path": relative.as_posix(), **photo,
                         "view_type": view_type, "view_type_label": view_label,
                         "source_url": source, "download_url": url, "metadata_path": metadata_path.relative_to(output).as_posix(),
                         "metadata_sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                         "museum": PROVIDER, "accession_number": data["accessionNumber"],
                         "region": region, "material": data["medium"], "period": data.get("period", ""),
                         "object_date": data.get("objectDate", ""), "credit_line": data.get("creditLine", ""),
                         "group_id": group, "group_basis": group_basis,
                         "license": "CC0-1.0", "license_evidence": LICENSE_EVIDENCE,
                         "data_kind": "real_image_unannotated", "github_redistribution": True,
                         "training_eligible": False, "expert_reviewed": False, "six_class_annotation": None,
                         "diseases": [], "provenance": provenance,
                         "notes": "保留博物馆原始JPEG字节；多视图不当作独立文物；色彩/年代/尺寸沿用馆方元数据，不推断当前病害。"})
        print(json.dumps({"artifact_id": f"met-{object_id}", "images": len(rows),
                          "bytes": sum(r["bytes"] for r in rows)}, ensure_ascii=False), flush=True)
        return rows

    with ThreadPoolExecutor(max_workers=3) as executor:
        records = [row for group in executor.map(collect, ids) for row in group]
    records.sort(key=lambda row: row["id"])
    manifest = {
        "version": "ahr-public-mural-reference-v1", "retrieved_at": retrieved_at,
        "provider": PROVIDER, "source_type": "museum_open_access", "license": "CC0-1.0",
        "license_evidence": LICENSE_EVIDENCE, "license_url": LICENSE_URL,
        "selection": "逐件核查中国壁画实物；排除纸绢书画、木板画、雕塑、线描图及来源不明确的中亚对象；按正背面分开计数",
        "count": len(records), "artifact_count": len(ids),
        "unique_file_sha256_count": len({r["sha256"] for r in records}),
        "total_bytes": sum(r["bytes"] for r in records),
        "view_counts": {kind: sum(row["view_type"] == kind for row in records)
                        for kind in ("front", "front_monochrome", "reverse")},
        "excluded_assets": [{"object_id": 42716, "filename": name, "reason": reason}
                            for name, reason in EXCLUDED_IMAGE_NAMES.items()],
        "six_class_ground_truth_count": 0, "training_eligible": False,
        "github_redistribution": True, "records": records,
        "limitations": ["馆藏公开影像用于真实图片展示、标注操作、图像检索工程验证，不是病害检测训练/测试集。",
                        "18个馆藏对象不等于18个独立原址；部分碎片可能来自同一洞窟，未证明独立性。",
                        "含山西、新疆及原址待核对象，不能替代指南要求的单地域合作数据。",
                        "没有专家病害标签、标尺/色卡采集参数、现场空鼓/盐分检测、完整修复档案。",
                        "日期与年代保留馆方原始字段；若字段不一致须人工考证，项目不擅自更正。"]
    }
    _json(output / "manifest.json", manifest)
    write_support_files(output, manifest)
    print(json.dumps({k: manifest[k] for k in ("count", "artifact_count", "unique_file_sha256_count", "total_bytes", "six_class_ground_truth_count")}, ensure_ascii=False))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/public/mural_reference")
    parser.add_argument("--object-ids", nargs="+", type=int, choices=sorted(OBJECTS))
    parser.add_argument("--refresh", action="store_true", help="重新核查元数据并下载官方原图")
    args = parser.parse_args()
    fetch_public_murals(args.output, args.object_ids, args.refresh)
