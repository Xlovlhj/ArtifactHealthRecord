import hashlib

from fastapi.testclient import TestClient
import pytest

from backend.ahr.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username":"restorer","password":"ahr-demo-2026"})
        assert response.status_code == 200
        yield client


def test_sam_job_is_bound_to_snapshot_and_does_not_write_disease(client, monkeypatch):
    import ai.assistance
    monkeypatch.setattr(ai.assistance, "assist_annotation", lambda *a,**k: {
        "status":"ok", "predictions":[{"polygon":[[1,1],[4,1],[4,4]], "polygons":[[[1,1],[4,1],[4,4]]],
            "holes":[],"type":None,"confidence":0.5}],"model_version":"offline-test-model"})
    before = client.get("/api/v1/records/AHR-DEMO-001").json()
    image = before["images"][0]
    response = client.post(f"/api/v1/images/{image['id']}/assist",json={
        "expected_version":before["version"],"points":[[2,2]],"point_labels":[1]})
    assert response.status_code == 200
    job = client.get("/api/v1/jobs/"+response.json()["id"]).json()
    assert job["status"] == "completed"
    assert job["kind"] == "annotation_assistance"
    result = job["result"]
    assert result["source_record_version"] == before["version"]
    assert result["source_image_sha256"] == image["sha256"]
    assert result["normalized_image_sha256"] == hashlib.sha256(client.get(image["url"]).content).hexdigest()
    assert result["adoption_source"] == "manual" and result["disease_diagnosis"] is False
    after = client.get("/api/v1/records/AHR-DEMO-001").json()
    assert after["version"] == before["version"] and after["diseases"] == before["diseases"]


def test_sam_rejects_stale_version_and_invalid_prompts(client):
    record = client.get("/api/v1/records/AHR-DEMO-001").json()
    image = record["images"][0]
    url = f"/api/v1/images/{image['id']}/assist"
    base = {"expected_version":record["version"],"points":[[2,2]]}
    assert client.post(url,json={**base,"expected_version":record["version"]+1}).status_code == 409
    for update in [{"points":[]},{"points":[[-1,1]]},{"point_labels":[0,1]},
                   {"box":[4,4,2,2]},{"points":[[image["width"],2]]}]:
        assert client.post(url,json={**base,**update}).status_code == 422


def test_sam_missing_weights_is_explicit_and_manager_cannot_enqueue(client, monkeypatch):
    import ai.assistance
    monkeypatch.setattr(ai.assistance, "assist_annotation", lambda *a,**k: {
        "status":"unavailable","predictions":[],"model_version":None,"reason":"未配置本地 SAM 预训练权重"})
    record=client.get("/api/v1/records/AHR-DEMO-001").json()
    url=f"/api/v1/images/{record['images'][0]['id']}/assist"
    body={"expected_version":record["version"],"points":[[10,10]]}
    response=client.post(url,json=body)
    job=client.get("/api/v1/jobs/"+response.json()["id"]).json()
    assert job["result"]["status"]=="unavailable" and job["result"]["predictions"]==[]
    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login",json={"username":"manager","password":"ahr-demo-2026"})
    assert client.post(url,json=body).status_code==403
