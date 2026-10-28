"""Held-out real-image assessment at native resolution with failure examples."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from PIL import Image
from ai.data import load_manifest, sha256
from ai.labels import PALETTE, BINARY_CLASS_NAMES
from ai.metrics import confusion_matrix, metrics_from_confusion
from ai.service import _load_checkpoint, _read, predict_mask_tiled


def evaluate(manifest, checkpoint, output, split="test", threads=4):
    records, _ = load_manifest(manifest)
    selected = [r for r in records if r["split"] == split]
    if not selected or any(r["data_kind"] != "real" for r in selected):
        raise ValueError("评测必须使用非空独立真实验证/测试集；合成图不可评测")
    model, metadata = _load_checkpoint(checkpoint, allow_binary=True)
    names = metadata["class_names"]
    is_binary = names == BINARY_CLASS_NAMES
    if metadata.get("smoke_test") or metadata.get("synthetic_only"):
        raise ValueError("工程/纯合成权重不能产生真实数据性能报告")
    if metadata["dataset_sha256"] != sha256(manifest):
        raise ValueError("当前数据清单与训练绑定的清单不一致；不能排除分组泄漏")
    torch.set_num_threads(threads)
    matrix = np.zeros((len(names), len(names)), np.int64)
    rows, predictions = [], {}
    for row in selected:
        rgb = _read(row["image"])
        with Image.open(row["mask"]) as source:
            target = np.asarray(source).copy()
        if is_binary:
            target[(target > 0) & (target != 255)] = 1
            archive = Path(row["mask"]).with_suffix(".npz")
            if archive.is_file():
                with np.load(archive) as multilabel:
                    target[multilabel["disease_masks"].any(0) & ~multilabel["uncertain"]] = 1
                    target[multilabel["uncertain"]] = 255
        if target.shape != rgb.shape[:2]:
            raise ValueError("评估掩膜尺寸不匹配")
        started = time.perf_counter()
        predicted, _ = predict_mask_tiled(rgb, model, metadata["input_size"], num_classes=len(names))
        elapsed = time.perf_counter()-started
        local = confusion_matrix(target, predicted, len(names))
        matrix += local
        item = {"image": row["image"], "group_id": row["group_id"],
                "inference_seconds": elapsed, "total_pixels":int(target.size),
                "ignored_pixels":int((target == 255).sum()),
                "ignored_fraction":float((target == 255).mean()),
                **metrics_from_confusion(local, names)}
        rows.append(item)
        predictions[row["image"]] = predicted
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Null/absent-disease cases remain reported but do not pretend to be perfect.
    worst = sorted(rows, key=lambda x: x["macro_dice"] if x["macro_dice"] is not None else 2)[:20]
    for index, item in enumerate(worst):
        target = output / f"failure_{index+1:02d}.png"
        Image.fromarray(np.asarray(PALETTE, dtype=np.uint8)[predictions[item["image"]]]).save(target)
        item["prediction_path"] = str(target)
        item["expert_failure_reason"] = "待人工复核，不自动编造原因"
    report = {"model_version": metadata["version"], "checkpoint_sha256": sha256(checkpoint),
              "dataset_sha256": sha256(manifest), "split": split, "sample_count": len(rows),
              "group_count": len({r["group_id"] for r in selected}),
              "test_group_ids": sorted({r["group_id"] for r in selected}),
              "fold": metadata.get("fold"), "folds": metadata.get("folds"),
              "model_config": metadata["model_config"],
              "data_kind": "real", "seed": metadata["seed"], "device": "cpu",
              "evaluation_space": "原始分辨率滑窗，不将缩小图像指标冒充原图指标",
              "task": "binary" if is_binary else "multiclass", "class_names": names,
              **metrics_from_confusion(matrix, names), "per_image": rows, "worst_cases": worst,
              "mean_inference_seconds": float(np.mean([r["inference_seconds"] for r in rows])),
              "total_pixels":sum(r["total_pixels"] for r in rows),
              "ignored_pixels":sum(r["ignored_pixels"] for r in rows),
              "ignored_fraction":sum(r["ignored_pixels"] for r in rows)/sum(r["total_pixels"] for r in rows),
              "five_fold_std": None, "notes": ["仅当前折结果；完成独立五折后再报告均值与标准差。",
                                                "重叠/不确定像素不参与指标；必须同时审阅ignored_fraction，不能忽略评测覆盖边界。",
                                                "空鼓视觉分割不是现场确诊。测试集不得用于模型选择。"]}
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def aggregate_folds(paths, output):
    reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
    if len(reports) != 5 or {r.get("fold") for r in reports} != set(range(5)):
        raise ValueError("需要且只接受 fold 0..4 的五个真实测试报告")
    groups = set()
    model_configs = {json.dumps(r.get("model_config"),sort_keys=True) for r in reports}
    if len(model_configs) != 1:
        raise ValueError("五折必须使用同一个模型架构配置")
    for report in reports:
        if report.get("data_kind") != "real" or report.get("split") != "test" or report.get("folds") != 5:
            raise ValueError("五折汇总只能使用真实测试集结果")
        current = set(report.get("test_group_ids", []))
        if not current or current & groups:
            raise ValueError("五折测试组缺失或重叠，不能报告交叉验证结果")
        groups |= current
    scores = [r["macro_dice"] for r in reports]
    if any(score is None for score in scores):
        raise ValueError("某折没有可计算的病害Dice，请检查类别覆盖")
    per_class = {}
    for label in reports[0]["per_class"]:
        values = [r["per_class"][label]["dice"] for r in reports]
        present = [v for v in values if v is not None]
        per_class[label] = {"fold_dice":values,"covered_folds":len(present),
                            "mean_dice":float(np.mean(present)) if present else None,
                            "std_dice":float(np.std(present,ddof=1)) if len(present)>1 else None}
    result = {"folds":5,"macro_dice_mean":float(np.mean(scores)),
              "macro_dice_std":float(np.std(scores,ddof=1)),"std_definition":"样本标准差 ddof=1",
              "per_class":per_class,"test_group_count":len(groups),
              "source_reports":[{"path":str(path),"sha256":sha256(path)} for path in paths],
              "notes":["某类别未覆盖全部折时，均值/标准差仅涵盖存在真值或预测的折，见covered_folds。"]}
    output = Path(output)
    output.mkdir(parents=True,exist_ok=True)
    (output/"five_fold_metrics.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest")
    parser.add_argument("--checkpoint")
    parser.add_argument("--aggregate", nargs=5, metavar="METRICS_JSON", help="汇总五折独立真实测试报告")
    parser.add_argument("--output", default="runtime/evaluation")
    parser.add_argument("--split", choices=["val", "test"], default="test")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()
    if args.aggregate:
        report = aggregate_folds(args.aggregate,args.output)
        print(json.dumps({k:report[k] for k in ("folds","macro_dice_mean","macro_dice_std")},ensure_ascii=False))
    else:
        if not args.manifest or not args.checkpoint:
            parser.error("需要 --manifest 和 --checkpoint，或 --aggregate 五个指标文件")
        report = evaluate(args.manifest, args.checkpoint, args.output, args.split, args.threads)
        print(json.dumps({k:report[k] for k in ("sample_count", "macro_dice", "evaluated_disease_classes")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
