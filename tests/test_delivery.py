import importlib.util
import json
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_release_excludes_private_data_and_keeps_public_samples(tmp_path):
    delivery=module("ahr_deploy",ROOT/"deploy.py")
    files=["README.md", ".env", ".env.example", "runtime/demo-access.json", "data/external/restricted.jpg",
           "data/public/mural_reference/image.jpg", "data/public/mural_reference/manifest.json",
           "data/knowledge/sources.json", "frontend/dist/index.html", "frontend/node_modules/x.js", "ai/model.pt"]
    for name in files:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("fixture")
    selected={str(p.relative_to(tmp_path)) for p in delivery.release_files(tmp_path,False)}
    assert selected=={"README.md", ".env.example", "data/public/mural_reference/image.jpg",
                      "data/public/mural_reference/manifest.json", "data/knowledge/sources.json"}
    (tmp_path/"docs").mkdir()
    (tmp_path/"docs/leak").symlink_to(tmp_path/".env")
    with pytest.raises(ValueError,match="符号链接"):
        list(delivery.release_files(tmp_path))


def test_public_delivery_rejects_tampering_and_path_escape(tmp_path):
    import hashlib
    checker=module("ahr_verify_delivery",ROOT/"scripts/verify_delivery.py")
    Image.new("RGB",(12,8)).save(tmp_path/"sample.png")
    record={"id":"test", "path":"sample.png", "width":12,"height":8,
            "sha256":hashlib.sha256((tmp_path/"sample.png").read_bytes()).hexdigest(),
            "source_url":"https://example.org/fixture", "license":"test-fixture-only", "license_evidence":"fixture",
            "group_id":"object-1", "training_eligible":False,"expert_reviewed":False}
    def write():
        (tmp_path/"manifest.json").write_text(json.dumps({"records":[record]}))
    write()
    assert checker.verify_public_images(tmp_path)["checked_images"]==1
    record["sha256"]="0"*64;write()
    assert "哈希" in checker.verify_public_images(tmp_path)["errors"][0]
    record["path"]="../outside.png";write()
    assert "越过" in checker.verify_public_images(tmp_path)["errors"][0]
