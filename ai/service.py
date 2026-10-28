"""Photo quality, model-backed proposals, longitudinal alignment, and previews.

No trained checkpoint means no disease proposals. Photo-only hollowing remains
a hypothesis even when a checkpoint exists. All generated previews are marked.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
import pickle
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .labels import CLASS_NAMES, BINARY_CLASS_NAMES


def _read(path):
    with Image.open(path) as source:
        if source.width * source.height > 40_000_000:
            raise ValueError("单张图片最多 4000 万像素，请先裁剪或降采样")
        return np.array(ImageOps.exif_transpose(source).convert("RGB"))


def _data_url(rgb):
    output = io.BytesIO()
    Image.fromarray(np.uint8(rgb)).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def _quality(rgb):
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # These are engineering collection prompts, not calibrated clinical thresholds.
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    under, over = float((gray < 12).mean()), float((gray > 243).mean())
    messages = []
    if sharpness < 60:
        messages.append("纹理/边缘较弱，请检查失焦、抖动；平坦区域也可能出现此提示")
    if under > .15:
        messages.append("暗部比例较高，建议补拍均匀照明照片")
    if over > .15:
        messages.append("亮部比例较高，请检查反光和过曝；浅色底层也可能出现此提示")
    if min(gray.shape) < 512:
        messages.append("短边不足 512 像素，细小病害可能无法辨认")
    return {"sharpness_laplacian_variance": round(sharpness, 3),
            "underexposed_fraction": round(under, 5), "overexposed_fraction": round(over, 5),
            "warnings": messages, "status": "review_capture" if messages else "capture_checks_passed",
            "method": "确定性图像采集检查，非病害分类模型",
            "thresholds": {"sharpness_below": 60, "dark_gray_below": 12, "bright_gray_above": 243,
                           "exposure_fraction_above": .15, "minimum_short_edge": 512},
            "threshold_basis": "项目未标定的采集提示默认值，非国标阈值；不能作为病害诊断"}


def _load_checkpoint(checkpoint, allow_binary=False):
    import torch
    from .models import build_model
    data = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if data.get("class_names") != CLASS_NAMES and not (allow_binary and data.get("class_names") == BINARY_CLASS_NAMES):
        raise ValueError("模型类别表与 AHR 六类病害不一致；禁止自动映射")
    config = data["model_config"]
    model = build_model(**{**config, "pretrained": None})
    model.load_state_dict(data["state_dict"], strict=True)
    return model.eval(), data


def predict_probabilities(rgb, model, tile_size=512, overlap=.25):
    """Overlapping tiled inference at image resolution, identical RGB normalization."""
    import torch
    height, width = rgb.shape[:2]
    tile_size = int(tile_size)
    if tile_size < 32 or not 0 <= overlap < 1:
        raise ValueError("tile_size 必须 ≥32，0≤overlap<1")
    stride = max(1, int(tile_size * (1-overlap)))
    starts = lambda n: sorted(set(list(range(0, max(n-tile_size, 0)+1, stride)) + [max(n-tile_size, 0)]))
    probabilities = np.zeros((7, height, width), np.float32)
    counts = np.zeros((height, width), np.float32)
    with torch.inference_mode():
        for top in starts(height):
            for left in starts(width):
                patch = rgb[top:top+tile_size, left:left+tile_size]
                ph, pw = patch.shape[:2]
                patch = np.pad(patch, ((0, tile_size-ph), (0, tile_size-pw), (0, 0)), mode="edge")
                tensor = patch.astype(np.float32) / 255
                tensor = (tensor-np.array([.485, .456, .406], np.float32))/np.array([.229, .224, .225], np.float32)
                tensor = torch.from_numpy(tensor.transpose(2, 0, 1)[None].copy())
                prob = model(tensor).softmax(1)[0].cpu().numpy()[:, :ph, :pw]
                probabilities[:, top:top+ph, left:left+pw] += prob
                counts[top:top+ph, left:left+pw] += 1
    return probabilities / counts[None]


def predict_mask_tiled(rgb, model, tile_size=512, overlap=.25, num_classes=7):
    """Native-resolution overlap averaging with a rolling probability stripe.

    Memory is O(classes × tile_size × width), not O(classes × image area).
    The returned mask/maximum softmax use O(image area); no image downscaling.
    """
    import torch
    if tile_size < 32 or not 0 <= overlap < 1:
        raise ValueError("tile_size 必须 ≥32，0≤overlap<1")
    height, width = rgb.shape[:2]
    stride = max(1, int(tile_size * (1-overlap)))
    starts = lambda n: sorted(set(range(0, max(n-tile_size, 0)+1, stride)) | {max(n-tile_size, 0)})
    ys, xs = starts(height), starts(width)
    buffer = np.zeros((num_classes, min(height, tile_size), width), np.float32)
    counts = np.zeros(buffer.shape[1:], np.float32)
    mask, confidence = np.zeros((height, width), np.uint8), np.zeros((height, width), np.float32)
    base = 0
    def flush(rows):
        probs = buffer[:, :rows] / np.maximum(counts[None, :rows], 1)
        mask[base:base+rows] = probs.argmax(0)
        confidence[base:base+rows] = probs.max(0)
    with torch.inference_mode():
        for y in ys:
            if y > base:
                rows = y-base
                flush(rows)
                buffer[:, :-rows] = buffer[:, rows:]
                counts[:-rows] = counts[rows:]
                buffer[:, -rows:] = 0
                counts[-rows:] = 0
                base = y
            for x in xs:
                patch = rgb[y:y+tile_size, x:x+tile_size]
                ph, pw = patch.shape[:2]
                patch = np.pad(patch, ((0, tile_size-ph), (0, tile_size-pw), (0, 0)), mode="edge")
                tensor = patch.astype(np.float32) / 255
                tensor = (tensor-np.array([.485, .456, .406], np.float32))/np.array([.229, .224, .225], np.float32)
                tensor = torch.from_numpy(tensor.transpose(2, 0, 1)[None].copy())
                prob = model(tensor).softmax(1)[0].cpu().numpy()[:, :ph, :pw]
                if prob.shape[0] != num_classes:
                    raise ValueError("模型类别数与目标掩膜不匹配")
                buffer[:, :ph, x:x+pw] += prob
                counts[:ph, x:x+pw] += 1
        flush(height-base)
    return mask, confidence


def analyze_image(path, checkpoint=None, output_dir=None, tile_size=None, overlap=.25) -> dict:
    start = time.perf_counter()
    rgb = _read(path)
    height, width = rgb.shape[:2]
    checkpoint = checkpoint or os.getenv("AHR_MODEL_CHECKPOINT")
    result = {"width": width, "height": height, "quality": _quality(rgb), "predictions": [],
              "model_version": None, "mode": "manual_required", "status": "model_unavailable",
              "limitations": ["照片不能确诊空鼓；需现场敲击、红外或其他经专家认可的检测证据。",
                              "区域及置信度均需专家确认，不能直接作为施工依据。"]}
    if not checkpoint or not Path(checkpoint).is_file():
        result["limitations"].append("未配置经验证的六类病害权重；本次仅完成图像质量检查，请人工标注。")
        result["elapsed_ms"] = round((time.perf_counter()-start)*1000, 2)
        return result
    try:
        model, metadata = _load_checkpoint(checkpoint)
        if metadata.get("smoke_test") or metadata.get("synthetic_only"):
            result["limitations"].append("所配置权重只用于工程/合成数据冒烟测试，不启用真实病害自动识别。")
            result["elapsed_ms"] = round((time.perf_counter()-start)*1000, 2)
            return result
        size = int(tile_size or metadata.get("input_size", 512))
        mask, confidence = predict_mask_tiled(rgb, model, size, overlap)
        destination = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="ahr-mask-"))
        destination.mkdir(parents=True, exist_ok=True)
        # Unthresholded indexed mask retains the complete prediction for audit.
        mask_path, confidence_path = destination / "mask.png", destination / "confidence.png"
        if mask_path.resolve() == Path(path).resolve() or confidence_path.resolve() == Path(path).resolve():
            raise ValueError("掩膜输出不得覆盖原图")
        Image.fromarray(mask).save(mask_path)
        Image.fromarray(np.rint(np.clip(confidence, 0, 1)*65535).astype(np.uint16)).save(confidence_path)
        result.update(mask_path=str(mask_path.resolve()), confidence_path=str(confidence_path.resolve()),
                      mask_metadata={"class_names": CLASS_NAMES, "width": width, "height": height,
                                     "space": "EXIF规范化原图像素", "threshold_applied": False,
                                     "confidence_scale": 65535, "tile_size": size, "overlap": overlap,
                                     "method": "原图滑窗重叠概率均值；滚动条带累加，不缩图"})
        # This filters display proposals, not a diagnostic operating point.
        threshold = float(metadata.get("proposal_threshold", .5))
        result["proposal_threshold"] = threshold
        result["threshold_basis"] = metadata.get("threshold_basis", "未标定展示阈值，须用独立验证集和专家复核确定")
        for class_id in range(1, 7):
            binary = ((mask == class_id) & (confidence >= threshold)).astype(np.uint8)
            contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                if len(contour) < 3:
                    continue
                polygon = cv2.approxPolyDP(contour, max(.5, .001*cv2.arcLength(contour, True)), True)
                if len(polygon) < 3:
                    polygon = contour
                region = np.zeros((height, width), np.uint8)
                cv2.drawContours(region, [contour], -1, 1, -1)
                selected = (region > 0) & (binary > 0)
                result["predictions"].append({"type": CLASS_NAMES[class_id],
                    "polygon": polygon[:, 0, :].astype(int).tolist(),
                    "confidence": round(float(confidence[selected].mean()), 5),
                    "confidence_method": "区域内像素softmax均值，未校准，不代表病害存在概率",
                    "area_pixels": int(selected.sum()), "requires_confirmation": True,
                    "evidence": [f"模型 {metadata.get('version', 'unknown')} 像素分割候选，未由专家确认"],
                    "field_verification_required": class_id == 3})
        result.update(mode="model_proposals", status="awaiting_expert_confirmation",
                      model_version=metadata.get("version", Path(checkpoint).name),
                      training_data_version=metadata.get("dataset_sha256"))
    except (ImportError, ValueError, KeyError, RuntimeError, OSError, pickle.UnpicklingError, EOFError) as exc:
        result["status"] = "model_load_failed"
        result["limitations"].append(f"权重无法用于本次分析：{type(exc).__name__}；请检查本地模型配置。")
    result["elapsed_ms"] = round((time.perf_counter()-start)*1000, 2)
    return result


def compare_images(before, after) -> dict:
    """ORB/RANSAC alignment; pixel changes are observations, never efficacy claims."""
    a, b = _read(before), _read(after)
    # Avoid unbounded full-resolution matching and response size.
    scale = min(1., 1400/max(a.shape[0], a.shape[1]))
    a = cv2.resize(a, (round(a.shape[1]*scale), round(a.shape[0]*scale)))
    bscale = min(1., 1400/max(b.shape[0], b.shape[1]))
    b = cv2.resize(b, (round(b.shape[1]*bscale), round(b.shape[0]*bscale)))
    result = {"alignment_success": False, "mode": "alignment_unavailable",
              "method": "ORB 特征匹配 + RANSAC 单应变换",
              "limitations": ["像素变化同时受光照、拍摄角度、色彩和遮挡影响，不能据此认定修复有效或病害加重。",
                              "二维单应假定近似平面；起伏、曲面和局部形变需要专业配准复核。"]}
    if a.shape == b.shape and np.array_equal(a, b):
        matrix = np.eye(3)
        inliers, n_matches = 0, 0
        result["method"] = "图像像素完全相同（恒等变换）"
    else:
        orb = cv2.ORB_create(nfeatures=4000)
        ka, da = orb.detectAndCompute(cv2.cvtColor(a, cv2.COLOR_RGB2GRAY), None)
        kb, db = orb.detectAndCompute(cv2.cvtColor(b, cv2.COLOR_RGB2GRAY), None)
        if da is None or db is None or min(len(ka), len(kb)) < 8:
            result["limitations"].append("可匹配纹理不足，请补拍相同视角、含稳定参照物的图像。")
            return result
        pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(db, da, k=2)
        good = [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < .75*pair[1].distance]
        if len(good) < 8:
            result["limitations"].append("可靠匹配少于 8 个，未生成误导性的变化量。")
            return result
        source = np.float32([kb[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        target = np.float32([ka[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        matrix, valid = cv2.findHomography(source, target, cv2.RANSAC, 4.)
        inliers, n_matches = int(valid.sum()) if valid is not None else 0, len(good)
        if matrix is None or inliers < 8 or inliers/n_matches < .4 or not np.isfinite(matrix).all():
            result["limitations"].append("匹配一致性不足，自动配准失败。")
            return result
    height, width = a.shape[:2]
    aligned = cv2.warpPerspective(b, matrix, (width, height))
    overlap = cv2.warpPerspective(np.ones(b.shape[:2], np.uint8), matrix, (width, height), flags=cv2.INTER_NEAREST) > 0
    if overlap.mean() < .25:
        result["limitations"].append("共同可见区域不足 25%，请重新选择可比照片。")
        return result
    delta = np.abs(a.astype(np.float32)-aligned.astype(np.float32)).mean(axis=2)
    delta[~overlap] = 0
    heatmap = cv2.cvtColor(cv2.applyColorMap(np.uint8(np.clip(delta*3, 0, 255)), cv2.COLORMAP_TURBO), cv2.COLOR_BGR2RGB)
    overlay = np.uint8(.6*a+.4*heatmap)
    overlay[~overlap] = a[~overlap]
    result.update(alignment_success=True, mode="aligned_pixel_comparison", homography=matrix.tolist(),
                  inlier_matches=inliers, candidate_matches=n_matches,
                  overlap_fraction=round(float(overlap.mean()), 5),
                  mean_absolute_pixel_difference=round(float(delta[overlap].mean()), 4),
                  changed_fraction_at_25_gray=round(float((delta[overlap] > 25).mean()), 5),
                  change_threshold_note="25/255 为未标定的可视化差异阈值，非病害或修复效果阈值",
                  analysis_size=[width, height], reference_scale=scale, moving_scale=bscale,
                  aligned_image=_data_url(aligned), change_map=_data_url(overlay))
    return result


def _watermark(rgb, method):
    image = Image.fromarray(np.uint8(rgb))
    draw = ImageDraw.Draw(image)
    size = max(12, min(24, image.width//24))
    font = None
    for candidate in ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, size)
            break
    label = "SIMULATION ONLY - NOT HISTORICAL TRUTH"
    if image.width < 300:
        label = "SIMULATION ONLY"
    draw.rectangle((0, max(0,image.height-size*3), image.width, image.height), fill=(26, 35, 39))
    draw.text((8, max(0,image.height-size*3+4)), label, fill="white", font=font)
    draw.text((8, max(0,image.height-size*1.5)), method, fill=(249,193,114), font=font)
    return image


def simulate(image, mask, output, method=None, checkpoint=None, prompt=None) -> dict:
    """Configured LaMa/SD inference, or explicitly non-AI interpolation preview.

    LaMa expects a trusted TorchScript export taking image NCHW and mask N1HW
    tensors and returning an NCHW RGB float tensor. SD loads only local files.
    """
    rgb = _read(image)
    if isinstance(mask, (str, Path)):
        with Image.open(mask) as source:
            binary = np.asarray(source.convert("L")) > 0
    else:
        binary = np.asarray(mask) > 0
    if binary.shape != rgb.shape[:2]:
        raise ValueError("模拟掩膜必须与原始图像尺寸相同")
    if not binary.any():
        raise ValueError("请先标注需要模拟的区域")
    if binary.all():
        raise ValueError("不能将全图作为缺损区域；需要保留参考像素")
    method = method or os.getenv("AHR_INPAINT_METHOD", "interpolation")
    checkpoint = checkpoint or os.getenv("AHR_INPAINT_CHECKPOINT")
    limitations = ["这是与专家和公众沟通的模拟图，不是历史原貌证据，不得作为直接施工依据。",
                   "掩膜内内容属于推测；原始影像保持不变，输出带永久水印。"]
    if method == "interpolation":
        generated = cv2.inpaint(rgb, np.uint8(binary)*255, 3, cv2.INPAINT_TELEA)
        label = "NON-AI INTERPOLATION PREVIEW"
        limitations.append("未使用生成模型；采用 OpenCV Telea 邻域插值，仅展示局部视觉连续性。半径 3 像素为工程默认值。")
    elif method == "lama":
        if not checkpoint or not Path(checkpoint).is_file():
            raise ValueError("LaMa 模式需要本地已授权 TorchScript 权重；不会静默降级")
        import torch
        model = torch.jit.load(checkpoint, map_location="cpu").eval()
        h, w = rgb.shape[:2]
        ih, iw = (-h)%8, (-w)%8
        padded = np.pad(rgb, ((0, ih),(0, iw),(0, 0)), mode="edge")
        pmask = np.pad(binary, ((0, ih),(0, iw)), mode="constant")
        with torch.inference_mode():
            result = model(torch.from_numpy(padded.transpose(2,0,1).copy()).float()[None]/255,
                           torch.from_numpy(pmask.copy()).float()[None,None])
        if isinstance(result, dict):
            result = result["inpainted"]
        generated = np.uint8(result[0].clamp(0,1).permute(1,2,0).cpu().numpy()[:h,:w]*255)
        label = "LAMA GENERATED HYPOTHESIS"
    elif method == "stable-diffusion":
        if not checkpoint or not Path(checkpoint).is_dir():
            raise ValueError("Stable Diffusion 模式需要已授权本地 Diffusers 模型目录")
        from diffusers import AutoPipelineForInpainting
        import torch
        pipeline = AutoPipelineForInpainting.from_pretrained(checkpoint, local_files_only=True,
                                                             torch_dtype=torch.float32).to("cpu")
        h, w = rgb.shape[:2]
        size = (max(64, round(w/8)*8), max(64, round(h/8)*8))
        result = pipeline(prompt=prompt or "conservative mural surface continuity, preserve surrounding texture",
                          image=Image.fromarray(rgb).resize(size),
                          mask_image=Image.fromarray(np.uint8(binary)*255).resize(size,Image.Resampling.NEAREST),
                          generator=torch.Generator(device="cpu").manual_seed(42), num_inference_steps=25).images[0]
        generated = np.asarray(result.resize((w,h)))
        label = "DIFFUSION GENERATED HYPOTHESIS"
    else:
        raise ValueError("method 必须为 interpolation/lama/stable-diffusion")
    # Only overwrite the user-selected mask before the global provenance watermark.
    composed = rgb.copy()
    composed[binary] = generated[binary]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    _watermark(composed, label).save(output)
    uncertainty = rgb.copy()
    uncertainty[binary] = np.uint8(.45*uncertainty[binary] + .55*np.array([235,160,58]))
    uncertainty_path = output.with_name(output.stem+"_uncertainty.png")
    _watermark(uncertainty,"ORANGE = HYPOTHETICAL REGION").save(uncertainty_path)
    return {"output_path": str(output), "method": method, "mode": "communication_preview",
            "is_historical_reconstruction": False, "is_learned_model": method != "interpolation",
            "watermarked": True, "mask_pixels": int(binary.sum()), "limitations": limitations,
            "uncertainty_path":str(uncertainty_path),
            "uncertainty_type":"掩膜内全部为推测区域，颜色不是概率或经标定置信度",
            "source_sha256": hashlib.sha256(Path(image).read_bytes()).hexdigest(),
            "checkpoint": Path(checkpoint).name if checkpoint else None,
            "seed": 42 if method == "stable-diffusion" else None}
