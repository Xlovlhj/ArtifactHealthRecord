"""Convert reviewed LabelMe files and split verified site/mural groups."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.data import labelme_to_mask, split_groups
from ai.labels import CLASS_NAMES


def make_smoke_data(output):
    """Generate unambiguous geometry fixtures, explicitly unrelated to real disease."""
    import numpy as np
    from PIL import Image, ImageDraw
    output = Path(output)
    annotations = output / "annotations"
    annotations.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(8):
        image = Image.new("RGB", (96, 80), (180, 165, 142))
        draw = ImageDraw.Draw(image)
        shapes = []
        for class_id, label in enumerate(CLASS_NAMES[1:], 1):
            x = 4+(class_id-1)%3*30
            y = 4+(class_id-1)//3*35
            points = [[x+index%3,y],[x+20,y+3],[x+18,y+23],[x,y+20]]
            draw.polygon([tuple(p) for p in points], fill=(30*class_id,200-20*class_id,60+20*class_id))
            shapes.append({"label":label,"points":points,"shape_type":"polygon","flags":{}})
        name = f"synthetic_geometry_{index:02d}.png"
        image.save(annotations / name)
        annotation = {"version":"5.2.1","imagePath":name,"imageWidth":96,"imageHeight":80,
                      "shapes":shapes,"flags":{"synthetic":True,"engineering_fixture":True}}
        (annotations / Path(name).with_suffix(".json")).write_text(json.dumps(annotation,ensure_ascii=False),encoding="utf-8")
        rows.append({"image":name,"site_id":"SYNTHETIC-ENGINEERING","mural_id":str(index),
                     "data_kind":"synthetic","license":"Project-created engineering fixture",
                     "reviewed":"false"})
    csv_path = output / "groups.csv"
    with csv_path.open("w",encoding="utf-8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return prepare(annotations,csv_path,output / "prepared")


def prepare(annotations, groups, output, group_by="site_id", seed=42, folds=None, fold=0):
    source, output = Path(annotations), Path(output)
    with open(groups, encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    required = {"image", "site_id", "mural_id", "data_kind", "license", "reviewed"}
    if not rows or not required.issubset(rows[0]):
        raise ValueError(f"groups.csv 必须包含 {sorted(required)}")
    catalog = {}
    for row in rows:
        if row["image"] in catalog:
            raise ValueError(f"重复元数据: {row['image']}")
        if row["data_kind"] not in {"real", "synthetic"}:
            raise ValueError("data_kind 只能是 real/synthetic")
        if not row["license"].strip() or not row[group_by].strip():
            raise ValueError("许可与分组信息不可留空")
        if row["data_kind"] == "real" and row["reviewed"].lower() not in {"true", "yes", "1"}:
            raise ValueError(f"真实影像 {row['image']} 尚未审核，不能生成训练/评测集")
        catalog[row["image"]] = row
    records = []
    for annotation in sorted(source.rglob("*.json")):
        data = json.loads(annotation.read_text(encoding="utf-8"))
        if "shapes" not in data or "imagePath" not in data:
            continue
        relative = str((annotation.parent / data["imagePath"]).resolve().relative_to(source.resolve()))
        if relative not in catalog:
            raise ValueError(f"缺少影像元数据: {relative}")
        metadata = catalog[relative]
        name = annotation.relative_to(source).with_suffix(".png")
        record = labelme_to_mask(annotation, output / "masks" / name)
        record.update({key: metadata[key] for key in required if key != "image"})
        # Mural IDs are scoped by site to avoid accidental ID collisions.
        record["group_id"] = metadata["site_id"] if group_by == "site_id" else metadata["site_id"] + "/" + metadata["mural_id"]
        records.append(record)
    if not records:
        raise ValueError("没有可用的 LabelMe 标注")
    records = split_groups(records, seed, folds, fold)
    # Preserve content hashes across checkout relocation: the manifest is a
    # dataset-relative artifact, never a record of this developer's home path.
    for record in records:
        for key in ("image", "mask"):
            record[key] = os.path.relpath(record[key], start=output.resolve())
    summary = {split: sum(r["split"] == split for r in records) for split in ("train", "val", "test")}
    document = {"version": "ahr-six-disease-v1", "class_names": CLASS_NAMES, "ignore_index": 255,
                "group_by": group_by, "seed": seed, "folds": folds, "fold": fold,
                "counts": summary, "records": records,
                "notes": ["合成图仅训练；重叠与不确定区域在单标签目标中为255，NPZ保留独立多标签。",
                          "按遗址/壁画先分组再裁剪；同组和相同内容禁止跨集合。"]}
    output.mkdir(parents=True, exist_ok=True)
    target = output / "manifest.json"
    target.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    return target, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", help="LabelMe JSON及原图目录")
    parser.add_argument("--groups", help="已核实来源/许可/壁画组的CSV")
    parser.add_argument("--output")
    parser.add_argument("--make-smoke-data", metavar="DIRECTORY", help="生成几何工程样例；不可评价真实病害性能")
    parser.add_argument("--group-by", choices=["site_id", "mural_id"], default="site_id")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--folds", type=int)
    parser.add_argument("--fold", type=int, default=0)
    args = parser.parse_args()
    if args.make_smoke_data:
        target, counts = make_smoke_data(args.make_smoke_data)
    else:
        if not all((args.annotations, args.groups, args.output)):
            parser.error("必须提供 --annotations --groups --output，或 --make-smoke-data")
        target, counts = prepare(args.annotations, args.groups, args.output, args.group_by,
                                 args.seed, args.folds, args.fold)
    print(json.dumps({"manifest": str(target), "counts": counts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
