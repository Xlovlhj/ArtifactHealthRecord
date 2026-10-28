import base64
import hashlib
import io
import json
import math
import secrets
import time
import zipfile
from collections import Counter, defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from PIL import Image, ImageOps, UnidentifiedImageError
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, Response, UploadFile, File, Form, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel as PydanticBaseModel, Field, ConfigDict, ValidationError
from sqlalchemy import select, func, delete, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from .config import settings, ROOT
from .db import *
from .security import current_user, require_role, public_user, verify_password, token_hash
from .service import authorized_record, record_detail, snapshot, image_dict, plan_dict, audit, changed, assert_version, content_hash
from .catalog import dictionary, DISEASES, DISEASE_NAMES, RULES_VERSION
from .geometry import validate_polygon, validate_centerline, calibration
from .knowledge import search, load_sources, similar
from .generation import generate_plan, validate_sections, extract_record
from .rules import check_plan
from .storage import put, get_path
from .schemas import ClinicalData, ImageProvenance

Image.MAX_IMAGE_PIXELS = 30_000_000
MAX_UPLOAD = 20 * 1024 * 1024
LOGIN_ATTEMPTS = defaultdict(list)


class BaseModel(PydanticBaseModel):
    model_config=ConfigDict(allow_inf_nan=False)


@asynccontextmanager
async def lifespan(app):
    from .migrations import migrate
    migrate()
    from .seed import initialize
    initialize()
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status.in_(["pending","running"]))):
            job.status="failed"
            job.error="服务重启中断了任务，请重新提交"
        db.commit()
    yield


app=FastAPI(title="文物病历 · 甘肃壁画保护工作台",version="1.0.0",lifespan=lifespan)
api=APIRouter(prefix="/api/v1")


@app.middleware("http")
async def request_guards(request,call_next):
    origin=request.headers.get("origin")
    if request.method not in ("GET","HEAD","OPTIONS") and origin and origin not in settings().allowed_origins.split(","):
        return JSONResponse({"detail":"请求来源不在允许列表"},status_code=403)
    length=request.headers.get("content-length")
    if length and int(length)>MAX_UPLOAD+1024*1024:
        return JSONResponse({"detail":"上传体积超过20MB"},status_code=413)
    response=await call_next(request)
    response.headers["X-Content-Type-Options"]="nosniff"
    response.headers["X-Frame-Options"]="DENY"
    response.headers["Referrer-Policy"]="same-origin"
    if request.url.path.startswith("/api/"): response.headers["Cache-Control"]="no-store"
    return response


@app.exception_handler(StaleDataError)
async def stale_handler(request,exc):
    return JSONResponse({"detail":"数据发生并发修改，请刷新后重试"},status_code=409)


@app.exception_handler(IntegrityError)
async def integrity_handler(request,exc):
    return JSONResponse({"detail":"数据版本或关联冲突，请刷新后重试"},status_code=409)


@app.exception_handler(RequestValidationError)
@app.exception_handler(ValidationError)
async def validation_handler(request,exc):
    return JSONResponse({"detail":"输入字段格式不正确，请检查必填项和字段类型"},status_code=422)


class LoginIn(BaseModel):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=256)


@api.post("/auth/login")
def login(body:LoginIn,request:Request,response:Response,db:Session=Depends(get_db)):
    key=(request.client.host if request.client else "unknown",body.username)
    recent=[t for t in LOGIN_ATTEMPTS[key] if t>time.time()-60]
    if len(recent)>=12: raise HTTPException(429,"登录尝试过多，请稍后重试")
    recent.append(time.time()); LOGIN_ATTEMPTS[key]=recent
    user=db.scalar(select(User).where(User.username==body.username,User.active==True))
    if not user or not verify_password(body.password,user.password_hash): raise HTTPException(401,"用户名或密码错误")
    token=secrets.token_urlsafe(40)
    db.add(AuthSession(id=token_hash(token),user_id=user.id,expires_at=time.time()+8*3600))
    audit(db,user,"login","user",user.id)
    db.commit()
    response.set_cookie("ahr_session",token,httponly=True,secure=settings().env=="production",samesite="strict",max_age=8*3600)
    return {"user":public_user(user),"access_token":token}


@api.get("/auth/me")
def me(user:User=Depends(current_user)): return public_user(user)


@api.post("/auth/logout")
def logout(request:Request,response:Response,user:User=Depends(current_user),db:Session=Depends(get_db)):
    token=request.cookies.get("ahr_session","")
    auth=request.headers.get("authorization","")
    if auth.lower().startswith("bearer "): token=auth[7:]
    row=db.get(AuthSession,token_hash(token))
    if row: db.delete(row)
    db.commit();response.delete_cookie("ahr_session")
    return {"ok":True}


def capabilities(db=None,user=None):
    cfg=settings()
    checkpoint=Path(cfg.segmentation_checkpoint) if cfg.segmentation_checkpoint else None
    from .catalog import symbol_package
    package=symbol_package()
    cases=None
    if db is not None and user is not None:
        rows=db.scalars(select(CaseReference).where(CaseReference.org==user.org))
        cases=sum(r.data.get("completeness")=="complete" and r.data.get("verified") is True and bool(r.data.get("license_note","")) for r in rows)
    return {"llm":"configured" if cfg.llm_base_url and cfg.llm_api_key and cfg.llm_model else "template_fallback", "segmentation":"checkpoint_configured" if checkpoint and checkpoint.is_file() else "manual_required", "storage":cfg.storage,"redis":"configured" if cfg.redis_url else "not_configured","demo_mode":cfg.demo_mode,"real_segmentation_metrics":None,"licensed_complete_cases":cases,"standard_symbols_verified":package.get("verified",False),"standard_rendering_certified":package.get("rendering_certified",False),"symbol_package":package.get("package_id")}


@api.get("/health")
def health(db:Session=Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status":"ok","version":"1.0.0","database":"postgresql" if settings().db_url.startswith("postgres") else "sqlite",**capabilities()}


@api.get("/dictionary")
def get_dictionary(user:User=Depends(current_user)): return dictionary()


def visible_records(db,user):
    return list(db.scalars(select(Record).join(Artifact,Record.artifact_id==Artifact.id).where(Artifact.org==user.org).order_by(Record.updated_at.desc())))


def summary(db,record):
    a=db.get(Artifact,record.artifact_id)
    images=list(db.scalars(select(ImageAsset).where(ImageAsset.record_id==record.id)))
    return {"id":record.id,"name":a.data.get("name"),"type":a.data.get("type"),"region":a.data.get("region"),"era":a.data.get("era"),"status":record.status,"version":record.version,"created_at":record.created_at,"updated_at":record.updated_at,"disease_count":db.scalar(select(func.count()).select_from(Disease).where(Disease.record_id==record.id)),"image_count":len(images),"thumbnail_url":f"/api/v1/images/{images[0].id}/file" if images else None,"is_demo":a.is_demo,"record_kind":a.data.get("record_kind","teaching" if a.is_demo else "survey")}


@api.get("/records")
def list_records(q:str="",status:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=[summary(db,r) for r in visible_records(db,user)]
    return [r for r in rows if (not q or q.lower() in json.dumps(r,ensure_ascii=False).lower()) and (not status or r["status"]==status)]


@api.get("/dashboard")
def dashboard(user:User=Depends(current_user),db:Session=Depends(get_db)):
    records=visible_records(db,user);ids=[r.id for r in records]
    diseases=list(db.scalars(select(Disease).where(Disease.record_id.in_(ids))))
    plans=list(db.scalars(select(Plan).where(Plan.record_id.in_(ids))))
    return {"records":len(records),"images":db.scalar(select(func.count()).select_from(ImageAsset).where(ImageAsset.record_id.in_(ids))),"diseases":len(diseases),"plans":len(plans),"pending_reviews":sum(p.status=="review" for p in plans),"approved_plans":sum(p.status=="approved" for p in plans),"by_disease":[{"name":k,"count":v} for k,v in Counter(d.type for d in diseases).items()],"by_status":[{"name":k,"count":v} for k,v in Counter(r.status for r in records).items()],"by_risk":[{"name":k,"count":v} for k,v in Counter((r.clinical_data or {}).get("risk",{}).get("level","unassessed") for r in records).items()],"recent":[summary(db,r) for r in records[:6]],"capabilities":capabilities(db,user)}


class ArtifactIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    name:str=Field(min_length=1,max_length=200)
    type:Literal["石窟寺壁画","寺观壁画","墓葬壁画","馆藏壁画"]="石窟寺壁画"
    era:str=""
    region:str="甘肃"
    location:str=""
    area_m2:float|None=Field(default=None,gt=0)
    support_type:str=""
    ground_type:str=""
    pigment_type:str=""
    sensitivity:Literal["internal","sensitive"]="internal"


class SurveyIn(BaseModel):
    date:str=""
    weather:str=""
    light:str=""
    equipment:str=""
    humidity:float|None=Field(default=None,ge=0,le=100)
    water_leak:bool|None=None
    surveyor:str=""
    report_url:str=""


class CreateRecord(BaseModel):
    artifact:ArtifactIn
    survey:SurveyIn=Field(default_factory=SurveyIn)
    chief_complaint:str=Field(default="",max_length=10000)
    history:str=Field(default="",max_length=10000)
    is_demo:bool=False


@api.post("/records")
def create_record(body:CreateRecord,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","admin")
    a=Artifact(data={**body.artifact.model_dump(),"record_kind":"teaching" if body.is_demo else "survey"},org=user.org,is_demo=body.is_demo)
    db.add(a);db.flush()
    s=Survey(artifact_id=a.id,data=body.survey.model_dump());db.add(s);db.flush()
    r=Record(artifact_id=a.id,survey_id=s.id,chief_complaint=body.chief_complaint,history=body.history,diagnosis={"hypothesis":"","evidence":[],"uncertainty":"待完成调查与专家复核"})
    db.add(r);db.flush();audit(db,user,"create","record",r.id,r.id,after=snapshot(db,r));db.commit()
    return record_detail(db,r)


@api.get("/records/{record_id}")
def get_record(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    return record_detail(db,authorized_record(db,record_id,user))


class DiagnosisIn(BaseModel):
    model_config=ConfigDict(extra="forbid")
    hypothesis:str=Field(default="",max_length=15000)
    evidence:list[str]=Field(default_factory=list,max_length=100)
    uncertainty:str=Field(default="",max_length=15000)


class UpdateRecord(BaseModel):
    model_config=ConfigDict(extra="forbid")
    expected_version:int
    artifact:dict|None=None
    survey:dict|None=None
    chief_complaint:str|None=Field(default=None,max_length=10000)
    history:str|None=Field(default=None,max_length=10000)
    diagnosis:DiagnosisIn|None=None
    clinical_data:ClinicalData|None=None


@api.put("/records/{record_id}")
def update_record(record_id:str,body:UpdateRecord,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user,True);assert_version(r,body.expected_version);before=snapshot(db,r)
    if body.artifact is not None:
        a=db.get(Artifact,r.artifact_id)
        server_fields={k:a.data[k] for k in ("record_kind","reference_artifact_id") if k in a.data}
        clean={k:v for k,v in body.artifact.items() if k not in {"id","record_kind","reference_artifact_id"}}
        existing={k:v for k,v in a.data.items() if k not in {"record_kind","reference_artifact_id"}}
        a.data={**ArtifactIn.model_validate({**existing,**clean}).model_dump(),**server_fields}
    if body.survey is not None:
        s=db.get(Survey,r.survey_id)
        s.data=SurveyIn.model_validate({**s.data,**body.survey}).model_dump()
    for field in ("chief_complaint","history","diagnosis"):
        value=getattr(body,field)
        if value is not None: setattr(r,field,value.model_dump() if hasattr(value,"model_dump") else value)
    if body.clinical_data is not None:
        clinical=body.clinical_data.model_dump()
        if clinical["risk"]["level"]!="unassessed" and not clinical["risk"]["reason"].strip():
            raise HTTPException(422,"风险分级必须填写评估依据")
        old_risk=(r.clinical_data or {}).get("risk",{})
        if any(old_risk.get(k)!=clinical["risk"].get(k) for k in ("level","reason")):
            clinical["risk"].update(assessed_by=user.name,assessed_at=now())
        else:
            clinical["risk"].update(assessed_by=old_risk.get("assessed_by",""),assessed_at=old_risk.get("assessed_at",""))
        r.clinical_data=clinical
    changed(db,r);db.flush();audit(db,user,"update","record",r.id,r.id,before,snapshot(db,r));db.commit()
    return record_detail(db,r)


def authorized_image(db,image_id,user,lock=False):
    image=db.get(ImageAsset,image_id)
    if not image:raise HTTPException(404,"影像不存在")
    record=authorized_record(db,image.record_id,user,lock)
    if lock:db.refresh(image)
    return image,record


@api.post("/records/{record_id}/images")
async def upload_image(record_id:str,file:UploadFile=File(...),image_type:str=Form("original"),provenance:str=Form(""),user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","admin")
    r=authorized_record(db,record_id,user,True)
    if image_type not in {"original","followup","document"}:raise HTTPException(422,"无效影像类别")
    try:source=ImageProvenance.model_validate_json(provenance) if provenance else ImageProvenance()
    except (ValueError,ValidationError):raise HTTPException(422,"来源字段格式无效，合成图不得声明为真实评测用途")
    data=await file.read(MAX_UPLOAD+1)
    if len(data)>MAX_UPLOAD:raise HTTPException(413,"单张影像最大20MB")
    try:
        im=Image.open(io.BytesIO(data));im.verify()
        im=ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        if im.width*im.height>30_000_000:raise ValueError()
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
        raise HTTPException(422,"请上传有效的PNG/JPEG/WebP/TIFF影像，像素不超过3000万")
    original_hash=hashlib.sha256(data).hexdigest()
    duplicate=db.scalar(select(ImageAsset).where(ImageAsset.record_id==r.id,ImageAsset.sha256==original_hash))
    if duplicate:return {**image_dict(duplicate),"duplicate":True,"duplicate_notice":"相同原始文件已存在，未新增也未覆盖来源；请在已有影像补录来源。"}
    image_id=uid("IMG-")
    # Preserve exact input as an original, render an orientation-normalized PNG separately.
    put(f"raw/{r.id}/{image_id}.original",data)
    buf=io.BytesIO();im.save(buf,format="PNG")
    key=f"images/{r.id}/{image_id}.png";put(key,buf.getvalue(),"image/png")
    from .governance import declare_provenance
    row=ImageAsset(id=image_id,artifact_id=r.artifact_id,record_id=r.id,filename=Path(file.filename or "image").name,storage_key=key,sha256=original_hash,image_type=image_type,width=im.width,height=im.height,provenance=declare_provenance(source,user,original_hash))
    db.add(row);changed(db,r);db.flush();audit(db,user,"upload","image",row.id,r.id,after=image_dict(row));db.commit()
    return image_dict(row)


@api.get("/images/{image_id}/file")
def image_file(image_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    image,_=authorized_image(db,image_id,user)
    return FileResponse(get_path(image.storage_key),media_type="image/png")


@api.get("/images/{image_id}/original")
def original_file(image_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    image,r=authorized_image(db,image_id,user)
    require_export(db,r,user)
    key=f"raw/{r.id}/{image.id}.original"
    try:path=get_path(key)
    except FileNotFoundError:raise HTTPException(409,"原始上传文件缺失；规范化显示图不能替代原始字节")
    audit(db,user,"download_original","image",image.id,r.id);db.commit()
    return FileResponse(path,filename=image.filename,media_type="application/octet-stream")


class CalibrationIn(BaseModel):
    points:list[list[float]]
    length_cm:float


def recalibrate(db,image,r,user,value):
    before=image.calibration;image.calibration=value
    for d in db.scalars(select(Disease).where(Disease.image_id==image.id)):
        d.area_cm2=d.area_px*value["cm_per_pixel"]**2 if value else None
    changed(db,r);audit(db,user,"calibrate","image",image.id,r.id,before,value);db.commit()
    return image_dict(image)


@api.put("/images/{image_id}/calibration")
def set_calibration(image_id:str,body:CalibrationIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    image,r=authorized_image(db,image_id,user,True)
    return recalibrate(db,image,r,user,calibration(body.points,body.length_cm,image.width,image.height))


@api.post("/images/{image_id}/calibration/clear")
def clear_calibration(image_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    image,r=authorized_image(db,image_id,user,True)
    return recalibrate(db,image,r,user,None)


class DiseaseIn(BaseModel):
    type:str
    polygon:list[list[float]]
    centerline:list[list[float]]|None=None
    severity:Literal["轻度","中度","重度","待确认"]="待确认"
    confidence:float|None=Field(default=None,ge=0,le=1)
    evidence:str=Field(default="",max_length=5000)
    field_evidence:str=Field(default="",max_length=5000)
    confirmed:bool=False
    source:Literal["manual","model"]="manual"
    model_job_id:str|None=None
    proposal_index:int|None=None


class DiseasesIn(BaseModel):
    expected_version:int
    image_id:str
    items:list[DiseaseIn]=Field(max_length=500)


@api.put("/records/{record_id}/diseases")
def save_diseases(record_id:str,body:DiseasesIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user,True);assert_version(r,body.expected_version)
    image,_=authorized_image(db,body.image_id,user)
    if image.record_id!=r.id:raise HTTPException(422,"影像不属于当前病历")
    validated=[]
    for item in body.items:
        if item.type not in DISEASE_NAMES:raise HTTPException(422,"仅支持约定六类病害")
        if item.type=="空鼓" and item.confirmed and not item.field_evidence.strip():raise HTTPException(422,"确认空鼓需要现场检测证据；普通照片不足以确认")
        poly,area=validate_polygon(item.polygon,image.width,image.height)
        if item.centerline and item.type!="裂隙":raise HTTPException(422,"仅裂隙病害使用中心线")
        centerline=validate_centerline(item.centerline,image.width,image.height)
        row=item.model_dump();row.update(polygon=poly,area_px=area,area_ratio=area/(image.width*image.height),area_cm2=area*image.calibration["cm_per_pixel"]**2 if image.calibration else None,
                                       standard_code=next(d["standard_code"] for d in DISEASES if d["type"]==item.type),centerline=centerline)
        if item.source=="manual":
            row["confidence"]=None;row["model_job_id"]=None;row["proposal_index"]=None
        else:
            job=db.get(Job,item.model_job_id) if item.model_job_id else None
            if not job or job.record_id!=r.id or job.kind!="segmentation" or job.status!="completed" or job.result.get("image_id")!=image.id:
                raise HTTPException(422,"模型标注必须绑定本图已完成的真实分割任务")
            proposals=job.result.get("predictions",[])
            idx=item.proposal_index
            if idx is None or not 0<=idx<len(proposals) or proposals[idx]["type"]!=item.type or proposals[idx]["polygon"]!=poly:
                raise HTTPException(422,"候选与模型任务不一致；修改过的区域请保存为人工标注")
            row["confidence"]=proposals[idx].get("confidence")
            row["model_version"]=job.result.get("model_version")
        validated.append(row)
    before=[asdict(d) for d in db.scalars(select(Disease).where(Disease.image_id==image.id))]
    db.execute(delete(Disease).where(Disease.image_id==image.id))
    for row in validated:db.add(Disease(record_id=r.id,image_id=image.id,**row))
    changed(db,r);db.flush();audit(db,user,"annotate","image",image.id,r.id,before,validated);db.commit()
    return record_detail(db,r)


def enqueue(db,user,record,kind,background,worker,*args):
    active=db.scalar(select(func.count()).select_from(Job).where(Job.user_id==user.id,Job.status.in_(["pending","running"])))
    if active>=3:raise HTTPException(429,"已有3个任务在执行，请稍候")
    job=Job(user_id=user.id,record_id=record.id,kind=kind);db.add(job);db.flush()
    audit(db,user,"enqueue",kind,job.id,record.id);db.commit()
    background.add_task(run_job,job.id,worker,args)
    return asdict(job)


def run_job(job_id,worker,args):
    with SessionLocal() as db:
        job=db.get(Job,job_id);job.status="running";job.updated_at=now();db.commit()
        try:
            result=worker(db,job,*args)
            job.result=result;job.status="completed";job.updated_at=now()
            audit(db,job.user_id,"complete",job.kind,job.id,job.record_id,after={"status":"completed","model_version":result.get("model_version"),"method":result.get("method")})
            db.commit()
        except Exception as exc:
            db.rollback();job=db.get(Job,job_id);job.status="failed";job.error=f"任务失败（{type(exc).__name__}），请检查影像、模型配置或服务日志";job.updated_at=now();db.commit()
            import logging
            logging.getLogger("ahr.jobs").warning("Job %s failed: %s",job.id,type(exc).__name__)


def analyze_worker(db,job,image_id):
    from ai.service import analyze_image
    image=db.get(ImageAsset,image_id)
    result=analyze_image(get_path(image.storage_key),settings().segmentation_checkpoint or None)
    result.update(image_id=image.id,image_sha256=image.sha256)
    image.quality=result.get("quality",{})
    return result


@api.post("/images/{image_id}/analyze")
def analyze(image_id:str,background:BackgroundTasks,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    image,r=authorized_image(db,image_id,user)
    return enqueue(db,user,r,"segmentation",background,analyze_worker,image_id)


@api.get("/jobs/{job_id}")
def get_job(job_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    job=db.get(Job,job_id)
    if not job:raise HTTPException(404,"任务不存在")
    authorized_record(db,job.record_id,user)
    return asdict(job)


@api.get("/knowledge")
def knowledge(q:str="",kind:str="",disease:str="",region:str="",user:User=Depends(current_user)):
    items=search(q,kind,disease,region,100)
    return {"items":items,"count":len(items)}


@api.get("/records/{record_id}/similar-cases")
def cases(record_id:str,disease:str="",region:str="",material:str="",image_id:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    r=authorized_record(db,record_id,user)
    from .casebook import retrieve_cases
    path=None
    if image_id:
        image,_=authorized_image(db,image_id,user)
        if image.record_id!=r.id:raise HTTPException(422,"查询影像不属于本病历")
        path=get_path(image.storage_key)
    return retrieve_cases(db,record_detail(db,r,False),user.org,disease,region,material,path)


class ExtractIn(BaseModel):
    text:str=Field(min_length=1,max_length=30000)
    image_id:str|None=None


@api.post("/records/{record_id}/extract")
def extract(record_id:str,body:ExtractIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user)
    image_data_url=None
    if body.image_id:
        image,_=authorized_image(db,body.image_id,user)
        if image.record_id!=r.id:raise HTTPException(422,"影像不属于当前病历")
        with Image.open(get_path(image.storage_key)) as im:
            im=im.convert("RGB");im.thumbnail((1600,1600))
            buf=io.BytesIO();im.save(buf,"JPEG",quality=85)
        image_data_url="data:image/jpeg;base64,"+base64.b64encode(buf.getvalue()).decode()
    result=extract_record(body.text,record_detail(db,r,False),image_data_url)
    audit(db,user,"extract_draft","record",r.id,r.id,after={"provider":result["provider"],"model_version":result["model_version"]});db.commit()
    return result


class GenerateIn(BaseModel):
    use_llm:bool=True


def next_plan_version(db,record_id):
    return (db.scalar(select(func.max(Plan.version)).where(Plan.record_id==record_id)) or 0)+1


def supersede_previous(db,r):
    for old in db.scalars(select(Plan).where(Plan.record_id==r.id,Plan.status.in_(["review","approved"]))):
        old.status="superseded"
    r.status="draft"


@api.post("/records/{record_id}/plans")
def create_plan(record_id:str,body:GenerateIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    r=authorized_record(db,record_id,user,True)
    result=generate_plan(record_detail(db,r,False),body.use_llm)
    supersede_previous(db,r)
    p=Plan(record_id=r.id,version=next_plan_version(db,r.id),record_version=r.version,record_snapshot=snapshot(db,r),author=user.id,**result)
    db.add(p);db.flush();audit(db,user,"generate","plan",p.id,r.id,after=plan_dict(p));db.commit()
    return plan_dict(p)


def authorized_plan(db,plan_id,user,lock=False):
    p=db.scalar(select(Plan).where(Plan.id==plan_id))
    if not p:raise HTTPException(404,"方案不存在")
    # All mutations acquire Record before Plan to avoid inverted PostgreSQL locks.
    r=authorized_record(db,p.record_id,user,lock)
    if lock:
        p=db.scalar(select(Plan).where(Plan.id==plan_id).with_for_update().execution_options(populate_existing=True))
        if not p:raise HTTPException(404,"方案不存在")
    return p,r


class EditPlanIn(BaseModel):
    sections:dict
    expected_version:int


@api.put("/plans/{plan_id}")
def edit_plan(plan_id:str,body:EditPlanIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    old,r=authorized_plan(db,plan_id,user,True)
    if old.version!=body.expected_version:raise HTTPException(409,"方案版本已变化")
    if old.record_version!=r.version:raise HTTPException(409,"病历内容已变化，请基于当前病历重新生成草案，不能把旧方案静默绑定新版病历")
    if old.version!=next_plan_version(db,r.id)-1:raise HTTPException(409,"已有更新方案，请在最新版上编辑")
    from .casebook import selected_evidence
    allowed={s["id"] for s in load_sources()}|{s["id"] for s in selected_evidence(db,r,user.org)}
    try:sections=validate_sections(body.sections,allowed)
    except ValueError as exc:raise HTTPException(422,str(exc))
    supersede_previous(db,r)
    refs=[*load_sources(),*selected_evidence(db,r,user.org)]
    used={c for s in sections.values() for c in s["citations"]}|{c for s in sections.values() for m in s.get("measures",[]) for c in m.get("citations",[])}
    p=Plan(record_id=r.id,version=next_plan_version(db,r.id),record_version=r.version,record_snapshot=snapshot(db,r),evidence_snapshot=[s for s in refs if s["id"] in used],sections=sections,citations=sorted(used),author=user.id,provider="human_edit",model_version=old.model_version,generation_note=f"基于{old.id}创建的新版本，保留旧版本")
    db.add(p);db.flush();audit(db,user,"new_version","plan",p.id,r.id,plan_dict(old),plan_dict(p));db.commit()
    return plan_dict(p)


def run_checks(db,p,r):
    result=check_plan(plan_dict(p),record_detail(db,r,False))
    if p.record_version!=r.version:
        result["items"].append({"rule_id":"R-VERSION-001","name":"病历版本一致","result":"block","message":"方案对应旧病历，请依据当前病历创建新版本","basis":"项目版本控制","basis_status":"project_policy"});result["overall"]="block"
    p.checks=result["items"]
    db.add(PlanCheck(plan_id=p.id,data=result))
    return result


@api.post("/plans/{plan_id}/check")
def check(plan_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    p,r=authorized_plan(db,plan_id,user,True)
    result=run_checks(db,p,r);audit(db,user,"check","plan",p.id,r.id,after=result);db.commit()
    return result


@api.post("/plans/{plan_id}/submit")
def submit(plan_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","admin")
    p,r=authorized_plan(db,plan_id,user,True)
    if p.status not in ("draft","rejected"):raise HTTPException(409,"仅草案或退回方案可以提交")
    if p.version!=next_plan_version(db,r.id)-1:raise HTTPException(409,"已有更新方案，仅最新版可以提交")
    result=run_checks(db,p,r)
    if result["overall"]=="block":db.commit();raise HTTPException(409,{"message":"存在阻断项，不能提交","checks":result})
    p.status="review";p.content_hash=content_hash(p);r.status="review"
    # Workflow state changes do not change the clinical content version.
    audit(db,user,"submit","plan",p.id,r.id,after=plan_dict(p));db.commit()
    return plan_dict(p)


class ReviewIn(BaseModel):
    decision:Literal["approved","rejected"]
    comment:str=Field(min_length=1,max_length=10000)
    signature:str=Field(min_length=1,max_length=120)


@api.post("/plans/{plan_id}/review")
def review(plan_id:str,body:ReviewIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"expert")
    if body.signature.strip()!=user.name:raise HTTPException(422,"确认姓名必须与当前登录账号姓名一致")
    p,r=authorized_plan(db,plan_id,user,True)
    if p.author==user.id:raise HTTPException(403,"编制者不能审核自己的方案")
    if p.status!="review":raise HTTPException(409,"方案不在待会诊状态")
    if p.version!=next_plan_version(db,r.id)-1:raise HTTPException(409,"已有更新方案，当前方案不能再审核")
    if p.content_hash!=content_hash(p):raise HTTPException(409,"方案内容与提交版本不一致")
    if p.record_version!=r.version:raise HTTPException(409,"病历已变化，请重新提交")
    result=run_checks(db,p,r)
    if body.decision=="approved" and result["overall"]=="block":db.commit();raise HTTPException(409,"仍存在阻断项，不能审核通过")
    p.status=body.decision;p.reviewer=user.id;p.signed_at=now()
    db.add(Consultation(record_id=r.id,plan_id=p.id,user_id=user.id,comment=body.comment,decision=body.decision,signature=body.signature,content_hash=p.content_hash))
    r.status="approved" if body.decision=="approved" else "draft"
    db.flush()
    audit(db,user,"review","plan",p.id,r.id,after={"decision":body.decision,"comment":body.comment,"signature":body.signature,"hash":p.content_hash,"notice":"内部身份审核记录，不等同CA电子签章"});db.commit()
    return plan_dict(p)


class CommentIn(BaseModel):
    comment:str=Field(min_length=1,max_length=10000)
    plan_id:str|None=None
    decision:Literal["comment"]="comment"


@api.post("/records/{record_id}/consultations")
def comment(record_id:str,body:CommentIn,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user)
    if body.plan_id:
        p,_=authorized_plan(db,body.plan_id,user)
        if p.record_id!=r.id:raise HTTPException(422,"方案不属于当前病历")
    c=Consultation(record_id=r.id,plan_id=body.plan_id,user_id=user.id,comment=body.comment)
    db.add(c);db.flush();audit(db,user,"comment","consultation",c.id,r.id,after=asdict(c));db.commit()
    return asdict(c)


@api.get("/consultations")
def consultations(user:User=Depends(current_user),db:Session=Depends(get_db)):
    ids=[r.id for r in visible_records(db,user)]
    result=[]
    for p in db.scalars(select(Plan).where(Plan.record_id.in_(ids)).order_by(Plan.created_at.desc())):
        r=db.get(Record,p.record_id);a=db.get(Artifact,r.artifact_id)
        result.append({**plan_dict(p),"plan_id":p.id,"record_name":a.data["name"]})
    return result


@api.get("/audit")
def audit_list(record_id:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    ids=[r.id for r in visible_records(db,user)]
    stmt=select(AuditLog).where(AuditLog.record_id.in_(ids))
    if record_id:authorized_record(db,record_id,user);stmt=stmt.where(AuditLog.record_id==record_id)
    return [asdict(a) for a in db.scalars(stmt.order_by(AuditLog.created_at.desc()).limit(300))]


@api.get("/system/readiness")
def readiness(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return {"capabilities":capabilities(db,user),"knowledge_count":len(load_sources()),"case_abstract_count":sum(s.get("kind")=="case" for s in load_sources()),"items":[{"name":"病历与人工病害标注","status":"implemented"},{"name":"13节方案/引用/规则/版本审核","status":"implemented"},{"name":"真实六类分割准确率","status":"not_evaluated","detail":"需要授权标注数据和训练权重；合成冒烟数据不计入"},{"name":"GB/T30237-2025六类定义与图示资料","status":"source_verified","detail":"已核对六类条号与图示参数；成图质量、裂隙中心线与专业审查另行验证，未宣称获认证"},{"name":"逐图来源与授权","status":"implemented","detail":"/api/v1/data/readiness 提供当前机构实际数据台账"},{"name":"CodeArts使用/华为云部署证据","status":"requires_user_cloud_environment","detail":"部署配置已提供，未伪造实际云资源或使用记录"}]}


class SimulateIn(BaseModel):
    image_id:str
    types:list[str]=Field(default_factory=list)


def simulate_worker(db,job,image_id,types,polygons,source_record_version,image_sha256):
    import numpy as np
    from PIL import ImageDraw
    from ai.service import simulate
    image=db.get(ImageAsset,image_id)
    mask=Image.new("L",(image.width,image.height));draw=ImageDraw.Draw(mask)
    for points in polygons:draw.polygon([tuple(p) for p in points],fill=255)
    output=settings().runtime/"work"/f"{job.id}.png";output.parent.mkdir(exist_ok=True)
    cfg=settings()
    result=simulate(get_path(image.storage_key),np.array(mask),output,method=cfg.inpaint_method,checkpoint=cfg.inpaint_checkpoint or None)
    key=f"simulation/{job.record_id}/{job.id}.png";put(key,output.read_bytes(),"image/png")
    uncertainty_key=None
    if result.get("uncertainty_path"):
        uncertainty_key=f"simulation/{job.record_id}/{job.id}_uncertainty.png"
        put(uncertainty_key,Path(result["uncertainty_path"]).read_bytes(),"image/png")
    result={k:v for k,v in result.items() if k not in ("output_path","uncertainty_path")}
    row=Simulation(record_id=job.record_id,image_id=image_id,storage_key=key,data={**result,"uncertainty_storage_key":uncertainty_key,"source_record_version":source_record_version,"source_image_sha256":image_sha256,"source_polygons":polygons})
    db.add(row);db.flush()
    return {**result,"id":row.id,"image_id":image_id,"source_record_version":source_record_version,"source_image_sha256":image_sha256,"source_polygons":polygons,"url":f"/api/v1/simulations/{row.id}/file","uncertainty_url":f"/api/v1/simulations/{row.id}/uncertainty" if uncertainty_key else None}


@api.post("/records/{record_id}/simulate")
def simulation(record_id:str,body:SimulateIn,background:BackgroundTasks,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"restorer","expert","admin")
    r=authorized_record(db,record_id,user,True);image,_=authorized_image(db,body.image_id,user)
    if image.record_id!=r.id:raise HTTPException(422,"影像不属于当前病历")
    rows=list(db.scalars(select(Disease).where(Disease.image_id==image.id)))
    rows=[d for d in rows if not body.types or d.type in body.types]
    if not rows:raise HTTPException(422,"请先标注需要沟通预览的区域")
    return enqueue(db,user,r,"simulation",background,simulate_worker,image.id,body.types,[d.polygon for d in rows],r.version,image.sha256)


@api.get("/simulations/{simulation_id}/file")
@api.get("/simulations/{simulation_id}/uncertainty")
def simulation_file(simulation_id:str,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=db.get(Simulation,simulation_id)
    if not row:raise HTTPException(404,"模拟记录不存在")
    authorized_record(db,row.record_id,user)
    key=row.data.get("uncertainty_storage_key") if request.url.path.endswith("uncertainty") else row.storage_key
    if not key:raise HTTPException(404,"未生成不确定区域图")
    return FileResponse(get_path(key),media_type="image/png")


class CompareIn(BaseModel):
    before_image_id:str
    after_image_id:str


def compare_worker(db,job,before_id,after_id):
    from ai.service import compare_images
    a,b=db.get(ImageAsset,before_id),db.get(ImageAsset,after_id)
    result=compare_images(get_path(a.storage_key),get_path(b.storage_key))
    result.update(before_image_id=before_id,after_image_id=after_id)
    result["comparison_url"]=result.get("change_map")
    return result


@api.post("/records/{record_id}/compare")
def compare(record_id:str,body:CompareIn,background:BackgroundTasks,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    r=authorized_record(db,record_id,user)
    a,_=authorized_image(db,body.before_image_id,user);b,_=authorized_image(db,body.after_image_id,user)
    if a.record_id!=r.id or b.record_id!=r.id:raise HTTPException(422,"比较影像必须属于同一病历")
    return enqueue(db,user,r,"comparison",background,compare_worker,a.id,b.id)


def map_inputs(db,r,image_id):
    image=db.get(ImageAsset,image_id) if image_id else db.scalar(select(ImageAsset).where(ImageAsset.record_id==r.id).order_by(ImageAsset.created_at))
    if not image or image.record_id!=r.id:raise HTTPException(404,"病历内无对应影像")
    return record_detail(db,r,False),image_dict(image),get_path(image.storage_key).read_bytes()


@api.get("/records/{record_id}/disease-map.svg")
def map_svg(record_id:str,image_id:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .reports import disease_svg
    r=authorized_record(db,record_id,user)
    require_export(db,r,user)
    output=disease_svg(*map_inputs(db,r,image_id))
    audit(db,user,"export_svg","record",r.id,r.id);db.commit()
    return Response(output,media_type="image/svg+xml",headers={"Content-Disposition":f'attachment; filename="{r.id}-map.svg"'})


@api.get("/records/{record_id}/disease-map.pdf")
def map_report(record_id:str,image_id:str="",user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .reports import map_pdf
    r=authorized_record(db,record_id,user)
    require_export(db,r,user)
    output=map_pdf(*map_inputs(db,r,image_id))
    audit(db,user,"export_map_pdf","record",r.id,r.id);db.commit()
    return Response(output,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{r.id}-map.pdf"'})


@api.get("/plans/{plan_id}/export.pdf")
def plan_export(plan_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .reports import plan_pdf
    p,r=authorized_plan(db,plan_id,user)
    require_export(db,r,user)
    output=plan_pdf(record_detail(db,r,False),plan_dict(p))
    audit(db,user,"export_plan","plan",p.id,r.id);db.commit()
    return Response(output,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{p.id}.pdf"'})


def archive_data(db,r):
    data=record_detail(db,r)
    data["simulation_register"]=[{"id":s["id"],"created_at":s["created_at"],"notice":"模拟图单独保管，不属于原始影像档案"} for s in data.pop("simulations")]
    data["archive_metadata"]={"schema_version":"ahr-1.0","exported_at":now(),"record_version":r.version,"rules_version":RULES_VERSION,"source_notice":"原始影像与人工记录分别保留；模拟生成图不纳入原始影像档案"}
    data["evidence_sources"]=[*load_sources(),*data.get("evidence_sources",[])]
    return data


@api.get("/records/{record_id}/archive.json")
def export_json(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    r=authorized_record(db,record_id,user)
    require_export(db,r,user)
    audit(db,user,"export_json","record",r.id,r.id);db.flush();data=archive_data(db,r);db.commit()
    return Response(json.dumps(data,ensure_ascii=False,indent=2),media_type="application/json",headers={"Content-Disposition":f'attachment; filename="{r.id}.json"'})


@api.get("/records/{record_id}/archive.pdf")
def export_pdf(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .reports import record_pdf
    r=authorized_record(db,record_id,user)
    require_export(db,r,user)
    audit(db,user,"export_pdf","record",r.id,r.id);db.flush();output=record_pdf(archive_data(db,r));db.commit()
    return Response(output,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="{r.id}.pdf"'})


@api.get("/records/{record_id}/archive.zip")
def export_zip(record_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .reports import record_pdf,disease_svg,plan_pdf
    r=authorized_record(db,record_id,user)
    require_export(db,r,user)
    audit(db,user,"export_zip","record",r.id,r.id);db.flush();data=archive_data(db,r)
    output=io.BytesIO();manifest=[]
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        def write(name,content):
            content=content.encode() if isinstance(content,str) else content
            archive.writestr(name,content);manifest.append({"file":name,"sha256":hashlib.sha256(content).hexdigest(),"bytes":len(content)})
        write("record.json",json.dumps(data,ensure_ascii=False,indent=2))
        write("record.pdf",record_pdf(data))
        for image in db.scalars(select(ImageAsset).where(ImageAsset.record_id==r.id)):
            body=get_path(image.storage_key).read_bytes()
            write(f"normalized/{image.id}.png",body)
            try:original=get_path(f"raw/{r.id}/{image.id}.original").read_bytes()
            except FileNotFoundError:raise HTTPException(409,"原始上传文件缺失，无法生成完整原始档案；请恢复原文件后重试")
            suffix=Path(image.filename).suffix or ".bin"
            write(f"originals/{image.id}{suffix}",original)
            write(f"maps/{image.id}.svg",disease_svg(data,image_dict(image),body))
        for p in data["plans"]:write(f"plans/{p['id']}.pdf",plan_pdf(data,p))
        for entry in db.scalars(select(ArchiveEntry).where(ArchiveEntry.record_id==r.id)):
            if entry.storage_key:
                try:attachment=get_path(entry.storage_key).read_bytes()
                except FileNotFoundError:raise HTTPException(409,"档案附件丢失，请恢复后重新导出")
                write(f"attachments/{entry.section}/{entry.id}{Path(entry.filename).suffix}",attachment)
        write("README.txt","文物病历归档包。originals为上传原始字节，normalized为旋转规范化显示图；SHA256见manifest。逐图provenance保留来源、授权与复核记录，record_kind区分现场调查、教学及公开馆藏参考。模拟图不包含在本包。病害图按GB/T30237-2025六类图示资料包绘制，毫米尺寸按纸面计；缺裂隙中心线时明确提示。资料核对及软件内审不等同成图认证或法定签章。")
        archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    db.commit()
    return Response(output.getvalue(),media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="{r.id}-archive.zip"'})


class UserCreate(BaseModel):
    username:str=Field(min_length=3,max_length=60,pattern=r"^[a-zA-Z0-9_.-]+$")
    name:str=Field(min_length=1,max_length=100)
    role:Literal["surveyor","restorer","expert","manager","admin"]
    password:str=Field(min_length=12,max_length=256)


@api.post("/users")
def create_user(body:UserCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    from .security import hash_password
    require_role(user,"admin")
    row=User(username=body.username,name=body.name,role=body.role,password_hash=hash_password(body.password),org=user.org)
    db.add(row);db.flush();audit(db,user,"create_user","user",row.id,after=public_user(row));db.commit()
    return public_user(row)


@api.get("/users")
def users(user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"admin")
    return [public_user(u) for u in db.scalars(select(User).where(User.org==user.org))]


app.include_router(api)
from .extensions import router as extensions_router,require_export
app.include_router(extensions_router)
from .governance import router as governance_router
app.include_router(governance_router)
from .reference import router as reference_router
app.include_router(reference_router)
from .assistance_api import router as assistance_router
app.include_router(assistance_router)
dist=ROOT/"frontend/dist"
if dist.is_dir():
    app.mount("/",StaticFiles(directory=dist,html=True),name="frontend")
else:
    @app.get("/")
    def home():
        return {"message":"文物病历API已启动。请运行 python3 run.py build 构建前端，然后重启服务。","docs":"/docs"}

