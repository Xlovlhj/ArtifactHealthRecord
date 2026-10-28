"""Portable real-image reference catalogs, independent of training manifests."""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from .data import sha256


def load_reference_catalog(manifest_path, verify_files=True):
    """Validate provenance and bytes before a catalog can be served or copied.

    A museum's CC0 image is a usable image, not an expert disease annotation.
    Paths in returned records remain relative and relocation-safe.
    """
    source = Path(manifest_path).resolve()
    document = json.loads(source.read_text(encoding="utf-8"))
    records = document.get("records", [])
    if not records or document.get("version") != "ahr-public-mural-reference-v1":
        raise ValueError("参考图库为空或清单版本不受支持")
    if document.get("github_redistribution") is not True:
        raise ValueError("参考图库未确认可公开再分发")
    ids, hashes, artifacts = set(), set(), set()
    for row in records:
        if not row.get("id") or row["id"] in ids or not row.get("artifact_id"):
            raise ValueError("参考影像需有唯一ID与馆藏对象ID")
        ids.add(row["id"])
        artifacts.add(row["artifact_id"])
        if row.get("license") != "CC0-1.0" or row.get("github_redistribution") is not True:
            raise ValueError(f"影像未确认开放许可: {row['id']}")
        if row.get("data_kind") != "real_image_unannotated" or row.get("training_eligible") is not False:
            raise ValueError("未标注参考影像不能被标为病害训练数据")
        if row.get("view_type") not in {"front", "front_monochrome", "reverse"}:
            raise ValueError("参考照片必须明确正面、黑白正面或背面；线描图不可冒充照片")
        if row.get("expert_reviewed") is not False or row.get("six_class_annotation") is not None or row.get("diseases"):
            raise ValueError("参考图库不允许携带未经独立审核的病害标签")
        provenance = row.get("provenance", {})
        if (provenance.get("source_type") != "public_dataset" or not provenance.get("source_url")
                or not provenance.get("license_url") or not provenance.get("permission_evidence")
                or "redistribution" not in provenance.get("allowed_uses", [])):
            raise ValueError("缺少逐图来源或公开再分发依据")
        if "evaluation" in provenance.get("allowed_uses", []) or "training" in provenance.get("allowed_uses", []):
            raise ValueError("当前参考包尚未完成训练/评测的数据审核")
        for path_field, hash_field in (("path", "sha256"), ("metadata_path", "metadata_sha256")):
            relative = Path(row[path_field])
            path = (source.parent / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(source.parent):
                raise ValueError("参考清单路径必须位于图库目录内")
            if not path.is_file():
                raise ValueError(f"参考文件缺失: {relative}")
            if verify_files and sha256(path) != row[hash_field]:
                raise ValueError(f"参考文件SHA256不符: {relative}")
        if verify_files:
            with Image.open(source.parent / row["path"]) as image:
                if image.size != (row["width"], row["height"]):
                    raise ValueError(f"参考图像尺寸与清单不符: {row['id']}")
                image.verify()
            metadata = json.loads((source.parent / row["metadata_path"]).read_text(encoding="utf-8"))
            allowed_urls = [metadata.get("primaryImage"), *metadata.get("additionalImages", [])]
            if (metadata.get("isPublicDomain") is not True or row["download_url"] not in allowed_urls
                    or row["artifact_id"] != f"met-{metadata.get('objectID')}"):
                raise ValueError("逐件馆方许可/对象/下载URL与清单不一致")
        hashes.add(row["sha256"])
    if document.get("count") != len(records) or document.get("artifact_count") != len(artifacts):
        raise ValueError("参考影像数或对象数与清单不符")
    if document.get("unique_file_sha256_count") != len(hashes):
        raise ValueError("独立文件数与清单不符，不可把同一文件多次计数")
    if document.get("six_class_ground_truth_count") != 0:
        raise ValueError("未标注参考图库的六类真值数量必须为0")
    expected_views = {kind: sum(row["view_type"] == kind for row in records)
                      for kind in ("front", "front_monochrome", "reverse")}
    if document.get("view_counts") != expected_views:
        raise ValueError("正背面视图统计与逐图记录不符")
    return document


def catalog_inventory(manifest_path):
    document = load_reference_catalog(manifest_path)
    return {"manifest_sha256": sha256(manifest_path), "count": document["count"],
            "artifact_count": document["artifact_count"],
            "unique_file_sha256_count": document["unique_file_sha256_count"],
            "total_bytes": sum(row["bytes"] for row in document["records"]),
            "view_counts": document["view_counts"],
            "six_class_ground_truth_count": 0, "training_eligible": False,
            "all_files_verified": True, "license": document["license"]}
