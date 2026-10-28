"""Prompt-driven SAM region proposals; disease labels always come from people."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

from .retrieval import model_identity
from .service import _read, _data_url


@lru_cache(maxsize=1)
def _load_sam(directory, digest):
    from transformers import SamModel, SamProcessor
    processor = SamProcessor.from_pretrained(directory, local_files_only=True)
    model = SamModel.from_pretrained(directory, local_files_only=True).eval()
    return processor, model


def assist_annotation(path, points=None, point_labels=None, box=None, model_dir=None):
    rgb = _read(path)
    height, width = rgb.shape[:2]
    if not points and box is None:
        raise ValueError("SAM 辅助标注需要至少一个前景/背景点或一个矩形框")
    if points:
        positions = np.asarray(points, np.float64)
        if positions.ndim != 2 or positions.shape[1] != 2 or not np.isfinite(positions).all():
            raise ValueError("points 必须为有限的 [x,y] 列表")
        if (positions < 0).any() or (positions[:, 0] >= width).any() or (positions[:, 1] >= height).any():
            raise ValueError("辅助标注点超出原图范围")
        point_labels = point_labels if point_labels is not None else [1] * len(points)
        if len(point_labels) != len(points) or any(label not in (0, 1) for label in point_labels):
            raise ValueError("point_labels 必须与点一一对应：1前景、0背景")
    if box is not None:
        if len(box) != 4 or not np.isfinite(box).all() or not (0 <= box[0] < box[2] < width and 0 <= box[1] < box[3] < height):
            raise ValueError("box 必须为图像内 [x0,y0,x1,y1] 有效矩形")
    result = {"predictions": [], "mode": "manual_required", "status": "unavailable", "model_version": None,
              "width": width, "height": height, "evidence": [],
              "limitations": ["SAM 只根据点击/框选提出区域边界，不识别六类病害；操作者选择类别并确认。",
                              "IoU预测分数属于模型内部排序分数，未经本项目数据校准。"]}
    if not model_dir or not Path(model_dir).is_dir():
        result["reason"] = "未配置本地 SAM 预训练权重"
        return result
    try:
        import torch
        identity = model_identity(model_dir)
        processor, model = _load_sam(identity["directory"], identity["sha256"])
        prompts = {}
        if points:
            prompts.update(input_points=[points], input_labels=[point_labels])
        if box is not None:
            prompts["input_boxes"] = [[box]]
        inputs = processor(images=Image.fromarray(rgb), return_tensors="pt", **prompts)
        with torch.inference_mode():
            outputs = model(**inputs, multimask_output=True)
        masks = processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(), inputs["original_sizes"].cpu(), inputs["reshaped_input_sizes"].cpu())[0][0].numpy()
        scores = outputs.iou_scores[0, 0].cpu().numpy()
        for index in np.argsort(-scores):
            binary = masks[index].astype(np.uint8)
            contours, hierarchy = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
            polygons, holes = [], []
            for contour_index, contour in enumerate(contours):
                if len(contour) >= 3:
                    (holes if hierarchy[0, contour_index, 3] >= 0 else polygons).append(contour[:, 0].tolist())
            if not polygons:
                continue
            result["predictions"].append({"polygon": max(polygons, key=len), "polygons": polygons,
                "holes": holes, "mask_data_url": _data_url(binary * 255), "confidence": float(scores[index]),
                "confidence_method": "SAM predicted IoU; 未校准", "type": None,
                "requires_confirmation": True, "area_pixels": int(binary.sum())})
        result.update(mode="sam_prompt_proposals", status="ok", model_version=identity["sha256"],
                      evidence=[{"method": "SAM", "points": points or [], "point_labels": point_labels or [], "box": box,
                                 "image_coordinates": "EXIF规范化后的原图像素"}])
    except (ImportError, OSError, ValueError, RuntimeError, KeyError) as exc:
        result["reason"] = f"本地 SAM 不可用：{type(exc).__name__}: {exc}"
    return result
