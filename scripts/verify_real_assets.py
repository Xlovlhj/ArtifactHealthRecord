"""Run actual local pretrained inference against the public mural photo package.

This verifies execution and records identities; it does not measure disease
accuracy or imply that SAM proposals identify any of the six diseases.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def verify(manifest_path, model_root, output, threads=2):
    import numpy as np
    import torch
    import transformers
    from PIL import Image
    from ai.assistance import assist_annotation
    from ai.catalog import catalog_inventory, load_reference_catalog
    from ai.data import sha256
    from ai.models import build_model
    from ai.retrieval import search_images, model_identity

    torch.set_num_threads(threads)
    source = Path(manifest_path)
    root = Path(model_root)
    catalog = load_reference_catalog(source)
    query = next(row for row in catalog["records"] if row["id"] == "met-42716-01")
    image_path = source.parent / query["path"]
    candidates = [{**row, "path": str(source.parent / row["path"])} for row in catalog["records"]
                  if row["id"] != query["id"]]
    started = time.perf_counter()
    retrieval = search_images(image_path, candidates, root / "dinov2-small", top_k=5,
                              filters={"view_type": ["front", "front_monochrome"]})
    retrieval_seconds = time.perf_counter() - started
    if retrieval["status"] != "ok" or len(retrieval["items"]) != 5:
        raise RuntimeError(f"DINOv2 inference failed: {retrieval}")
    # Central point in the visible main mural; only an interaction exercise.
    points = [[query["width"] // 2, query["height"] // 2]]
    started = time.perf_counter()
    assisted = assist_annotation(image_path, points=points, point_labels=[1], model_dir=root / "sam-vit-base")
    sam_seconds = time.perf_counter() - started
    if assisted["status"] != "ok":
        raise RuntimeError(f"SAM inference failed: {assisted}")
    if any(p["type"] is not None or not p["requires_confirmation"] for p in assisted["predictions"]):
        raise RuntimeError("SAM region proposals must not be assigned disease diagnoses")
    # Test the guide's actual pretrained ResNet34 encoder, with a new untrained
    # task head. We do not save/use this network as a disease checkpoint.
    weight = root / "resnet34/resnet34-b627a593.pth"
    started = time.perf_counter()
    torch.manual_seed(42)
    model = build_model("unet-resnet34", pretrained=str(weight)).eval()
    official = torch.load(weight, map_location="cpu", weights_only=True)
    encoder_equal = torch.equal(model.encoder.state_dict()["conv1.weight"], official["conv1.weight"])
    with Image.open(image_path) as image:
        array = np.asarray(image.convert("RGB").resize((128, 128)), dtype=np.float32) / 255.
    array = (array - np.asarray([.485, .456, .406], dtype=np.float32)) / np.asarray([.229, .224, .225], dtype=np.float32)
    with torch.inference_mode():
        logits = model(torch.from_numpy(array.transpose(2, 0, 1).copy()).unsqueeze(0))
    if not encoder_equal or tuple(logits.shape) != (1, 7, 128, 128) or not torch.isfinite(logits).all():
        raise RuntimeError("Pretrained encoder verification failed")
    report = {
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "command": "python3 scripts/verify_real_assets.py",
        "environment": {"python": platform.python_version(), "torch": str(torch.__version__),
                        "transformers": transformers.__version__, "device": "cpu", "threads": threads,
                        "dtype": "float32"},
        "catalog": catalog_inventory(source),
        "input": {"id": query["id"], "path": str(image_path), "sha256": query["sha256"],
                  "width": query["width"], "height": query["height"], "source_url": query["source_url"]},
        "dinov2": {**retrieval, "elapsed_seconds": round(retrieval_seconds, 4),
                   "query_itself_excluded": True, "candidate_count": len(candidates),
                   "model_files": model_identity(root / "dinov2-small")["files"]},
        "sam": {"status": assisted["status"], "mode": assisted["mode"],
                "model_version": assisted["model_version"], "model_files": model_identity(root / "sam-vit-base")["files"],
                "points": points, "point_labels": [1], "elapsed_seconds": round(sam_seconds, 4),
                "proposal_count": len(assisted["predictions"]),
                "proposals": [{key: p[key] for key in ("confidence", "confidence_method", "type", "requires_confirmation", "area_pixels")}
                              for p in assisted["predictions"]],
                "diagnosis_created": False, "limitations": assisted["limitations"]},
        "unet_resnet34": {"status": "ok", "encoder_weight_sha256": sha256(weight),
                          "official_encoder_conv1_exactly_equal": encoder_equal, "output_shape": list(logits.shape),
                          "finite_logits": True, "elapsed_seconds": round(time.perf_counter() - started, 4),
                          "segmentation_head_trained": False, "checkpoint_created": False},
        "six_class_real_dice": None,
        "claim": "公开真实壁画+官方通用预训练权重的本地工程实测；未评价六类病害精度、检索相关性或SAM专业边界质量。"
    }
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="data/public/mural_reference/manifest.json")
    parser.add_argument("--model-root", default="runtime/models")
    parser.add_argument("--output", default="ai/REAL_ASSET_VALIDATION.json")
    parser.add_argument("--threads", type=int, default=2)
    args = parser.parse_args()
    result = verify(args.manifest, args.model_root, args.output, args.threads)
    print(json.dumps({"catalog": result["catalog"], "dinov2_status": result["dinov2"]["status"],
                      "sam_status": result["sam"]["status"], "sam_proposals": result["sam"]["proposal_count"],
                      "resnet34_status": result["unet_resnet34"]["status"], "report": args.output}, ensure_ascii=False))
