"""Boundary tests for evidence integrity, geometry, and trainable AI components."""
import json
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from ai.data import labelme_to_mask, split_groups, validate_manifest
from ai.metrics import confusion_matrix, metrics_from_confusion
from ai.service import analyze_image, compare_images, simulate


def test_labelme_non_square_overlap_and_uncertainty(tmp_path):
    Image.new("RGB", (70, 40), "gray").save(tmp_path / "mural.png")
    annotation = {"imagePath":"mural.png","imageWidth":70,"imageHeight":40,
                  "shapes":[
                      {"label":"起甲","points":[[2,2],[25,2],[25,25],[2,25]]},
                      {"label":"裂隙","points":[[20,20],[35,20],[35,35],[20,35]]},
                      {"label":"酥碱","points":[[50,5],[60,5],[60,15]],"flags":{"uncertain":True}}]}
    path = tmp_path / "mural.json"
    path.write_text(json.dumps(annotation),encoding="utf-8")
    result = labelme_to_mask(path,tmp_path / "mask.png")
    mask = np.asarray(Image.open(result["mask"]))
    assert mask.shape == (40,70)
    assert mask[10,10] == 1 and mask[30,30] == 4
    assert mask[22,22] == 255 and mask[7,57] == 255
    archived = np.load(tmp_path / "mask.npz")
    assert archived["disease_masks"][0,22,22] == 1
    assert archived["disease_masks"][3,22,22] == 1


def test_annotation_wrong_dimensions_is_rejected(tmp_path):
    Image.new("RGB",(80,40)).save(tmp_path / "photo.png")
    path = tmp_path / "photo.json"
    path.write_text(json.dumps({"imagePath":"photo.png","imageWidth":40,"imageHeight":80,"shapes":[]}))
    with pytest.raises(ValueError,match="尺寸"):
        labelme_to_mask(path,tmp_path / "mask.png")


def test_group_split_and_exact_duplicate_leakage():
    records = [{"group_id":f"cave-{i//2}","image_sha256":str(i),"data_kind":"real"} for i in range(12)]
    records.append({"group_id":"synth-1","image_sha256":"synth","data_kind":"synthetic"})
    result = split_groups(records,42)
    assert {r["split"] for r in result} == {"train","val","test"}
    assert result[-1]["split"] == "train"
    for group in {r["group_id"] for r in result}:
        assert len({r["split"] for r in result if r["group_id"] == group}) == 1
    result[0]["image_sha256"] = "duplicate"
    other = next(row for row in result if row["split"] != result[0]["split"])
    other["image_sha256"] = "duplicate"
    with pytest.raises(ValueError,match="相同原图"):
        validate_manifest(result)


def test_synthetic_cannot_enter_validation():
    with pytest.raises(ValueError,match="合成图"):
        validate_manifest([{"group_id":"a","image_sha256":"a","data_kind":"synthetic","split":"test"}])


def test_absent_classes_are_not_counted_as_perfect():
    target = np.array([[0,1,1],[0,255,0]])
    prediction = np.array([[0,1,0],[0,6,0]])
    metrics = metrics_from_confusion(confusion_matrix(target,prediction))
    assert metrics["per_class"]["起甲"]["dice"] == pytest.approx(2/3)
    assert metrics["per_class"]["空鼓"]["dice"] is None
    assert metrics["macro_dice"] == pytest.approx(2/3)
    assert metrics["evaluated_disease_classes"] == 1


def test_no_weights_means_no_fabricated_diagnosis(tmp_path,monkeypatch):
    monkeypatch.delenv("AHR_MODEL_CHECKPOINT",raising=False)
    image = tmp_path / "plain.png"
    Image.new("RGB",(70,40),"gray").save(image)
    result = analyze_image(image)
    assert result["width"] == 70 and result["height"] == 40
    assert result["predictions"] == [] and result["model_version"] is None
    assert result["mode"] == "manual_required"
    assert "非病害" in result["quality"]["method"]


def test_comparison_does_not_invent_alignment(tmp_path):
    before,after = tmp_path/"before.png",tmp_path/"after.png"
    Image.new("RGB",(100,80),"gray").save(before)
    Image.new("RGB",(100,80),"white").save(after)
    failed = compare_images(before,after)
    assert failed["alignment_success"] is False
    assert "mean_absolute_pixel_difference" not in failed
    identical = compare_images(before,before)
    assert identical["alignment_success"] is True
    assert identical["mean_absolute_pixel_difference"] == 0


def test_orb_alignment_recovers_known_translation(tmp_path):
    import cv2
    rng = np.random.default_rng(42)
    rgb = rng.integers(0,255,(260,340,3),dtype=np.uint8)
    shifted = cv2.warpAffine(rgb,np.float32([[1,0,9],[0,1,7]]),(340,260))
    before,after = tmp_path/"reference.png",tmp_path/"moving.png"
    Image.fromarray(rgb).save(before)
    Image.fromarray(shifted).save(after)
    report = compare_images(before,after)
    assert report["alignment_success"] is True
    matrix = np.asarray(report["homography"])
    assert matrix[0,2] == pytest.approx(-9,abs=1)
    assert matrix[1,2] == pytest.approx(-7,abs=1)
    assert report["overlap_fraction"] > .8


def test_simulation_is_separate_watermarked_and_masked(tmp_path):
    rng = np.random.default_rng(42)
    original = rng.integers(50,200,(120,200,3),dtype=np.uint8)
    path,output = tmp_path/"source.png",tmp_path/"preview.png"
    Image.fromarray(original).save(path)
    mask = np.zeros((120,200),np.uint8)
    mask[10:30,10:30] = 1
    report = simulate(path,mask,output,method="interpolation")
    assert report["is_learned_model"] is False and report["watermarked"] is True
    assert np.array_equal(np.asarray(Image.open(path)),original)
    edited = np.asarray(Image.open(output))
    assert np.array_equal(edited[:30,50:150],original[:30,50:150])
    assert not np.array_equal(edited[-20:],original[-20:])
    with pytest.raises(ValueError,match="尺寸"):
        simulate(path,np.zeros((2,3)),output)
    with pytest.raises(ValueError,match="权重"):
        simulate(path,mask,output,method="lama")


def test_unet_trains_and_ignores_uncertain_pixels():
    torch = pytest.importorskip("torch")
    from ai.models import UNet, CombinedLoss
    torch.set_num_threads(2)
    torch.manual_seed(42)
    model = UNet(base_channels=4)
    x = torch.randn(2,3,33,41)
    y = torch.randint(0,7,(2,33,41))
    y[:,:4,:] = 255
    logits = model(x)
    assert logits.shape == (2,7,33,41)
    loss = CombinedLoss()(logits,y)
    loss.backward()
    assert torch.isfinite(loss)
    assert model.head.weight.grad.abs().sum() > 0
    zero = CombinedLoss()(model(x),torch.full_like(y,255))
    assert zero.item() == 0


def test_smoke_checkpoint_never_serves_disease_predictions(tmp_path):
    torch = pytest.importorskip("torch")
    from ai.models import UNet
    from ai.labels import CLASS_NAMES
    model = UNet(base_channels=4)
    path,checkpoint = tmp_path/"input.png",tmp_path/"smoke.pt"
    Image.new("RGB",(64,64),"gray").save(path)
    torch.save({"state_dict":model.state_dict(),"model_config":{"architecture":"unet","base_channels":4},
                "class_names":CLASS_NAMES,"smoke_test":True},checkpoint)
    result = analyze_image(path,checkpoint)
    assert result["predictions"] == []
    assert result["mode"] == "manual_required"
    assert any("冒烟" in line for line in result["limitations"])


def test_segformer_optional_backend_returns_full_resolution_logits():
    torch = pytest.importorskip("torch")
    pytest.importorskip("transformers")
    from ai.models import build_model
    torch.set_num_threads(2)
    model = build_model("segformer-b0").eval()
    with torch.inference_mode():
        logits = model(torch.zeros(1,3,64,64))
    assert logits.shape == (1,7,64,64)
    assert torch.isfinite(logits).all()


def test_prepared_manifest_survives_dataset_relocation(tmp_path):
    import shutil
    from scripts.prepare_dataset import make_smoke_data
    from ai.data import load_manifest, sha256
    source = tmp_path / "old-machine" / "dataset"
    manifest, _ = make_smoke_data(source)
    original_hash = sha256(manifest)
    encoded = json.loads(manifest.read_text())
    assert all(not Path(row[key]).is_absolute() for row in encoded["records"] for key in ("image", "mask"))
    destination = tmp_path / "new-machine" / "dataset"
    shutil.copytree(source,destination)
    shutil.rmtree(source)
    relocated = destination / "prepared" / "manifest.json"
    assert sha256(relocated) == original_hash
    records, _ = load_manifest(relocated)
    assert len(records) == 8
    assert all(Path(row["image"]).is_relative_to(destination) and Path(row["mask"]).exists() for row in records)
