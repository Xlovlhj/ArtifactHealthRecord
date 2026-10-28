"""Integrity and provenance tests; no professional accuracy claims."""
import copy
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import pytest

from ai.catalog import catalog_inventory, load_reference_catalog
from ai.data import load_manifest, sha256
from scripts.prepare_dataset import make_smoke_data


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data/public/mural_reference/manifest.json"


def copy_one_catalog(tmp_path):
    original = json.loads(CATALOG.read_text())
    row = copy.deepcopy(original["records"][0])
    document = {**original, "records": [row], "count": 1, "artifact_count": 1,
                "unique_file_sha256_count": 1, "total_bytes": row["bytes"],
                "view_counts": {kind: int(row["view_type"] == kind) for kind in ("front", "front_monochrome", "reverse")}}
    for key in ("path", "metadata_path"):
        target = tmp_path / row[key]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CATALOG.parent / row[key], target)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(document))
    return path, document


def test_entire_public_package_has_valid_cc0_sources_and_distinct_real_images():
    report = catalog_inventory(CATALOG)
    assert report["all_files_verified"] and report["six_class_ground_truth_count"] == 0
    assert report["count"] == report["unique_file_sha256_count"] == 27
    assert report["artifact_count"] == 18
    assert report["view_counts"] == {"front": 14, "front_monochrome": 5, "reverse": 8}
    assert not (CATALOG.parent / "images/met-42716-02.jpg").exists()


def test_catalog_relocates_and_rejects_image_tampering(tmp_path):
    path, document = copy_one_catalog(tmp_path)
    assert load_reference_catalog(path)["count"] == 1
    image = tmp_path / document["records"][0]["path"]
    image.write_bytes(image.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        load_reference_catalog(path)


@pytest.mark.parametrize("field,value", [("training_eligible", True), ("expert_reviewed", True),
                                         ("diseases", ["裂隙"]), ("view_type", "diagram")])
def test_unannotated_photos_cannot_be_promoted_to_disease_gold(tmp_path, field, value):
    path, document = copy_one_catalog(tmp_path)
    document["records"][0][field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        load_reference_catalog(path)


def test_official_metadata_license_must_match_even_after_rehash(tmp_path):
    path, document = copy_one_catalog(tmp_path)
    row = document["records"][0]
    metadata_path = tmp_path / row["metadata_path"]
    metadata = json.loads(metadata_path.read_text())
    metadata["isPublicDomain"] = False
    metadata_path.write_text(json.dumps(metadata))
    row["metadata_sha256"] = sha256(metadata_path)
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="许可"):
        load_reference_catalog(path)


def test_companion_multilabel_truth_is_bound_to_manifest(tmp_path):
    manifest, _ = make_smoke_data(tmp_path)
    rows, _ = load_manifest(manifest)
    assert all(row["multilabel_sha256"] for row in rows)
    path = Path(rows[0]["mask"]).with_suffix(".npz")
    # This used to alter binary gold without changing the manifest/image/mask.
    np.savez_compressed(path, disease_masks=np.zeros((6, 80, 96), dtype=np.uint8),
                        uncertain=np.zeros((80, 96), dtype=bool))
    with pytest.raises(ValueError, match="多标签.*SHA256"):
        load_manifest(manifest)


def test_reference_paths_cannot_escape_the_public_catalog(tmp_path):
    path, document = copy_one_catalog(tmp_path)
    document["records"][0]["path"] = "../outside.jpg"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="目录内"):
        load_reference_catalog(path)


def test_model_preprocessing_changes_identity_without_changing_weights(tmp_path):
    from ai.retrieval import model_identity
    (tmp_path / "config.json").write_text('{"model_type":"dinov2"}')
    (tmp_path / "model.safetensors").write_bytes(b"identity-test-only-not-a-model")
    processor = tmp_path / "preprocessor_config.json"
    processor.write_text('{"size":{"shortest_edge":224}}')
    before = model_identity(tmp_path)
    processor.write_text('{"size":{"shortest_edge":384},"do_normalize":true}')
    after = model_identity(tmp_path)
    assert before["sha256"] != after["sha256"]
    assert before["files"]["model.safetensors"] == after["files"]["model.safetensors"]
    assert before["files"]["preprocessor_config.json"] != after["files"]["preprocessor_config.json"]
