"""Reproducible U-Net/SegFormer training; requires a provenance manifest."""
from __future__ import annotations

import argparse
import datetime
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import torch
from torch.utils.data import DataLoader
from ai.data import SegmentationDataset, load_manifest, sha256
from ai.labels import CLASS_NAMES, BINARY_CLASS_NAMES
from ai.metrics import confusion_matrix, metrics_from_confusion
from ai.models import CombinedLoss, build_model


def evaluate_loader(model, loader, device, class_names=CLASS_NAMES):
    matrix = np.zeros((len(class_names), len(class_names)), dtype=np.int64)
    model.eval()
    with torch.inference_mode():
        for images, targets in loader:
            predictions = model(images.to(device)).argmax(1).cpu().numpy()
            matrix += confusion_matrix(targets.numpy(), predictions, len(class_names))
    return metrics_from_confusion(matrix, class_names)


def encoder_modules(model):
    if hasattr(model, "encoder"):
        return [model.encoder]
    if hasattr(model, "model") and hasattr(model.model, "segformer"):
        return [model.model.segformer]
    return [model.enc1, model.enc2, model.enc3, model.bridge]


def train(args):
    if args.epochs < 1 or args.batch_size < 1 or args.size < 32 or args.patience < 1:
        raise ValueError("epochs/batch-size/patience 必须为正，size ≥32")
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.set_num_threads(args.threads)
    torch.use_deterministic_algorithms(True, warn_only=True)
    records, data = load_manifest(args.manifest)
    if data.get("class_names") != CLASS_NAMES:
        raise ValueError("训练数据类别表不匹配")
    train_rows = [r for r in records if r["split"] == "train"]
    val_rows = [r for r in records if r["split"] == "val" and r["data_kind"] == "real"]
    if not train_rows:
        raise ValueError("训练集为空")
    if not val_rows and not args.smoke_test:
        raise ValueError("正式训练需要独立真实验证集；仅工程验证可显式 --smoke-test")
    if args.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA 不可用；使用 --device cpu")
    class_names = BINARY_CLASS_NAMES if args.task == "binary" else CLASS_NAMES
    config = {"architecture": args.model, "base_channels": args.base_channels, "pretrained": args.pretrained,
              "num_classes": len(class_names)}
    model = build_model(**config).to(args.device)
    if args.resume:
        checkpoint = torch.load(args.resume, map_location=args.device, weights_only=True)
        if checkpoint["class_names"] != class_names:
            raise ValueError("恢复模型类别表不匹配")
        model.load_state_dict(checkpoint["state_dict"])
    if args.transfer:
        checkpoint = torch.load(args.transfer, map_location=args.device, weights_only=True)
        if checkpoint["model_config"]["architecture"] != args.model:
            raise ValueError("迁移必须使用同一架构；只重用尺寸一致的非分类头张量")
        current = model.state_dict()
        transferred = {name: value for name, value in checkpoint["state_dict"].items()
                       if name in current and value.shape == current[name].shape
                       and not name.startswith(("head.", "segmentation_head.", "model.decode_head.classifier."))}
        if not transferred:
            raise ValueError("迁移检查点没有匹配张量")
        model.load_state_dict(transferred, strict=False)
    freeze_epochs = args.freeze_encoder_epochs
    if freeze_epochs is None:
        freeze_epochs = 5 if args.pretrained or args.resume or args.transfer else 0
    if freeze_epochs < 0 or (freeze_epochs and not (args.pretrained or args.resume or args.transfer)):
        raise ValueError("冻结只用于已有预训练/迁移权重的编码器，不能冻结随机初始化编码器")
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=.01)
    criterion = CombinedLoss(.5, .5)
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(SegmentationDataset(train_rows, args.size, True, args.task), batch_size=args.batch_size,
                        shuffle=True, generator=generator, num_workers=0)
    validation = DataLoader(SegmentationDataset(val_rows, args.size, task=args.task), batch_size=args.batch_size) if val_rows else None
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    history, best_score, stale = [], -float("inf"), 0
    version = f"ahr-{args.model}-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = time.perf_counter()
    for epoch in range(args.epochs):
        model.train()
        frozen = epoch < freeze_epochs
        for encoder in encoder_modules(model):
            for parameter in encoder.parameters():
                parameter.requires_grad_(not frozen)
            if frozen:
                encoder.eval()  # Freeze BatchNorm state as well as gradients.
        loss_sum, seen = 0., 0
        for images, targets in loader:
            images, targets = images.to(args.device), targets.to(args.device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), targets)
            if not torch.isfinite(loss):
                raise RuntimeError("训练损失出现非有限值")
            loss.backward()
            optimizer.step()
            loss_sum += float(loss.detach()) * len(images)
            seen += len(images)
        validation_metrics = evaluate_loader(model, validation, args.device, class_names) if validation else None
        # Smoke tests have no validation or performance metric claim.
        score = validation_metrics["macro_dice"] if validation_metrics else -loss_sum/seen
        if score is None:
            score = -loss_sum/seen
        row = {"epoch": epoch+1, "training_loss": loss_sum/seen, "validation": validation_metrics,
               "encoder_frozen": frozen}
        history.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        if score > best_score:
            best_score, stale = score, 0
            checkpoint = {"format_version": 1, "version": version, "state_dict": model.cpu().state_dict(),
                          "model_config": {**config, "pretrained": None}, "class_names": class_names, "task": args.task,
                          "input_size": args.size, "dataset_sha256": sha256(args.manifest),
                          "seed": args.seed, "epoch": epoch+1, "smoke_test": args.smoke_test,
                          "fold": data.get("fold"), "folds": data.get("folds"),
                          "synthetic_only": all(r["data_kind"] == "synthetic" for r in train_rows),
                          "validation": validation_metrics, "proposal_threshold": .5,
                          "threshold_basis": "0.5为未标定展示阈值，须经独立验证集/专家确定",
                          "torch_version": str(torch.__version__)}
            torch.save(checkpoint, output / "best.pt")
            model.to(args.device)
        else:
            stale += 1
        if validation and stale >= args.patience:
            break
    report = {"version": version, "model_config": config, "args": vars(args), "history": history,
              "augmentation": {"source": "指南§8.1", "crop": args.size, "horizontal_flip_probability": .5,
                  "rotation_degrees": [-15, 15], "brightness_factor": [.9, 1.1], "contrast_factor": [.9, 1.1],
                  "hue_saturation_changes": False, "project_defaults_not_calibrated": {
                      "blur_probability": .2, "blur_radius": [.1, .6], "jpeg_probability": .2, "jpeg_quality": [85, 100]}},
              "freeze_encoder_epochs": freeze_epochs,
              "elapsed_seconds": round(time.perf_counter()-started, 3),
              "dataset_sha256": sha256(args.manifest), "training_count": len(train_rows),
              "validation_count": len(val_rows), "test_set_used": False,
              "claim": "仅工程冒烟验证，无真实分割性能结论" if args.smoke_test else "内部验证集结果；非外部临床/保护工程验证"}
    (output / "training.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="runtime/models/baseline")
    parser.add_argument("--model", choices=["unet", "unet-resnet34", "segformer-b0"], default="unet-resnet34")
    parser.add_argument("--task", choices=["binary", "multiclass"], default="multiclass", help="binary先学习病害区域，multiclass学习六类；二者类别表隔离")
    parser.add_argument("--pretrained", help="SegFormer本地目录/Hub ID，或ResNet官方本地.pth/imagenet；已下载默认ResNet路径自动采用，未下载明确报错")
    parser.add_argument("--resume", help="本项目检查点，用于迁移微调；非完整优化器断点恢复")
    parser.add_argument("--transfer", help="同架构二分类→六类等迁移；仅加载形状匹配的非分类头")
    parser.add_argument("--freeze-encoder-epochs", type=int, help="预训练/迁移默认5轮；随机初始化默认0轮，随后全部解冻")
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--lr", type=float, default=6e-5)
    parser.add_argument("--patience", type=int, default=10)
    parser.add_argument("--base-channels", type=int, default=16)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--smoke-test", action="store_true", help="仅验证工程可运行；权重不能用于病害分析服务")
    args = parser.parse_args()
    if args.model == "unet-resnet34" and not args.pretrained and not args.resume and not args.transfer:
        local = Path("runtime/models/resnet34/resnet34-b627a593.pth")
        if local.is_file():
            args.pretrained = str(local)
        elif not args.smoke_test:
            parser.error("指南默认ResNet34预训练基线需要先 python3 scripts/fetch_models.py --models resnet34；或明确选择 --model unet")
    train(args)


if __name__ == "__main__":
    main()
