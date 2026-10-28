"""Dataset import with auditable provenance and mural/site-level partitions."""
from __future__ import annotations

import hashlib
import io
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps, ImageEnhance, ImageFilter

from .labels import IGNORE_INDEX, LABELS


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def labelme_to_mask(json_path: str | Path, out_path: str | Path) -> dict:
    """Rasterize at the actual image dimensions, preserving uncertainty/overlap.

    The 7-class softmax target cannot encode two diseases at one pixel. Such
    pixels are ignored in that target, and all six independent masks are saved
    as an accompanying NPZ. No label silently overwrites another label.
    """
    source = Path(json_path)
    annotation = json.loads(source.read_text(encoding="utf-8"))
    image_path = (source.parent / annotation["imagePath"]).resolve()
    with Image.open(image_path) as image:
        width, height = image.size
        if image.getexif().get(274, 1) != 1:
            raise ValueError(f"{source.name}: 请先统一 EXIF 方向并重新核对标注坐标")
    if annotation.get("imageWidth", width) != width or annotation.get("imageHeight", height) != height:
        raise ValueError(f"{source.name}: 标注尺寸与原始图像不一致")
    channels = np.zeros((6, height, width), dtype=np.uint8)
    uncertain = np.zeros((height, width), dtype=bool)
    for shape in annotation.get("shapes", []):
        label = shape["label"].strip()
        if label not in LABELS or label == "背景":
            raise ValueError(f"未知标签 {label!r}；请人工映射，不自动猜测")
        points = shape["points"]
        if shape.get("shape_type", "polygon") != "polygon" or len(points) < 3:
            raise ValueError("训练导入只接受至少三个顶点的多边形")
        if any(not (0 <= p[0] < width and 0 <= p[1] < height) for p in points):
            raise ValueError("标注顶点超出图像像素坐标范围")
        plane = Image.new("L", (width, height), 0)
        ImageDraw.Draw(plane).polygon([tuple(p) for p in points], fill=1)
        region = np.asarray(plane, dtype=bool)
        if shape.get("flags", {}).get("uncertain", False):
            uncertain |= region
        else:
            channels[LABELS[label] - 1] |= region.astype(np.uint8)
    overlap = channels.sum(axis=0) > 1
    mask = np.zeros((height, width), dtype=np.uint8)
    for index, plane in enumerate(channels, 1):
        mask[plane.astype(bool)] = index
    mask[overlap | uncertain] = IGNORE_INDEX
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(mask).save(output)
    np.savez_compressed(output.with_suffix(".npz"), disease_masks=channels,
                        uncertain=uncertain, overlap=overlap)
    return {"image": str(image_path), "mask": str(output.resolve()), "width": width,
            "height": height, "image_sha256": sha256(image_path),
            "mask_sha256": sha256(output),
            "multilabel_sha256": sha256(output.with_suffix(".npz")),
            "annotation_sha256": sha256(source), "overlap_pixels": int(overlap.sum()),
            "uncertain_pixels": int(uncertain.sum())}


def split_groups(records: list[dict], seed: int = 42, folds: int | None = None,
                 fold: int = 0) -> list[dict]:
    """Split real site/mural groups before any cropping. Synthetic is train-only."""
    if any(not r.get("group_id") for r in records):
        raise ValueError("每幅图必须有经过人工核实的 site/mural group_id")
    groups = sorted({r["group_id"] for r in records if r["data_kind"] == "real"})
    random.Random(seed).shuffle(groups)
    if not groups:
        return [{**r, "split": "train"} for r in records]
    if len(groups) < 3:
        raise ValueError("至少需要 3 个独立真实遗址/壁画组才能隔离训练、验证、测试")
    if folds is not None:
        if folds < 3 or len(groups) < folds or not 0 <= fold < folds:
            raise ValueError("交叉验证需要 3≤folds≤真实组数，且 fold 位于有效范围")
        test = {g for i, g in enumerate(groups) if i % folds == fold}
        val = {g for i, g in enumerate(groups) if i % folds == (fold + 1) % folds}
    else:
        n_test = max(1, round(len(groups) * .15))
        n_val = max(1, round(len(groups) * .15))
        test, val = set(groups[:n_test]), set(groups[n_test:n_test + n_val])
    results = []
    for record in records:
        group = record["group_id"]
        if record["data_kind"] == "synthetic" and group in test | val:
            raise ValueError("真实验证/测试组的合成衍生图不能进入训练")
        split = "test" if group in test else "val" if group in val else "train"
        results.append({**record, "split": split})
    validate_manifest(results)
    return results


def validate_manifest(records: list[dict]) -> None:
    group_splits, image_splits = {}, {}
    for row in records:
        if row.get("data_kind") not in {"real", "synthetic"}:
            raise ValueError("data_kind 必须为 real 或 synthetic")
        if row.get("split") not in {"train", "val", "test"}:
            raise ValueError("split 必须为 train/val/test")
        if row["data_kind"] == "synthetic" and row["split"] != "train":
            raise ValueError("合成图不能进入验证/测试集")
        if not row.get("group_id"):
            raise ValueError("缺少 group_id")
        group_splits.setdefault(row["group_id"], set()).add(row["split"])
        digest = row.get("image_sha256") or sha256(row["image"])
        image_splits.setdefault(digest, set()).add(row["split"])
    if any(len(splits) > 1 for splits in group_splits.values()):
        raise ValueError("数据泄漏：同一遗址/壁画跨越多个集合")
    if any(len(splits) > 1 for splits in image_splits.values()):
        raise ValueError("数据泄漏：相同原图内容跨越多个集合")


def load_manifest(path: str | Path) -> tuple[list[dict], dict]:
    source = Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    records = data["records"]
    for record in records:
        for key in ("image", "mask"):
            record[key] = str((source.parent / record[key]).resolve())
            if not Path(record[key]).is_file():
                raise ValueError(f"数据文件不存在: {record[key]}")
        actual_digest = sha256(record["image"])
        if record.get("image_sha256") and record["image_sha256"] != actual_digest:
            raise ValueError(f"影像内容与清单SHA256不一致: {record['image']}")
        record["image_sha256"] = actual_digest
        actual_mask_digest = sha256(record["mask"])
        if record.get("mask_sha256") and record["mask_sha256"] != actual_mask_digest:
            raise ValueError(f"标注掩膜内容与清单SHA256不一致: {record['mask']}")
        record["mask_sha256"] = actual_mask_digest
        # Binary training/evaluation restores overlap from this NPZ; its bytes
        # are part of the ground truth and must be bound to the same manifest.
        archive = Path(record["mask"]).with_suffix(".npz")
        if record.get("multilabel_sha256"):
            if not archive.is_file() or sha256(archive) != record["multilabel_sha256"]:
                raise ValueError("多标签归档内容与清单SHA256不一致")
        elif archive.is_file() and record["data_kind"] == "real":
            raise ValueError("真实数据多标签归档未绑定SHA256；请重新运行prepare_dataset生成完整清单")
        if record["data_kind"] == "real":
            if str(record.get("reviewed", "")).lower() not in {"true", "yes", "1"}:
                raise ValueError("真实数据未经审核，拒绝用于训练或评测")
            if not record.get("license"):
                raise ValueError("真实数据缺少使用许可记录")
    validate_manifest(records)
    return records, data


class SegmentationDataset:
    def __init__(self, records: list[dict], size: int = 512, augment: bool = False, task="multiclass"):
        if task not in {"multiclass", "binary"}:
            raise ValueError("task 必须为 multiclass/binary")
        self.records, self.size, self.augment, self.task = records, size, augment, task

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        import torch
        record = self.records[index]
        with Image.open(record["image"]) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
        with Image.open(record["mask"]) as original_mask:
            mask = original_mask.copy()
        if self.task == "binary":
            binary = np.asarray(mask).copy()
            binary[(binary > 0) & (binary != IGNORE_INDEX)] = 1
            archive = Path(record["mask"]).with_suffix(".npz")
            if archive.is_file():
                with np.load(archive) as multilabel:
                    union = multilabel["disease_masks"].any(0)
                    uncertain = multilabel["uncertain"]
                    if union.shape != binary.shape or uncertain.shape != binary.shape:
                        raise ValueError("多标签归档与目标掩膜尺寸不符")
                    binary[union & ~uncertain] = 1
                    binary[uncertain] = IGNORE_INDEX
            mask = Image.fromarray(binary)
        if image.size != mask.size:
            raise ValueError(f"图像与掩膜尺寸不同: {record['image']}")
        values = np.unique(np.asarray(mask))
        if not all(v in {*range(7), IGNORE_INDEX} for v in values):
            raise ValueError("掩膜只允许类别 0..6 和忽略值 255")
        # Geometry is paired; image-only photometric changes follow guide §8.1.
        if self.augment and min(image.size) >= self.size:
            left = random.randint(0, image.width - self.size)
            top = random.randint(0, image.height - self.size)
            box = (left, top, left + self.size, top + self.size)
            image, mask = image.crop(box), mask.crop(box)
        image = image.resize((self.size, self.size), Image.Resampling.BILINEAR)
        mask = mask.resize((self.size, self.size), Image.Resampling.NEAREST)
        if self.augment and random.random() < .5:
            image, mask = ImageOps.mirror(image), ImageOps.mirror(mask)
        if self.augment:
            angle = random.uniform(-15, 15)
            image = image.rotate(angle, resample=Image.Resampling.BILINEAR, fillcolor=(0, 0, 0))
            mask = mask.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=IGNORE_INDEX)
            image = ImageEnhance.Brightness(image).enhance(random.uniform(.9, 1.1))
            image = ImageEnhance.Contrast(image).enhance(random.uniform(.9, 1.1))
            # The guide names light blur/JPEG, without numeric strength: these
            # explicit defaults are project engineering settings, not calibrated.
            if random.random() < .2:
                image = image.filter(ImageFilter.GaussianBlur(radius=random.uniform(.1, .6)))
            if random.random() < .2:
                stream = io.BytesIO()
                image.save(stream, format="JPEG", quality=random.randint(85, 100))
                stream.seek(0)
                with Image.open(stream) as compressed:
                    image = compressed.convert("RGB")
        x = np.asarray(image, dtype=np.float32) / 255.
        x = (x - np.array([.485, .456, .406], dtype=np.float32)) / np.array([.229, .224, .225], dtype=np.float32)
        target = np.asarray(mask, dtype=np.int64).copy()
        if self.task == "binary":
            target[(target > 0) & (target != IGNORE_INDEX)] = 1
        return torch.from_numpy(x.transpose(2, 0, 1).copy()), torch.from_numpy(target)
