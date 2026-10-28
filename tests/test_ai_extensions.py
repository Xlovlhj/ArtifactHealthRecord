"""Engineering contracts; constructed fixtures never measure disease performance."""
import json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image

from ai.preprocessing import preprocess_images, correct_color
from ai.retrieval import search_images
from ai.assistance import assist_annotation


def picture(tmp_path, size=(93, 57)):
    path = tmp_path / "original.png"
    rgb = np.random.default_rng(1).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(rgb).save(path)
    return path, rgb


def test_preprocessing_tiles_preserve_original_coordinates_and_padding(tmp_path):
    path, original = picture(tmp_path)
    original_bytes = path.read_bytes()
    report = preprocess_images([path], tmp_path / "derived", {"tile_size": 32, "overlap": 8})
    restored = np.zeros_like(original)
    covered = np.zeros(original.shape[:2], bool)
    for tile in report["tiles"]:
        pixels = np.asarray(Image.open(tile["path"]))
        x, y, w, h = (tile[key] for key in ("x", "y", "width", "height"))
        restored[y:y+h, x:x+w] = pixels[:h, :w]
        covered[y:y+h, x:x+w] = True
    assert covered.all() and np.array_equal(original, restored)
    assert path.read_bytes() == original_bytes
    assert json.loads((tmp_path / "derived/manifest.json").read_text())["sources"][0]["sha256"]
    with pytest.raises(ValueError, match="空"):
        preprocess_images([path], tmp_path / "derived")


def test_color_card_identity_is_fitted_and_underconstrained_rejected():
    colors = [[20, 20, 20], [180, 20, 20], [20, 180, 20], [20, 20, 180], [180, 180, 180]]
    rgb = np.asarray([[color for color in colors]] * 5, np.uint8)
    patches = [{"rect": [i, 0, 1, 5], "reference_rgb": color} for i, color in enumerate(colors)]
    corrected, evidence = correct_color(rgb, patches)
    assert np.max(np.abs(corrected.astype(int)-rgb.astype(int))) <= 1
    assert evidence["fit_rmse_linear_rgb"] < 1e-10
    with pytest.raises(ValueError):
        correct_color(rgb, patches[:3])


def test_scale_and_identity_lens_calibration(tmp_path):
    path, _ = picture(tmp_path, (100, 80))
    report = preprocess_images([path], tmp_path / "scaled", {"max_side": 50, "pixel_size_mm": .2,
        "camera_matrix": [[100, 0, 50], [0, 100, 40], [0, 0, 1]], "distortion": [0, 0, 0, 0, 0]})
    assert (report["images"][0]["width"], report["images"][0]["height"]) == (50, 40)
    assert report["images"][0]["transform"]["pixel_size_mm_xy"] == [.4, .4]


def test_failed_stitch_is_explicit(tmp_path):
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    Image.new("RGB", (100, 100)).save(a)
    Image.new("RGB", (100, 100), "white").save(b)
    with pytest.raises(ValueError, match="拼接失败"):
        preprocess_images([a, b], tmp_path / "stitched", {"stitch": True})


def test_image_retrieval_no_model_does_not_invent_scores(tmp_path):
    path, _ = picture(tmp_path)
    result = search_images(path, [{"id": "a", "path": str(path)}])
    assert result["status"] == "unavailable" and result["items"] == []


def test_retrieval_structured_filter_then_cosine(monkeypatch, tmp_path):
    """Mock feature vectors test adapter logic only, not pretrained model quality."""
    from ai import retrieval
    path, _ = picture(tmp_path)
    monkeypatch.setattr(retrieval, "model_identity", lambda _: {"sha256": "fixture"})
    monkeypatch.setattr(retrieval, "image_embedding", lambda *args: np.asarray([1., 0.]))
    result = search_images(path, [{"id": "a", "path": str(path), "region": "甘肃"},
                                 {"id": "b", "path": str(path), "region": "山西"}], tmp_path, filters={"region": "甘肃"})
    assert result["status"] == "ok" and [row["id"] for row in result["items"]] == ["a"]
    assert result["items"][0]["score"] == 1


def test_sam_prompts_validated_and_no_model_no_regions(tmp_path):
    path, _ = picture(tmp_path)
    result = assist_annotation(path, points=[[10, 12]], point_labels=[1])
    assert result["mode"] == "manual_required" and not result["predictions"]
    with pytest.raises(ValueError):
        assist_annotation(path, points=[[1000, 0]])
    with pytest.raises(ValueError):
        assist_annotation(path, box=[10, 20, 2, 3])


@pytest.mark.parametrize("size,overlap", [(32, 0), (32, .25), (48, .5), (128, .25)])
def test_rolling_native_inference_matches_full_probability_accumulation(tmp_path, size, overlap):
    import torch
    from ai.models import UNet
    from ai.service import predict_probabilities, predict_mask_tiled
    torch.set_num_threads(2)
    torch.manual_seed(2)
    model = UNet(base_channels=4).eval()
    _, rgb = picture(tmp_path)
    probabilities = predict_probabilities(rgb, model, size, overlap)
    mask, confidence = predict_mask_tiled(rgb, model, size, overlap)
    assert np.array_equal(mask, probabilities.argmax(0))
    assert np.allclose(confidence, probabilities.max(0), atol=1e-6)


def test_real_dinov2_optional_local_weights(tmp_path):
    """If official weights exist, verify actual local feature inference, not accuracy."""
    model_dir = Path(__file__).resolve().parents[1] / "runtime/models/dinov2-small"
    if not (model_dir / "provenance.json").exists():
        pytest.skip("未下载官方本地预训练模型；不以随机权重替代")
    import torch
    torch.set_num_threads(2)
    path, _ = picture(tmp_path)
    result = search_images(path, [{"id": "same", "path": str(path)}], model_dir)
    assert result["status"] == "ok", result
    assert result["items"][0]["score"] == pytest.approx(1., abs=1e-6)


def test_binary_task_union_preserves_overlap_and_keeps_unknown(tmp_path):
    from ai.data import SegmentationDataset
    path, _ = picture(tmp_path, (32, 32))
    target = np.zeros((32, 32), np.uint8)
    target[4, 4] = target[5, 5] = 255
    Image.fromarray(target).save(tmp_path / "mask.png")
    disease_masks = np.zeros((6, 32, 32), np.uint8)
    disease_masks[:2, 4, 4] = 1
    uncertain = np.zeros((32, 32), bool)
    uncertain[5, 5] = True
    np.savez(tmp_path / "mask.npz", disease_masks=disease_masks, uncertain=uncertain)
    _, mask = SegmentationDataset([{"image": path, "mask": tmp_path / "mask.png"}], size=32, task="binary")[0]
    assert mask[4, 4] == 1 and mask[5, 5] == 255


def test_binary_loss_and_wrong_task_service_rejection(tmp_path):
    import torch
    from ai.models import build_model, CombinedLoss
    from ai.labels import BINARY_CLASS_NAMES
    from ai.service import analyze_image
    torch.set_num_threads(2)
    model = build_model(base_channels=4, num_classes=2)
    logits = model(torch.zeros(1, 3, 32, 32))
    loss = CombinedLoss()(logits, torch.ones((1, 32, 32), dtype=torch.long))
    loss.backward()
    checkpoint = tmp_path / "binary.pt"
    torch.save({"class_names": BINARY_CLASS_NAMES, "state_dict": model.state_dict(),
                "model_config": {"architecture": "unet", "base_channels": 4, "num_classes": 2}}, checkpoint)
    path, _ = picture(tmp_path)
    result = analyze_image(path, checkpoint)
    assert not result["predictions"] and result["status"] == "model_load_failed"


def test_sam_optional_real_weights_prompt_forward(tmp_path):
    model_dir = Path(__file__).resolve().parents[1] / "runtime/models/sam-vit-base"
    if not (model_dir / "provenance.json").exists():
        pytest.skip("未下载官方SAM；不以随机权重替代")
    import torch
    torch.set_num_threads(2)
    path, _ = picture(tmp_path, (96, 96))
    result = assist_annotation(path, points=[[48, 48]], point_labels=[1], model_dir=model_dir)
    assert result["status"] == "ok", result
    assert result["model_version"] and result["mode"] == "sam_prompt_proposals"
    for candidate in result["predictions"]:
        assert candidate["type"] is None and candidate["requires_confirmation"]
