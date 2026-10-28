"""Independent regression tests for evidence, permissions and review integrity.

All records/images/jobs are synthetic fixtures in conftest's temporary runtime.
No external service credentials or model inference claims are involved.
"""
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from starlette.background import BackgroundTasks

from backend.ahr import generation, knowledge, main
from backend.ahr.config import settings
from backend.ahr.db import ImageAsset, Job, SessionLocal, Simulation, User
from backend.ahr.security import hash_password
from backend.ahr.storage import get_path


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as value:
        yield value


def login(client, username="restorer"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "ahr-demo-2026"})
    # The security throttle applies per username, including successful logins.
    assert response.status_code == 200, response.text
    return response.json()["user"]


def record_fixture(client, *, is_demo=True, with_image=True):
    response = client.post("/api/v1/records", json={
        "artifact": {"name": "完整性回归：合成教学输入", "region": "甘肃"},
        "survey": {"date": "2026-10-28"}, "is_demo": is_demo,
    })
    assert response.status_code == 200, response.text
    record = response.json()
    if not with_image:
        return record, None
    output = io.BytesIO()
    Image.new("RGB", (640, 480), "#d2c1a2").save(output, format="JPEG")
    response = client.post(f"/api/v1/records/{record['id']}/images", files={
        "file": ("synthetic-integrity.jpg", output.getvalue(), "image/jpeg"),
    })
    assert response.status_code == 200, response.text
    image = response.json()
    response = client.put(f"/api/v1/images/{image['id']}/calibration", json={
        "points": [[10, 10], [110, 10]], "length_cm": 10,
    })
    assert response.status_code == 200, response.text
    return client.get(f"/api/v1/records/{record['id']}").json(), response.json()


def new_plan(client, record_id):
    response = client.post(f"/api/v1/records/{record_id}/plans", json={"use_llm": False})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(autouse=True)
def fresh_session(client):
    # Test transport shares an IP; reset only the in-memory throttle between tests.
    main.LOGIN_ATTEMPTS.clear()
    login(client)


@pytest.mark.parametrize("is_demo", [False, True])
def test_demo_flag_cannot_authorize_external_data_transmission(client, monkeypatch, is_demo):
    config = settings()
    monkeypatch.setattr(config, "llm_base_url", "https://offline.invalid/v1")
    monkeypatch.setattr(config, "llm_api_key", "offline-fixture-not-a-secret")
    monkeypatch.setattr(config, "llm_model", "offline-fixture")
    monkeypatch.setattr(config, "embedding_model", "offline-fixture")
    monkeypatch.setattr(config, "allow_external_models", False)

    def external_call_forbidden(*args, **kwargs):
        raise AssertionError("is_demo must not bypass external transmission authorization")

    monkeypatch.setattr(generation, "call_json", external_call_forbidden)
    monkeypatch.setattr(knowledge, "optional_vector_search", external_call_forbidden)
    record, _ = record_fixture(client, is_demo=is_demo, with_image=False)
    response = client.post(f"/api/v1/records/{record['id']}/plans", json={"use_llm": True})
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "template_fallback"
    response = client.post(f"/api/v1/records/{record['id']}/extract", json={"text": "只保留本地的构造测试输入"})
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "manual_fallback"
    assert client.get(f"/api/v1/records/{record['id']}/similar-cases").status_code == 200


def test_only_current_plan_and_current_record_version_can_progress(client):
    record, _ = record_fixture(client)
    rid = record["id"]
    first = new_plan(client, rid)
    assert client.post(f"/api/v1/plans/{first['id']}/submit").status_code == 200
    second = new_plan(client, rid)
    detail = client.get(f"/api/v1/records/{rid}").json()
    assert next(p for p in detail["plans"] if p["id"] == first["id"])["status"] == "superseded"
    assert detail["status"] == "draft"
    assert client.put(f"/api/v1/plans/{first['id']}", json={
        "expected_version": first["version"], "sections": first["sections"],
    }).status_code == 409
    assert client.post(f"/api/v1/plans/{first['id']}/submit").status_code == 409
    assert client.post(f"/api/v1/plans/{second['id']}/submit").status_code == 200
    expert = login(client, "expert")
    review = {"decision": "approved", "comment": "仅验证版本状态流转。", "signature": expert["name"]}
    assert client.post(f"/api/v1/plans/{first['id']}/review", json=review).status_code == 409
    assert client.post(f"/api/v1/plans/{second['id']}/review", json=review).status_code == 200
    login(client)
    third = new_plan(client, rid)
    detail = client.get(f"/api/v1/records/{rid}").json()
    assert next(p for p in detail["plans"] if p["id"] == second["id"])["status"] == "superseded"
    assert detail["status"] == "draft"
    response = client.put(f"/api/v1/records/{rid}", json={
        "expected_version": detail["version"], "history": "新增调查内容使旧方案证据版本失效",
    })
    assert response.status_code == 200, response.text
    assert client.put(f"/api/v1/plans/{third['id']}", json={
        "expected_version": third["version"], "sections": third["sections"],
    }).status_code == 409
    assert client.post(f"/api/v1/plans/{third['id']}/submit").status_code == 409


def test_plan_keeps_creation_snapshot_when_current_record_is_renamed(client):
    record, _ = record_fixture(client)
    plan = new_plan(client, record["id"])
    snapshot = plan["record_snapshot"]
    assert snapshot["artifact"]["name"] == record["artifact"]["name"]
    assert snapshot["version"] == record["version"]
    submitted = client.post(f"/api/v1/plans/{plan['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    signed_content_hash = submitted.json()["content_hash"]
    response = client.put(f"/api/v1/records/{record['id']}", json={
        "expected_version": record["version"], "artifact": {"name": "修改后的文物名，不能出现在旧方案封面"},
        "history": "生成方案后增加的新调查事实",
    })
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["artifact"]["name"] != snapshot["artifact"]["name"]
    historical = next(p for p in detail["plans"] if p["id"] == plan["id"])
    assert historical["record_snapshot"] == snapshot
    assert historical["record_version"] == record["version"]
    assert historical["content_hash"] == signed_content_hash
    assert historical["status"] == "superseded"
    exported = client.get(f"/api/v1/plans/{plan['id']}/export.pdf")
    assert exported.status_code == 200, exported.text[:100] if exported.status_code != 200 else ""
    assert exported.content.startswith(b"%PDF")


def test_original_missing_cannot_be_replaced_with_normalized_display_bytes(client):
    record, image = record_fixture(client)
    with SessionLocal() as db:
        row = db.get(ImageAsset, image["id"])
        raw = get_path(f"raw/{record['id']}/{row.id}.original")
        normalized = get_path(row.storage_key)
    original = raw.read_bytes()
    assert hashlib.sha256(original).hexdigest() == image["sha256"]
    raw.unlink()
    try:
        assert normalized.is_file()
        assert client.get(f"/api/v1/images/{image['id']}/original").status_code == 409
        assert client.get(f"/api/v1/records/{record['id']}/archive.zip").status_code == 409
    finally:
        raw.write_bytes(original)
    assert client.get(f"/api/v1/images/{image['id']}/original").content == original


def test_simulation_records_enqueue_snapshot_when_record_changes_during_queue(client, monkeypatch):
    record, image = record_fixture(client)
    polygon = [[100, 100], [180, 100], [180, 180], [100, 180]]
    response = client.put(f"/api/v1/records/{record['id']}/diseases", json={
        "expected_version": record["version"], "image_id": image["id"],
        "items": [{"type": "裂隙", "polygon": polygon}],
    })
    assert response.status_code == 200, response.text
    record = response.json()
    queued = []
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda self, func, *args, **kwargs: queued.append((func, args, kwargs)))
    response = client.post(f"/api/v1/records/{record['id']}/simulate", json={"image_id": image["id"]})
    assert response.status_code == 200, response.text
    assert len(queued) == 1
    job = response.json()
    response = client.put(f"/api/v1/records/{record['id']}", json={
        "expected_version": record["version"], "history": "排队期间新增的记录，不属于模拟输入快照",
    })
    assert response.status_code == 200, response.text
    assert response.json()["version"] > record["version"]
    worker, args, kwargs = queued[0]
    worker(*args, **kwargs)
    result = client.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["status"] == "completed", result
    with SessionLocal() as db:
        simulation = db.scalar(select(Simulation).where(Simulation.record_id == record["id"]))
        assert simulation.data["source_record_version"] == record["version"]
        assert simulation.data["source_image_sha256"] == image["sha256"]
        assert simulation.data["source_polygons"] == [polygon]


def test_model_evidence_requires_server_job_and_cannot_forge_confidence(client):
    record, image = record_fixture(client)
    polygon = [[30, 30], [90, 30], [90, 90], [30, 90]]
    item = {"type": "裂隙", "polygon": polygon, "source": "model", "confidence": .99}

    def save(value):
        latest = client.get(f"/api/v1/records/{record['id']}").json()
        return client.put(f"/api/v1/records/{record['id']}/diseases", json={
            "expected_version": latest["version"], "image_id": image["id"], "items": [value],
        })

    assert save(item).status_code == 422
    # A server-side transport fixture; it is not a trained model or a real diagnosis.
    with SessionLocal() as db:
        job = Job(user_id="offline-fixture", record_id=record["id"], kind="segmentation", status="completed", result={
            "image_id": image["id"], "image_sha256": image["sha256"], "model_version": "offline-job-fixture",
            "predictions": [{"type": "裂隙", "polygon": polygon, "confidence": .42}],
        })
        db.add(job)
        db.commit()
        job_id = job.id
    bound = {**item, "model_job_id": job_id, "proposal_index": 0}
    response = save(bound)
    assert response.status_code == 200, response.text
    disease = response.json()["diseases"][0]
    assert disease["confidence"] == .42
    assert disease["model_version"] == "offline-job-fixture"
    assert disease["model_job_id"] == job_id
    assert save({**bound, "polygon": [[40, 40], [90, 40], [90, 90], [40, 90]]}).status_code == 422
    assert save({**bound, "proposal_index": 1}).status_code == 422
    response = save({**bound, "source": "manual"})
    assert response.status_code == 200, response.text
    disease = response.json()["diseases"][0]
    assert disease["confidence"] is None and disease["model_job_id"] is None
    assert disease["model_version"] is None and disease["proposal_index"] is None


def test_signature_must_match_authenticated_reviewer(client):
    record, _ = record_fixture(client)
    plan = new_plan(client, record["id"])
    assert client.post(f"/api/v1/plans/{plan['id']}/submit").status_code == 200
    expert = login(client, "expert")
    body = {"decision": "approved", "comment": "验证签名身份绑定。", "signature": "另一个人的姓名"}
    assert client.post(f"/api/v1/plans/{plan['id']}/review", json=body).status_code == 422
    body["signature"] = expert["name"]
    response = client.post(f"/api/v1/plans/{plan['id']}/review", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["reviewer"] == expert["id"]


def test_authenticated_other_organization_cannot_read_or_change_record_evidence(client):
    record, image = record_fixture(client)
    plan = new_plan(client, record["id"])
    with SessionLocal() as db:
        outsider = User(username="integrity_other_org", name="异机构回归角色", role="expert", org="独立测试机构", password_hash=hash_password("integrity-temp-only-2026"))
        db.add(outsider)
        job = Job(user_id="offline-fixture", record_id=record["id"], kind="segmentation", status="completed", result={"image_id": image["id"], "predictions": []})
        db.add(job)
        db.commit()
        job_id = job.id
    response = client.post("/api/v1/auth/login", json={"username": "integrity_other_org", "password": "integrity-temp-only-2026"})
    assert response.status_code == 200, response.text
    for endpoint in (
        f"records/{record['id']}", f"images/{image['id']}/file", f"images/{image['id']}/original",
        f"jobs/{job_id}", f"plans/{plan['id']}/export.pdf", f"records/{record['id']}/archive.json",
        f"records/{record['id']}/disease-map.svg",
    ):
        assert client.get("/api/v1/" + endpoint).status_code == 404, endpoint
    response = client.put(f"/api/v1/records/{record['id']}", json={"expected_version": record["version"], "history": "越权修改尝试"})
    assert response.status_code == 404
    response = client.put(f"/api/v1/plans/{plan['id']}", json={"expected_version": plan["version"], "sections": plan["sections"]})
    assert response.status_code == 404
    assert client.get("/api/v1/records").json() == []


@pytest.mark.parametrize("diagnosis", [
    {"hypothesis": ["UNVALIDATED_MODEL_TEXT"]},
    {"hypothesis": "UNVALIDATED_MODEL_TEXT", "evidence": [{"not": "a string"}]},
    {"hypothesis": "UNVALIDATED_MODEL_TEXT", "extra_model_field": "not allowed"},
])
def test_malformed_model_extraction_falls_back_without_returning_unchecked_fields(client, monkeypatch, diagnosis):
    config = settings()
    monkeypatch.setattr(config, "llm_base_url", "https://offline.invalid/v1")
    monkeypatch.setattr(config, "llm_api_key", "offline-fixture-not-a-secret")
    monkeypatch.setattr(config, "llm_model", "offline-extraction-fixture")
    monkeypatch.setattr(config, "allow_external_models", True)
    calls = []

    def malformed_response(*args, **kwargs):
        calls.append(True)
        return {"chief_complaint": "UNVALIDATED_MODEL_TEXT", "history": "", "diagnosis": diagnosis}

    monkeypatch.setattr(generation, "call_json", malformed_response)
    record, _ = record_fixture(client, with_image=False)
    response = client.post(f"/api/v1/records/{record['id']}/extract", json={"text": "原始调查文字"})
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    result = response.json()
    assert result["provider"] == "manual_fallback"
    assert result["chief_complaint"] == "原始调查文字"
    assert "UNVALIDATED_MODEL_TEXT" not in json.dumps(result)
    assert client.get(f"/api/v1/records/{record['id']}").json()["version"] == record["version"]


@pytest.mark.parametrize("diagnosis", [{"hypothesis": ["invalid"]}, {"evidence": [{"forged": True}]}, {"hypothesis": "ok", "untracked": "field"}])
def test_malformed_diagnosis_cannot_enter_record(client, diagnosis):
    record, _ = record_fixture(client, with_image=False)
    response = client.put(f"/api/v1/records/{record['id']}", json={"expected_version": record["version"], "diagnosis": diagnosis})
    assert response.status_code == 422, response.text
    assert client.get(f"/api/v1/records/{record['id']}").json()["version"] == record["version"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_cannot_enter_record(client, value):
    response = client.post("/api/v1/records", content=json.dumps({"artifact": {"name": "非法浮点输入", "area_m2": value}}), headers={"content-type": "application/json"})
    assert response.status_code == 422, response.text
