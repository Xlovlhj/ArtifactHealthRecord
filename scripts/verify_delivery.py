"""Offline delivery checks; file integrity is separate from professional validation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REQUIRED = [
    "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", ".env.example",
    "environment.yml", "requirements.txt", "requirements-ai.txt", "run.py",
    "backend/ahr/main.py", "backend/ahr/migrations.py", "backend/ahr/reports.py",
    "backend/ahr/provenance.py", "frontend/src/App.tsx", "frontend/package-lock.json",
    "ai/models.py", "ai/data.py", "ai/assistance.py", "ai/retrieval.py", "ai/preprocessing.py",
    "scripts/train.py", "scripts/evaluate.py", "scripts/evaluate_study.py",
    "data/knowledge/symbol_package_gbt30237_2025.json",
    "data/public/mural_reference/manifest.json",
]


def verify_public_images(directory):
    from PIL import Image
    directory = Path(directory).resolve()
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    errors, checked, groups, seen, objects = [], 0, set(), set(), set()
    for row in manifest.get("records", []):
        identifier = row.get("id", "<missing id>")
        try:
            if not row.get("id") or identifier in seen:
                raise ValueError("缺失或重复的图像ID")
            seen.add(identifier)
            path = (directory / row["path"]).resolve()
            if not path.is_relative_to(directory):
                raise ValueError("影像路径越过公开数据目录")
            if not path.is_file():
                raise ValueError("原图不存在")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise ValueError("原图哈希不匹配")
            with Image.open(path) as image:
                if image.size != (row["width"], row["height"]):
                    raise ValueError("原图尺寸不匹配")
                image.verify()
            if not all(row.get(key) for key in ("source_url", "license", "license_evidence", "group_id")):
                raise ValueError("来源、许可凭据或文物分组不完整")
            if row.get("training_eligible") is not False or row.get("expert_reviewed") is not False:
                raise ValueError("公开参考图不应被标为已完成六类专家标注")
            checked += 1
            groups.add(row["group_id"])
            objects.add(row.get("artifact_id", row["group_id"]))
        except (KeyError, TypeError, ValueError, OSError) as exc:
            errors.append(f"{identifier}: {exc}")
    if not manifest.get("records"):
        errors.append("公开真实参考图清单为空")
    return {"checked_images": checked, "distinct_objects": len(objects), "distinct_source_groups": len(groups), "errors": errors,
            "six_class_annotated_images": 0, "scope": "公开参考图文件、来源字段及哈希；不是专业标注或模型准确率验收"}


def verify(root=ROOT):
    root = Path(root)
    missing = [name for name in REQUIRED if not (root / name).is_file()]
    result = {"missing_files": missing, "public_images": None}
    path = root / "data/public/mural_reference"
    if (path / "manifest.json").is_file():
        result["public_images"] = verify_public_images(path)
        from ai.catalog import catalog_inventory
        try:
            result["museum_source_verification"] = catalog_inventory(path / "manifest.json")
        except (ValueError, KeyError, TypeError, OSError) as exc:
            result["public_images"]["errors"].append(f"馆方许可/元数据核验失败: {exc}")
    result["passed"] = not missing and result["public_images"] is not None and not result["public_images"]["errors"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.root)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text+"\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
