import io
import json
import zipfile
import hashlib
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.ahr.main import app
from backend.ahr.geometry import validate_polygon,calibration
from backend.ahr.rules import positive_phrase,check_plan
from backend.ahr.generation import validate_sections
from backend.ahr.knowledge import load_sources


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:yield c


def login(client,username="restorer"):
    result=client.post("/api/v1/auth/login",json={"username":username,"password":"ahr-demo-2026"})
    assert result.status_code==200,result.text
    return result.json()["user"]


def test_auth_and_scope(client):
    assert client.get("/api/v1/records").status_code==401
    login(client,"manager")
    assert client.post("/api/v1/records",json={"artifact":{"name":"denied"}}).status_code==403
    assert client.post("/api/v1/auth/logout").status_code==200
    assert client.get("/api/v1/records").status_code==401


def test_full_evidence_workflow(client):
    login(client)
    r=client.get("/api/v1/records/AHR-DEMO-001").json()
    rid=r["id"];image=r["images"][0]
    # Worker has no trained weights: no fabricated model predictions.
    job=client.post(f"/api/v1/images/{image['id']}/analyze").json()
    result=client.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["status"]=="completed",result
    assert result["result"]["predictions"]==[]
    assert result["result"]["mode"]=="manual_required"
    # Correct geometry area and calibrated area.
    items=[{"type":"裂隙","polygon":[[100,100],[200,100],[200,200],[100,200]],"evidence":"人工调查标记","confirmed":False}]
    response=client.put(f"/api/v1/records/{rid}/diseases",json={"expected_version":r["version"],"image_id":image["id"],"items":items})
    assert response.status_code==200,response.text
    r=response.json()
    assert r["diseases"][0]["area_px"]==10000
    assert r["diseases"][0]["area_cm2"]==pytest.approx(100)
    assert client.put(f"/api/v1/records/{rid}",json={"expected_version":r["version"]-1,"history":"stale"}).status_code==409
    bad=[{**items[0],"type":"空鼓","confirmed":True}]
    assert client.put(f"/api/v1/records/{rid}/diseases",json={"expected_version":r["version"],"image_id":image["id"],"items":bad}).status_code==422
    # All citations exist; the fallback must identify itself honestly.
    response=client.post(f"/api/v1/records/{rid}/plans",json={"use_llm":False})
    assert response.status_code==200,response.text
    p=response.json()
    assert len(p["sections"])==13 and p["provider"]=="template_fallback"
    assert set(p["citations"])<={s["id"] for s in load_sources()}
    sections=json.loads(json.dumps(p["sections"]))
    sections["3.6"]["content"]="完全做旧，看不出修补。"
    edited=client.put(f"/api/v1/plans/{p['id']}",json={"expected_version":p["version"],"sections":sections}).json()
    checks=client.post(f"/api/v1/plans/{edited['id']}/check").json()
    assert checks["overall"]=="block"
    assert client.post(f"/api/v1/plans/{edited['id']}/submit").status_code==409
    good=client.put(f"/api/v1/plans/{edited['id']}",json={"expected_version":edited["version"],"sections":p["sections"]}).json()
    response=client.post(f"/api/v1/plans/{good['id']}/submit")
    assert response.status_code==200,response.text
    submitted=response.json()
    assert submitted["status"]=="review"
    # Restorer cannot impersonate an expert through body fields.
    review={"decision":"approved","comment":"已核对教学流程中的证据与版本。","signature":"测试专家"}
    assert client.post(f"/api/v1/plans/{good['id']}/review",json=review).status_code==403
    expert=login(client,"expert")
    review["signature"]=expert["name"]
    response=client.post(f"/api/v1/plans/{good['id']}/review",json=review)
    assert response.status_code==200,response.text
    approved=response.json()
    assert approved["status"]=="approved" and approved["content_hash"]==submitted["content_hash"]
    assert client.post(f"/api/v1/plans/{good['id']}/review",json=review).status_code==409
    # Communication preview is watermarked and separate from the original archive.
    job=client.post(f"/api/v1/records/{rid}/simulate",json={"image_id":image["id"]}).json()
    result=client.get(f"/api/v1/jobs/{job['id']}").json()
    assert result["status"]=="completed",result
    assert client.get(result["result"]["url"]).status_code==200
    for endpoint in ("archive.pdf","disease-map.pdf"):
        response=client.get(f"/api/v1/records/{rid}/{endpoint}")
        assert response.status_code==200,response.text
        assert response.content.startswith(b"%PDF")
    package=client.get(f"/api/v1/records/{rid}/archive.zip")
    assert package.status_code==200,package.text[:200]
    with zipfile.ZipFile(io.BytesIO(package.content)) as z:
        assert not any("simulation/" in name for name in z.namelist())
        data=json.loads(z.read("record.json"))
        assert "simulations" not in data and data["simulation_register"]
        for entry in json.loads(z.read("manifest.json")):
            assert hashlib.sha256(z.read(entry["file"])).hexdigest()==entry["sha256"]
    login(client)
    r=client.get(f"/api/v1/records/{rid}").json()
    old_version=r["version"]
    r=client.put(f"/api/v1/records/{rid}",json={"expected_version":old_version,"history":"补充调查：触发重新审核"}).json()
    assert r["version"]==old_version+1
    assert next(p for p in r["plans"] if p["id"]==good["id"])["status"]=="superseded"
    assert len(r["audit"])>=8


def test_upload_preserves_bytes_and_validates(client):
    login(client,"surveyor")
    r=client.post("/api/v1/records",json={"artifact":{"name":"影像原始字节测试","region":"甘肃"},"survey":{"date":"2026-10-28"}}).json()
    rid=r["id"]
    assert client.post(f"/api/v1/records/{rid}/images",files={"file":("bad.png",b"<script>bad</script>","image/png")}).status_code==422
    out=io.BytesIO();Image.new("RGB",(640,480),"#d7c29b").save(out,format="JPEG")
    body=out.getvalue()
    response=client.post(f"/api/v1/records/{rid}/images",files={"file":("source.jpg",body,"image/jpeg")})
    assert response.status_code==200,response.text
    image=response.json()
    assert client.get(f"/api/v1/images/{image['id']}/original").content==body
    assert client.get(f"/api/v1/records/{rid}").json()["images"][0]["sha256"]==hashlib.sha256(body).hexdigest()
    invalid=client.put(f"/api/v1/images/{image['id']}/calibration",json={"points":[[0,0],[0,0]],"length_cm":10})
    assert invalid.status_code==422


def test_no_self_review_and_unknown_citations(client):
    expert=login(client,"expert")
    p=client.post("/api/v1/records/AHR-DEMO-002/plans",json={"use_llm":False}).json()
    assert client.post(f"/api/v1/plans/{p['id']}/review",json={"decision":"approved","comment":"test","signature":expert["name"]}).status_code==403
    p["sections"]["3.1"]["citations"]=["NONEXISTENT-CLAUSE"]
    response=client.put(f"/api/v1/plans/{p['id']}",json={"expected_version":p["version"],"sections":p["sections"]})
    assert response.status_code==422


def test_geometry_and_negation():
    assert validate_polygon([[0,0],[20,0],[20,10],[0,10]],20,10)[1]==200
    assert calibration([[0,0],[100,0]],20,100,100)["cm_per_pixel"]==.2
    assert positive_phrase("计划完全做旧，去除修补痕迹。",r"完全做旧")
    assert not positive_phrase("禁止完全做旧。不得看不出修补。",r"完全做旧|看不出修补")
    with pytest.raises(Exception):validate_polygon([[0,0],[20,10],[0,10],[20,0]],20,10)

