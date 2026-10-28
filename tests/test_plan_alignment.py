"""Integration checks for real/reference distinctions, provenance review and standard maps.

Test uploads are synthetic fixtures; declaring source fields below tests the
workflow, not the authenticity of these deliberately constructed test bytes.
"""
import hashlib
import io
import json
import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.ahr import main
from backend.ahr.catalog import DISEASES, symbol_package
from backend.ahr.reports import disease_svg, map_pdf
from backend.ahr.symbols import symbol_geometry, inside, distance_to_segment


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:yield c


def login(client,name="restorer"):
    main.LOGIN_ATTEMPTS.clear()
    response=client.post("/api/v1/auth/login",json={"username":name,"password":"ahr-demo-2026"})
    assert response.status_code==200,response.text
    return response.json()["user"]


def photo_fixture(client,provenance=None):
    login(client)
    response=client.post("/api/v1/records",json={"artifact":{"name":"来源治理回归夹具"},"is_demo":True})
    assert response.status_code==200,response.text
    record=response.json()
    body=io.BytesIO();Image.new("RGB",(600,400),"#cbb99a").save(body,"PNG")
    response=client.post(f"/api/v1/records/{record['id']}/images",files={"file":("fixture.png",body.getvalue(),"image/png")},
                         data={"provenance":json.dumps(provenance)} if provenance else {})
    return record,response,body.getvalue()


def declared_source():
    return {"source_type":"public_dataset","source_title":"测试传输夹具，非真实来源证据",
            "source_url":"https://example.org/image","license_name":"CC0-1.0",
            "license_url":"https://creativecommons.org/publicdomain/zero/1.0/",
            "allowed_uses":["internal_display","evaluation"],"site_group":"isolated-test-fixture"}


def record_version(client,rid):
    return client.get(f"/api/v1/records/{rid}").json()["version"]


def test_provenance_is_not_inferred_and_invalid_declarations_are_rejected(client):
    record,response,_=photo_fixture(client)
    assert response.status_code==200,response.text
    image=response.json()
    assert image["provenance"]["source_type"]=="unknown"
    assert image["provenance_issues"]
    report=client.get("/api/v1/data/readiness").json()
    found=next(i for i in report["images"] if i["id"]==image["id"])
    assert found["provenance"]["review_status"]=="pending"
    version=record_version(client,record["id"])
    bad={**declared_source(),"source_type":"synthetic"}
    assert client.put(f"/api/v1/images/{image['id']}/provenance",json={"expected_version":version,"provenance":bad}).status_code==422
    for field in ("source_url","license_url"):
        bad={**declared_source(),field:"javascript:alert(1)"}
        assert client.put(f"/api/v1/images/{image['id']}/provenance",json={"expected_version":version,"provenance":bad}).status_code==422
    # A caller cannot send a fabricated reviewer via the declaration schema.
    forged={**declared_source(),"review_status":"verified"}
    assert client.put(f"/api/v1/images/{image['id']}/provenance",json={"expected_version":version,"provenance":forged}).status_code==422
    assert record_version(client,record["id"])==version


def test_independent_review_bound_to_hash_and_edit_invalidates_it(client):
    record,response,body=photo_fixture(client,declared_source())
    image=response.json();rid=record["id"];iid=image["id"]
    assert image["provenance"]["review_status"]=="pending"
    expert=login(client,"expert")
    review={"expected_version":record_version(client,rid),"decision":"verified","comment":"仅测试独立账号复核传输；不证明夹具是真实影像"}
    response=client.post(f"/api/v1/images/{iid}/provenance/review",json=review)
    assert response.status_code==200,response.text
    verified=response.json()
    assert verified["provenance"]["image_sha256"]==hashlib.sha256(body).hexdigest()
    assert verified["provenance"]["reviewer_id"]==expert["id"]
    assert client.post(f"/api/v1/images/{iid}/provenance/review",json=review).status_code==409
    edited=client.put(f"/api/v1/images/{iid}/provenance",json={"expected_version":verified["record_version"],"provenance":declared_source()})
    assert edited.status_code==200,edited.text
    assert edited.json()["provenance"]["review_status"]=="pending"
    review["expected_version"]=edited.json()["record_version"]
    assert client.post(f"/api/v1/images/{iid}/provenance/review",json=review).status_code==403
    login(client,"manager")
    assert client.put(f"/api/v1/images/{iid}/provenance",json={"expected_version":review["expected_version"],"provenance":declared_source()}).status_code==403


def test_synthetic_origin_is_retained_and_cannot_be_relabelled(client):
    source={**declared_source(),"source_type":"synthetic","allowed_uses":["training","internal_display"]}
    record,response,_=photo_fixture(client,source)
    image=response.json()
    assert response.status_code==200,response.text
    assert client.put(f"/api/v1/images/{image['id']}/provenance",json={"expected_version":record_version(client,record['id']),"provenance":declared_source()}).status_code==422
    seeded=client.get("/api/v1/records/AHR-DEMO-001").json()
    assert all(i["provenance"]["source_type"]=="synthetic" for i in seeded["images"])
    assert all("evaluation" not in i["provenance"]["allowed_uses"] for i in seeded["images"])


def test_case_edit_keeps_uploaded_evidence_and_requires_separate_review(client):
    login(client)
    data={"title":"构造病例测试","text":"测试调查依据","plan_summary":"测试过程","outcome":"测试结果",
          "source_url":"https://example.org/case","license_note":"仅测试用授权字段，不代表真实病例","completeness":"complete"}
    created=client.post("/api/v1/cases",json=data).json()
    photo=io.BytesIO();Image.new("RGB",(100,100),"white").save(photo,"PNG")
    attached=client.post(f"/api/v1/cases/{created['id']}/images",files={"file":("fixture.png",photo.getvalue(),"image/png")}).json()
    response=client.put(f"/api/v1/cases/{created['id']}",json={**data,"title":"修改标题保留证据","expected_version":attached["version"]})
    assert response.status_code==200,response.text
    edited=response.json()
    assert edited["images"]==attached["images"]
    assert client.get(edited["images"][0]["url"]).status_code==200
    login(client,"expert")
    response=client.post(f"/api/v1/cases/{created['id']}/review",json={"expected_version":edited["version"],"decision":"verified","comment":"测试独立复核"})
    assert response.status_code==200,response.text
    assert response.json()["verified"] is True
    assert client.get("/api/v1/dashboard").json()["capabilities"]["licensed_complete_cases"]>=1


def test_real_reference_catalog_import_retains_bytes_without_fabricated_disease(client):
    login(client)
    response=client.get("/api/v1/reference-images")
    assert response.status_code==200,response.text
    doc=response.json()
    assert doc["image_count"]>=18 and doc["artifact_count"]>=18
    source=doc["items"][0]
    original=client.get(source["url"])
    assert original.status_code==200
    assert hashlib.sha256(original.content).hexdigest()==source["sha256"]
    response=client.post(f"/api/v1/reference-images/{source['artifact_id']}/import")
    assert response.status_code==200,response.text
    record=response.json()
    assert record["artifact"]["record_kind"]=="public_reference"
    assert record["is_demo"] is False and not record["diseases"]
    assert not record["survey"]["date"] and not record["images"][0]["calibration"]
    image=record["images"][0]
    assert image["provenance"]["source_type"]=="public_dataset"
    assert image["provenance"]["review_status"]=="pending"
    assert "evaluation" not in image["provenance"]["allowed_uses"]
    assert client.get(f"/api/v1/images/{image['id']}/original").content==original.content
    duplicate=client.post(f"/api/v1/reference-images/{source['artifact_id']}/import").json()
    assert duplicate["id"]==record["id"] and len(duplicate["images"])==len(record["images"])
    exported=client.get(f"/api/v1/records/{record['id']}/archive.json").json()
    assert exported["images"][0]["provenance"]["source_url"]==source["source_url"]
    assert image["provenance"]["view_type"]==source["view_type"]
    # Editing the public artifact fields cannot erase or forge its reference origin.
    response=client.put(f"/api/v1/records/{record['id']}",json={"expected_version":record["version"],
        "artifact":{**record["artifact"],"name":"已编辑名称","record_kind":"survey","reference_artifact_id":"forged"}})
    assert response.status_code==200,response.text
    assert response.json()["artifact"]["record_kind"]=="public_reference"
    assert response.json()["artifact"]["reference_artifact_id"]==source["artifact_id"]


def test_centerline_persists_and_preserves_area_geometry(client):
    record,response,_=photo_fixture(client)
    image=response.json()
    item={"type":"裂隙","polygon":[[30,30],[250,30],[250,250],[30,250]],"centerline":[[40,40],[80,90],[180,200]]}
    payload={"expected_version":record_version(client,record["id"]),"image_id":image["id"],"items":[item]}
    response=client.put(f"/api/v1/records/{record['id']}/diseases",json=payload)
    assert response.status_code==200,response.text
    row=response.json()["diseases"][0]
    assert row["centerline"]==item["centerline"] and row["area_px"]==220*220
    assert row["standard_code"]=="GB/T 30237-2025-4.21"
    payload["expected_version"]=response.json()["version"]
    payload["items"][0]["centerline"]=[[0,0],[601,0]]
    assert client.put(f"/api/v1/records/{record['id']}/diseases",json=payload).status_code==422


def test_svg_pdf_use_six_symbol_definitions_and_missing_centerline_is_explicit():
    rows=[]
    for index,d in enumerate(DISEASES):
        x=(index%3)*180+10;y=(index//3)*180+10
        rows.append({"type":d["type"],"image_id":"i","polygon":[[x,y],[x+150,y],[x+150,y+150],[x,y+150]],"confirmed":True})
    image={"id":"i","width":600,"height":400,"image_type":"original"}
    data=io.BytesIO();Image.new("RGB",(600,400),"#d7c29b").save(data,"PNG")
    record={"id":"fixture","artifact":{"name":"六类图示程序回归"},"diseases":rows}
    svg=disease_svg(record,image,data.getvalue())
    root=ET.fromstring(svg)
    assert root.attrib["width"]=="190mm"
    assert "paper_mm" in svg and "中心线未录入" in svg
    for key in ("triangle","chevron","horizontal_lines","hatched_boundary_band","closed_boundary","crack_centerline"):
        assert f'data-symbol="{key}"' in svg
    crack=next(r for r in rows if r["type"]=="裂隙")
    assert not symbol_geometry(crack,.2)["paths"]
    crack["centerline"]=[[20,20],[120,120],[240,150]]
    drawn=symbol_geometry(crack,.2)
    assert len(drawn["paths"])>2 and not drawn["warnings"]
    assert "中心线未录入" not in disease_svg(record,image,data.getvalue())
    assert map_pdf(record,image,data.getvalue()).startswith(b"%PDF")
    package=symbol_package()
    assert drawn["stroke_width_mm"]==package["stroke_width_mm"]


def test_ground_loss_hatching_is_only_inside_boundary_band():
    row={"type":"地仗脱落","polygon":[[0,0],[40,0],[40,40],[0,40]]}
    geometry=symbol_geometry(row,1)
    assert geometry["paths"]
    edges=list(zip(geometry["polygon"],geometry["polygon"][1:]+geometry["polygon"][:1]))
    for a,b in geometry["paths"]:
        for weight in (.1,.5,.9):
            point=(a[0]*(1-weight)+b[0]*weight,a[1]*(1-weight)+b[1]*weight)
            assert inside(point,geometry["polygon"])
            assert min(distance_to_segment(point,c,d) for c,d in edges)<=4+1e-7
