"""Case selection, conservation records and archive completeness from guide §5/9/15."""
import hashlib
import io
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from pydantic import Field, model_validator
from .schemas import StrictModel
from .db import *
from .security import current_user,require_role
from .service import authorized_record,assert_version,changed,audit,record_detail
from .casebook import get_case,list_cases,case_dict
from .archive import archive_sections,entry_dict
from .storage import put,get_path

router=APIRouter(prefix="/api/v1")


class CaseIn(StrictModel):
    title:str=Field(min_length=1,max_length=300)
    text:str=Field(min_length=1,max_length=15000)
    region:str="甘肃"
    material:str=""
    diseases:list[str]=Field(default_factory=list,max_length=6)
    plan_summary:str=Field(default="",max_length=15000)
    outcome:str=Field(default="",max_length=10000)
    expert_note:str=Field(default="",max_length=10000)
    source_url:str=Field(default="",max_length=2000)
    publisher:str=""
    license_note:str=Field(default="",max_length=4000)
    record_id:str|None=None
    completeness:Literal["abstract","partial","complete"]="partial"
    expected_version:int|None=None

    @model_validator(mode="after")
    def completeness_fields(self):
        from .catalog import DISEASE_NAMES
        if set(self.diseases)-DISEASE_NAMES:raise ValueError("仅使用约定六类病害名称")
        if self.completeness=="complete" and not all(x.strip() for x in [self.text,self.plan_summary,self.outcome,self.source_url,self.license_note]):
            raise ValueError("完整病例须录入诊断依据、处理过程、结果、出处与使用授权说明")
        return self


@router.get("/cases")
def cases(q:str="",disease:str="",region:str="",material:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=list_cases(db,user.org,q,disease,region,material)
    return {"items":rows,"count":len(rows)}


@router.get("/cases/{case_id}")
def case(case_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return get_case(db,case_id,user.org)


@router.post("/cases")
def create_case(body:CaseIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    if body.record_id:authorized_record(db,body.record_id,user)
    data=body.model_dump(exclude={"record_id","expected_version"})
    data.update(kind="case",verified=False,recorded_by=user.id,completeness_notice="字段完整性由系统检查，案例真实性与专业适用性仍需复核")
    row=CaseReference(id=uid("CASE-"),org=user.org,record_id=body.record_id,source=body.source_url,data=data)
    db.add(row);db.flush();audit(db,user,"create_case","case",row.id,body.record_id,after=data);db.commit()
    return case_dict(row,user.org)


@router.put("/cases/{case_id}")
def edit_case(case_id:str,body:CaseIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    row=db.scalar(select(CaseReference).where(CaseReference.id==case_id).with_for_update())
    if not row or row.org!=user.org:raise HTTPException(403,"公开资料只读，或无该病例修改权限")
    if body.expected_version!=row.version:raise HTTPException(409,"病例版本已变化，请刷新")
    if body.record_id:authorized_record(db,body.record_id,user)
    before=case_dict(row,user.org)
    row.data={**body.model_dump(exclude={"record_id","expected_version"}),"kind":"case","verified":False,
              "recorded_by":user.id,"images":row.data.get("images",[])}
    row.source=body.source_url;row.record_id=body.record_id;row.version+=1;row.updated_at=now()
    audit(db,user,"update_case","case",row.id,row.record_id,before,case_dict(row,user.org));db.commit()
    return case_dict(row,user.org)


class CaseReview(StrictModel):
    expected_version:int
    decision:Literal["verified","rejected"]
    comment:str=Field(min_length=1,max_length=4000)


@router.post("/cases/{case_id}/review")
def review_case(case_id:str,body:CaseReview,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"expert","admin")
    row=db.scalar(select(CaseReference).where(CaseReference.id==case_id).with_for_update())
    if not row or row.org!=user.org:raise HTTPException(404,"病例不存在或无审核权限")
    if row.version!=body.expected_version:raise HTTPException(409,"病例版本已变化，请刷新")
    if row.data.get("recorded_by")==user.id:raise HTTPException(403,"病例录入人与复核人须为不同账号")
    if body.decision=="verified" and (row.data.get("completeness")!="complete" or not all(str(row.data.get(k,"")).strip() for k in ("text","plan_summary","outcome","source_url","license_note"))):
        raise HTTPException(422,"完整病例须具备调查依据、处理过程、结果、出处与授权记录")
    before=case_dict(row,user.org)
    row.data={**row.data,"verified":body.decision=="verified","review":{"decision":body.decision,"comment":body.comment,
              "reviewer_id":user.id,"reviewer_name":user.name,"reviewed_at":now(),"source_version":row.version,
              "scope":"资料完整性与授权依据复核；不代表疗效经过独立实验证明"}}
    row.version+=1;row.updated_at=now()
    audit(db,user,"review_case","case",row.id,row.record_id,before,case_dict(row,user.org));db.commit()
    return case_dict(row,user.org)


@router.post("/cases/{case_id}/images")
async def case_image(case_id:str,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    row=db.scalar(select(CaseReference).where(CaseReference.id==case_id).with_for_update())
    if not row or row.org!=user.org:raise HTTPException(403,"仅可向本机构病例添加已获授权的影像")
    if not row.data.get("license_note","").strip():raise HTTPException(422,"请先填写图像使用授权范围")
    data=await file.read(20*1024*1024+1)
    if len(data)>20*1024*1024:raise HTTPException(413,"文件超过20MB")
    from PIL import Image,ImageOps
    try:
        im=Image.open(io.BytesIO(data));im.verify()
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        if im.width*im.height>30_000_000:raise ValueError()
    except Exception:raise HTTPException(422,"无效影像或尺寸过大")
    image_id=uid("CI-");buf=io.BytesIO();im.save(buf,"PNG")
    key=f"cases/{row.id}/{image_id}.png";put(key,buf.getvalue(),"image/png")
    image={"id":image_id,"storage_key":key,"filename":Path(file.filename or "image").name,"sha256":hashlib.sha256(data).hexdigest(),"url":f"/api/v1/cases/{row.id}/images/{image_id}"}
    row.data={**row.data,"images":[*row.data.get("images",[]),image],"verified":False,"recorded_by":user.id};row.version+=1;row.updated_at=now()
    audit(db,user,"case_image","case",row.id,row.record_id,after={"image_id":image_id});db.commit()
    return case_dict(row,user.org)


@router.get("/cases/{case_id}/images/{image_id}")
def read_case_image(case_id:str,image_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=get_case(db,case_id,user.org)
    image=next((i for i in row.get("images",[]) if i["id"]==image_id),None)
    if not image:raise HTTPException(404,"病例影像不存在")
    return FileResponse(get_path(image["storage_key"]),media_type="image/png")


class SelectEvidence(StrictModel):
    expected_version:int
    ids:list[str]=Field(max_length=20)


@router.put("/records/{record_id}/evidence")
def select_evidence(record_id:str,body:SelectEvidence,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user,True);assert_version(r,body.expected_version)
    for identifier in body.ids:get_case(db,identifier,user.org)
    before=r.evidence_ids;r.evidence_ids=list(dict.fromkeys(body.ids));changed(db,r)
    audit(db,user,"select_evidence","record",r.id,r.id,before,r.evidence_ids);db.commit()
    return record_detail(db,r)


class ArchiveIn(StrictModel):
    expected_version:int
    section:str
    title:str=Field(min_length=1,max_length=300)
    text:str=Field(default="",max_length=30000)
    date:str=""


@router.post("/records/{record_id}/archive-entries")
def create_archive_entry(record_id:str,body:ArchiveIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user,True);assert_version(r,body.expected_version)
    if body.section not in {s["key"] for s in archive_sections()}:raise HTTPException(422,"不在10类档案构成内")
    row=ArchiveEntry(record_id=r.id,section=body.section,title=body.title,text=body.text,date=body.date,author=user.name)
    db.add(row);changed(db,r);db.flush();audit(db,user,"archive_entry","archive",row.id,r.id,after=entry_dict(row));db.commit()
    return record_detail(db,r)


@router.post("/archive-entries/{entry_id}/file")
async def attach_archive(entry_id:str,file:UploadFile=File(...),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    row=db.get(ArchiveEntry,entry_id)
    if not row:raise HTTPException(404,"档案条目不存在")
    r=authorized_record(db,row.record_id,user,True)
    if row.storage_key:raise HTTPException(409,"已有附件不可覆盖；请新增条目保存新版本")
    data=await file.read(20*1024*1024+1)
    if not data or len(data)>20*1024*1024:raise HTTPException(413,"附件为空或超过20MB")
    name=Path(file.filename or "attachment.bin").name
    if Path(name).suffix.lower() not in {".pdf",".docx",".xlsx",".csv",".txt",".json",".png",".jpg",".jpeg",".tif",".tiff"}:raise HTTPException(422,"请选择文档、表格或影像附件")
    key=f"archive/{r.id}/{row.id}/{uid()}{Path(name).suffix}"
    put(key,data);row.storage_key=key;row.filename=name;row.sha256=hashlib.sha256(data).hexdigest();changed(db,r)
    audit(db,user,"attach_archive","archive",row.id,r.id,after={"filename":name,"sha256":row.sha256});db.commit()
    return record_detail(db,r)


@router.get("/archive-entries/{entry_id}/file")
def get_archive_file(entry_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(ArchiveEntry,entry_id)
    if not row:raise HTTPException(404,"档案条目不存在")
    r=authorized_record(db,row.record_id,user)
    require_export(db,r,user)
    if not row.storage_key:raise HTTPException(404,"尚无附件")
    audit(db,user,"download_archive","archive",row.id,r.id);db.commit()
    return FileResponse(get_path(row.storage_key),filename=row.filename,media_type="application/octet-stream")


@router.get("/records/{record_id}/jobs")
def jobs(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    authorized_record(db,record_id,user)
    return [asdict(j) for j in db.scalars(select(Job).where(Job.record_id==record_id).order_by(Job.created_at.desc()).limit(50))]


def require_export(db,record,user):
    artifact=db.get(Artifact,record.artifact_id)
    if artifact.data.get("sensitivity")!="sensitive":return
    if user.role=="admin":return
    grant=db.scalar(select(ExportRequest).where(ExportRequest.record_id==record.id,ExportRequest.record_version==record.version,ExportRequest.requester==user.id,ExportRequest.status=="approved"))
    if not grant:raise HTTPException(403,"敏感资料导出需要本机构管理员批准当前病历版本，请先提交导出申请")


class ExportIn(StrictModel):
    purpose:str=Field(min_length=1,max_length=3000)


@router.post("/records/{record_id}/export-requests")
def request_export(record_id:str,body:ExportIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    r=authorized_record(db,record_id,user)
    row=ExportRequest(record_id=r.id,record_version=r.version,requester=user.id,purpose=body.purpose)
    db.add(row);db.flush();audit(db,user,"request_export","export",row.id,r.id,after=asdict(row));db.commit()
    return asdict(row)


@router.get("/records/{record_id}/export-requests")
def export_requests(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    authorized_record(db,record_id,user)
    rows=db.scalars(select(ExportRequest).where(ExportRequest.record_id==record_id).order_by(ExportRequest.created_at.desc()))
    return [asdict(r) for r in rows if user.role=="admin" or r.requester==user.id]


class ExportReview(StrictModel):
    decision:Literal["approved","rejected"]
    comment:str=Field(min_length=1,max_length=3000)


@router.post("/export-requests/{request_id}/review")
def review_export(request_id:str,body:ExportReview,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"admin")
    row=db.get(ExportRequest,request_id)
    if not row:raise HTTPException(404,"申请不存在")
    r=authorized_record(db,row.record_id,user,True)
    if row.status!="pending" or r.version!=row.record_version:raise HTTPException(409,"申请已处理或病历已更新，请重新申请")
    row.status=body.decision;row.comment=body.comment;row.reviewer=user.id
    audit(db,user,"review_export","export",row.id,r.id,after=asdict(row));db.commit()
    return asdict(row)
