"""Licensed museum photographs, explicitly separate from surveyed restoration cases."""
import hashlib
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import ROOT
from .db import Artifact, Survey, Record, ImageAsset, User, get_db, uid
from .security import current_user, require_role
from .service import record_detail, audit, authorized_record
from .schemas import ImageProvenance
from .governance import declare_provenance
from .storage import put

router=APIRouter(prefix="/api/v1")
MANIFEST=ROOT/"data/public/mural_reference/manifest.json"


def catalog(verify_files=False):
    if not MANIFEST.is_file():return {"records":[],"count":0,"artifact_count":0}
    from ai.catalog import load_reference_catalog
    try:return load_reference_catalog(MANIFEST,verify_files=verify_files)
    except (ValueError,KeyError,OSError) as exc:raise HTTPException(409,"参考图库清单或原始文件验证失败，请检查本地数据包") from exc


@router.get("/reference-images")
def reference_images(q:str="",region:str="",user:User=Depends(current_user)):
    doc=catalog()
    rows=doc["records"]
    if region:rows=[r for r in rows if region in r.get("region","")]
    if q:rows=[r for r in rows if q.casefold() in " ".join(str(r.get(k,"")) for k in ("title","title_zh","region","artifact_id")).casefold()]
    items=[{**r,"url":f"/api/v1/reference-images/{r['id']}/file"} for r in rows]
    return {"items":items,"image_count":len(items),"artifact_count":len({r["artifact_id"] for r in rows}),
            "total_image_count":doc["count"],"total_artifact_count":doc["artifact_count"],
            "notice":"馆方开放的真实壁画照片；无六类病害真值或专家修复结论，不计为甘肃实地试点、完整修复病例或模型测试集。"}


@router.get("/reference-images/{image_id}/file")
def reference_file(image_id:str,user:User=Depends(current_user)):
    row=next((r for r in catalog()["records"] if r["id"]==image_id),None)
    if not row:raise HTTPException(404,"参考影像不存在")
    path=(MANIFEST.parent/row["path"]).resolve()
    if hashlib.sha256(path.read_bytes()).hexdigest()!=row["sha256"]:raise HTTPException(409,"参考影像哈希不符")
    return FileResponse(path,media_type="image/jpeg")


@router.post("/reference-images/{artifact_id}/import")
def import_reference(artifact_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","admin")
    # Validate the complete portable evidence package, including museum metadata,
    # before using any row to create a reference record.
    rows=[r for r in catalog(True)["records"] if r["artifact_id"]==artifact_id]
    if not rows:raise HTTPException(404,"参考馆藏对象不存在")
    identity=hashlib.sha256((user.org+"\0"+artifact_id).encode()).hexdigest()[:24]
    record_id=f"AHR-REF-{identity}"
    existing=db.get(Record,record_id)
    if existing:return record_detail(db,authorized_record(db,record_id,user))
    first=rows[0]
    artifact=Artifact(id=f"ART-REF-{identity}",org=user.org,is_demo=False,data={
        "name":first.get("title_zh") or first["title"],"type":"馆藏壁画","era":first.get("object_date") or first.get("period",""),
        "region":first.get("region",""),"location":first.get("museum",""),"area_m2":None,
        "support_type":"馆方资料见来源链接","ground_type":first.get("material",""),"pigment_type":"待材料检测，不从照片推断",
        "sensitivity":"internal","record_kind":"public_reference","reference_artifact_id":artifact_id})
    db.add(artifact);db.flush()
    survey=Survey(artifact_id=artifact.id,data={"date":"","weather":"","light":"馆方公开影像，拍摄条件未提供","equipment":"未提供","surveyor":"","report_url":first["source_url"],"humidity":None,"water_leak":None})
    db.add(survey);db.flush()
    record=Record(id=record_id,artifact_id=artifact.id,survey_id=survey.id,
        chief_complaint="公开馆藏参考影像导入；尚未开展本项目现场调查或病害诊断。",
        history=f"{first.get('museum','')} 馆藏号 {first.get('accession_number','')}；原始对象链接：{first['source_url']}",
        diagnosis={"hypothesis":"","evidence":[first["source_url"]],"uncertainty":"仅有馆方照片与描述，缺少现场调查、病害真值、尺度、材料检测及修复过程。"})
    db.add(record);db.flush()
    for source in rows:
        original=(MANIFEST.parent/source["path"]).read_bytes()
        image_id=uid("IMG-")
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(original))).convert("RGB")
        output=io.BytesIO();im.save(output,format="PNG")
        key=f"images/{record.id}/{image_id}.png"
        put(key,output.getvalue(),"image/png");put(f"raw/{record.id}/{image_id}.original",original,"image/jpeg")
        declaration=ImageProvenance.model_validate({k:(v if v is not None else "") for k,v in source["provenance"].items()})
        provenance=declare_provenance(declaration,user,source["sha256"])
        provenance.update(reference_image_id=source["id"],catalog_version="ahr-public-mural-reference-v1",metadata_sha256=source["metadata_sha256"],
                          view_type=source.get("view_type","unknown"),view_type_label=source.get("view_type_label","视图类型待核"))
        db.add(ImageAsset(id=image_id,artifact_id=artifact.id,record_id=record.id,filename=f"{source['id']}.jpg",
            storage_key=key,sha256=source["sha256"],image_type="original",width=im.width,height=im.height,provenance=provenance))
    db.flush();audit(db,user,"import_public_reference","record",record.id,record.id,after={"artifact_id":artifact_id,"images":len(rows),"source_url":first["source_url"],"record_kind":"public_reference","diseases_created":0})
    db.commit()
    return record_detail(db,record)
