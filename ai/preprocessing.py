"""Reproducible, opt-in capture corrections; originals are never overwritten."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .data import sha256
from .service import _read, _quality


def _linear(rgb):
    rgb = np.asarray(rgb, np.float64) / 255
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def _srgb(linear):
    linear = np.clip(linear, 0, 1)
    return np.rint(np.where(linear <= .0031308, linear * 12.92,
                           1.055 * linear ** (1 / 2.4) - .055) * 255).astype(np.uint8)


def correct_color(rgb, patches):
    """Fit reference color-card RGB using explicit patches in input coordinates."""
    measured, references = [], []
    h, w = rgb.shape[:2]
    for patch in patches:
        x, y, pw, ph = map(int, patch["rect"])
        reference = np.asarray(patch["reference_rgb"], np.float64)
        if pw < 1 or ph < 1 or x < 0 or y < 0 or x + pw > w or y + ph > h:
            raise ValueError("色卡矩形必须在输入图像内且面积为正")
        if reference.shape != (3,) or not np.isfinite(reference).all() or ((reference < 0) | (reference > 255)).any():
            raise ValueError("色卡 reference_rgb 必须是 0..255 的三个参考值")
        measured.append(np.median(_linear(rgb[y:y+ph, x:x+pw]), axis=(0, 1)))
        references.append(_linear(reference))
    design = np.c_[np.asarray(measured), np.ones(len(measured))]
    if len(patches) < 4 or np.linalg.matrix_rank(design) < 4:
        raise ValueError("仿射色彩校正至少需要四个线性独立的色卡参考块，不能只用同色灰阶")
    coefficients, *_ = np.linalg.lstsq(design, references, rcond=None)
    corrected = _linear(rgb) @ coefficients[:3] + coefficients[3]
    residual = design @ coefficients - np.asarray(references)
    return _srgb(corrected), {"method": "linear_sRGB_affine_color_card",
        "matrix_4x3": coefficients.tolist(), "patch_count": len(patches),
        "patches": patches, "fit_rmse_linear_rgb": float(np.sqrt(np.mean(residual ** 2))),
        "clipped_pixel_fraction": float(((corrected < 0) | (corrected > 1)).any(2).mean()),
        "reference_basis": "操作者提供色卡参考值；拟合残差不是独立色差验证"}


def preprocess_images(paths, output_dir, options=None):
    """EXIF -> optional color card -> calibrated lens -> scale -> stitch -> tiles.

    options: color_patches (global or per index in color_patches_by_image),
    camera_matrix + distortion, max_side, pixel_size_mm, stitch, tile_size,
    overlap (pixels). All geometry changes are explicit in provenance.
    """
    options = dict(options or {})
    if not paths:
        raise ValueError("至少提供一张输入影像")
    allowed = {"color_patches", "color_patches_by_image", "camera_matrix", "distortion",
               "max_side", "pixel_size_mm", "stitch", "tile_size", "overlap"}
    if set(options) - allowed:
        raise ValueError(f"未知预处理参数: {sorted(set(options) - allowed)}")
    output = Path(output_dir).resolve()
    source_paths = [Path(path).resolve() for path in paths]
    # A fresh derivative directory prevents accidental changes to originals or prior runs.
    if output.exists() and any(output.iterdir()):
        raise ValueError("输出目录必须为空；原始影像和已有派生结果不得覆盖")
    output.mkdir(parents=True, exist_ok=True)
    report = {"images": [], "tiles": [], "sources": [], "operations": [],
              "model_version": "ahr-preprocessing-1", "method": "calibrated_image_processing",
              "evidence": [], "limitations": ["派生图用于观察与模型输入，原图保留为证据。"],
              "options": options}
    tile_size, overlap = int(options.get("tile_size", 0)), int(options.get("overlap", 0))
    if tile_size < 0 or overlap < 0 or (tile_size and overlap >= tile_size) or (overlap and not tile_size):
        raise ValueError("tile_size ≥0，且启用切片时 0≤overlap<tile_size")
    arrays, transforms = [], []
    for index, path in enumerate(source_paths):
        rgb = _read(path)
        h, w = rgb.shape[:2]
        with Image.open(path) as raw:
            orientation = raw.getexif().get(274, 1)
        transform = {"original_size": [w, h], "exif_orientation_applied": orientation,
                     "coordinate_reference": "EXIF 方向规范化后的原图", "steps": []}
        report["sources"].append({"path": str(path), "sha256": sha256(path),
                                  "quality_before": _quality(rgb)})
        patches = options.get("color_patches_by_image", {}).get(str(index), options.get("color_patches"))
        if patches:
            rgb, correction = correct_color(rgb, patches)
            transform["steps"].append(correction)
        if "camera_matrix" in options or "distortion" in options:
            matrix = np.asarray(options.get("camera_matrix"), np.float64)
            distortion = np.asarray(options.get("distortion"), np.float64)
            if matrix.shape != (3, 3) or distortion.size not in (4, 5, 8, 12, 14) or not np.isfinite(matrix).all() or not np.isfinite(distortion).all():
                raise ValueError("去畸变需要有效 3×3 相机内参及 4/5/8/12/14 个畸变参数")
            if matrix[0, 0] <= 0 or matrix[1, 1] <= 0 or not np.allclose(matrix[2], [0, 0, 1]):
                raise ValueError("相机内参焦距必须为正，最后一行为 [0,0,1]")
            rgb = cv2.undistort(rgb, matrix, distortion)
            transform["steps"].append({"method": "opencv_undistort", "camera_matrix": matrix.tolist(),
                                       "distortion": distortion.tolist(), "new_camera_matrix": matrix.tolist(),
                                       "border": "constant_zero", "requires_reannotation": True})
        max_side = int(options.get("max_side", 0))
        if max_side < 0:
            raise ValueError("max_side 必须 ≥0，0 表示不缩放")
        scale = min(1., max_side / max(h, w)) if max_side else 1.
        if scale < 1:
            rgb = cv2.resize(rgb, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
            transform["steps"].append({"method": "resize", "scale_xy": [rgb.shape[1]/w, rgb.shape[0]/h]})
        if options.get("pixel_size_mm") is not None:
            mm = float(options["pixel_size_mm"])
            if not np.isfinite(mm) or mm <= 0:
                raise ValueError("pixel_size_mm 必须是根据实测标尺确定的正数")
            transform["pixel_size_mm_xy"] = [mm*w/rgb.shape[1], mm*h/rgb.shape[0]]
            transform["scale_basis"] = "操作者提供的平面标尺；透视/镜头校正后局部尺度可能变化"
        arrays.append(rgb)
        transforms.append(transform)
    if options.get("stitch"):
        if len(arrays) < 2:
            raise ValueError("拼接至少需要两幅有重叠的照片")
        stitcher = cv2.Stitcher_create(cv2.Stitcher_SCANS)
        status, mosaic = stitcher.stitch([cv2.cvtColor(a, cv2.COLOR_RGB2BGR) for a in arrays])
        if status != cv2.Stitcher_OK:
            raise ValueError(f"拼接失败，OpenCV 状态 {status}；请检查重叠/拍摄几何，不生成伪拼接图")
        arrays = [cv2.cvtColor(mosaic, cv2.COLOR_BGR2RGB)]
        transforms = [{"method": "opencv_stitcher_scans", "inputs": transforms,
                       "coordinate_reference": "拼接图独立坐标系", "requires_reannotation": True,
                       "mapping_to_original": None}]
        report["limitations"].append("自动拼接不输出可靠逐像素原图映射；须在拼接图重新标注，禁止直接搬用原坐标。")
    for index, (rgb, transform) in enumerate(zip(arrays, transforms)):
        path = output / f"image-{index:03d}.png"
        Image.fromarray(rgb).save(path)
        h, w = rgb.shape[:2]
        entry = {"path": str(path), "width": w, "height": h, "sha256": sha256(path),
                 "transform": transform, "source_indices": list(range(len(source_paths))) if options.get("stitch") else [index],
                 "quality_after": _quality(rgb)}
        report["images"].append(entry)
        if tile_size:
            stride = tile_size - overlap
            for y in range(0, h, stride):
                for x in range(0, w, stride):
                    tile = rgb[y:y+tile_size, x:x+tile_size]
                    th, tw = tile.shape[:2]
                    padded = np.pad(tile, ((0, tile_size-th), (0, tile_size-tw), (0, 0)), mode="edge")
                    target = output / f"image-{index:03d}-tile-{y}-{x}.png"
                    Image.fromarray(padded).save(target)
                    report["tiles"].append({"path": str(target), "parent": str(path), "x": x, "y": y,
                        "width": tw, "height": th, "stored_size": tile_size, "padding": "edge",
                        "source_indices": entry["source_indices"], "group_policy": "继承原图遗址/壁画 group_id；切片后不得重新随机划分"})
    report["operations"] = [step["method"] for transform in transforms for step in transform.get("steps", [])]
    if options.get("stitch"):
        report["operations"].append("opencv_stitcher_scans")
    if tile_size:
        report["operations"].append("overlapping_tiles")
    report["evidence"] = [{"source_sha256": s["sha256"], "path": s["path"]} for s in report["sources"]]
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
