"""Local pretrained CLIP / Chinese-CLIP / DINOv2 image retrieval.

No image is sent to a remote API, and no randomly initialized fallback is used.
Structured filters precede cosine ranking; no arbitrary text/image score blend.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from .data import sha256


@lru_cache(maxsize=4)
def _model_identity(directory, fingerprint):
    path = Path(directory)
    weights = [*path.glob("*.safetensors"), *path.glob("pytorch_model*.bin")]
    if not weights or not (path / "config.json").is_file():
        raise ValueError("模型目录缺少配置或真实预训练权重")
    # Processing changes image resizing/normalization and SAM coordinates. It
    # belongs to the model identity and must invalidate both processor and
    # embedding caches, even when the network weights have not changed.
    configuration_names = ("config.json", "preprocessor_config.json", "processor_config.json",
                           "image_processor_config.json", "feature_extractor_config.json",
                           "model.safetensors.index.json", "pytorch_model.bin.index.json")
    files = sorted([*weights, *[path / name for name in configuration_names if (path / name).is_file()]])
    hashes = {p.name: sha256(p) for p in files}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    return {"directory": str(path), "sha256": digest, "files": hashes}


def model_identity(directory):
    path = Path(directory).resolve()
    if not path.is_dir():
        raise ValueError("本地模型目录不存在")
    fingerprint = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(path.iterdir()) if p.is_file())
    return _model_identity(str(path), fingerprint)


@lru_cache(maxsize=3)
def _load_encoder(directory, backend, digest):
    from transformers import AutoImageProcessor, AutoModel
    processor = AutoImageProcessor.from_pretrained(directory, local_files_only=True, trust_remote_code=False, use_fast=False)
    model = AutoModel.from_pretrained(directory, local_files_only=True, trust_remote_code=False).eval()
    supported = {"dinov2": {"dinov2", "dinov2_with_registers"}, "clip": {"clip"}, "chinese_clip": {"chinese_clip"}}
    if backend not in supported or model.config.model_type not in supported[backend]:
        raise ValueError(f"模型类型 {model.config.model_type} 与检索 backend={backend} 不一致")
    return processor, model


@lru_cache(maxsize=256)
def _embed_cached(path, image_hash, directory, backend, model_digest):
    import torch
    processor, model = _load_encoder(directory, backend, model_digest)
    with Image.open(path) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("检索图片最多 4000 万像素")
        image = ImageOps.exif_transpose(source).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    with torch.inference_mode():
        features = model(**inputs).last_hidden_state[:, 0] if backend == "dinov2" else model.get_image_features(**inputs)
    vector = features[0].float().cpu().numpy()
    if not np.isfinite(vector).all() or np.linalg.norm(vector) <= 1e-12:
        raise ValueError("模型输出无效特征")
    return vector / np.linalg.norm(vector)


def image_embedding(path, model_dir, backend="dinov2"):
    identity = model_identity(model_dir)
    return _embed_cached(str(Path(path).resolve()), sha256(path), identity["directory"], backend, identity["sha256"]).copy()


def _matches(candidate, filters):
    for key, wanted in (filters or {}).items():
        if wanted is None or wanted == "" or wanted == []:
            continue
        actual = candidate.get(key)
        actual = actual if isinstance(actual, list) else [actual]
        wanted = wanted if isinstance(wanted, list) else [wanted]
        if not set(map(str, actual)) & set(map(str, wanted)):
            return False
    return True


def search_images(query_path, candidates, model_dir=None, backend="dinov2", filters=None, top_k=5):
    if not 1 <= top_k <= 100:
        raise ValueError("top_k 必须在 1..100")
    result = {"items": [], "method": f"{backend}_image_cosine_with_structured_filters",
              "model_version": None, "status": "unavailable", "errors": [],
              "filters": filters or {}, "score_definition": "L2归一化图像特征余弦相似度；不是临床相似概率",
              "limitations": ["通用预训练视觉特征未经过文物病害检索验证；相似图形不等于材料、病因或处理方法相同。"]}
    if not model_dir or not Path(model_dir).is_dir():
        result["reason"] = "未配置本地预训练图像模型，未使用随机向量代替"
        return result
    try:
        identity = model_identity(model_dir)
        query = image_embedding(query_path, model_dir, backend)
        result["model_version"] = identity["sha256"]
        selected = [row for row in candidates if _matches(row, filters)]
        result["candidate_count_after_filters"] = len(selected)
        seen = set()
        for row in selected:
            if not row.get("id") or row["id"] in seen:
                raise ValueError("候选案例必须包含唯一非空 id")
            seen.add(row["id"])
            path = row.get("path") or row.get("image_path")
            if not path or not Path(path).is_file():
                result["errors"].append({"id": row["id"], "reason": "missing_local_image"})
                continue
            vector = image_embedding(path, model_dir, backend)
            result["items"].append({"id": row["id"], "score": float(np.clip(query @ vector, -1, 1)),
                                    "match_reasons": ["本地预训练图像特征相似", *[f"结构过滤: {key}" for key in (filters or {})]],
                                    "image_sha256": sha256(path)})
        result["items"] = sorted(result["items"], key=lambda row: (-row["score"], str(row["id"])))[:top_k]
        result["status"] = "ok"
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        result.update(status="unavailable", items=[], reason=f"本地图像检索不可用：{type(exc).__name__}: {exc}")
    return result
