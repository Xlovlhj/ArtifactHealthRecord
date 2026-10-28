"""Auditable source declarations, independent review, and organization-scoped data readiness."""
from collections import Counter
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import Artifact, Record, ImageAsset, Disease, CaseReference, User, get_db, now
from .schemas import StrictModel, ImageProvenance
from .provenance import REAL_SOURCE_TYPES, normalized_provenance, provenance_issues, permitted
from .security import current_user, require_role
from .service import authorized_record, assert_version, changed, audit, image_dict

router=APIRouter(prefix="/api/v1")


def declare_provenance(body, user, sha256):
    return {**body.model_dump(), "review_status":"pending", "recorded_by":user.id,
            "recorded_by_name":user.name, "recorded_at":now(), "image_sha256":sha256}


def image_and_record(db,image_id,user):
    image=db.get(ImageAsset,image_id)
    if not image:raise HTTPException(404,"影像不存在")
    record=authorized_record(db,image.record_id,user,True)
    db.refresh(image)
    return image,record


class ProvenanceUpdate(StrictModel):
    expected_version:int
    provenance:ImageProvenance


@router.put("/images/{image_id}/provenance")
def update_provenance(image_id:str,body:ProvenanceUpdate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"surveyor","restorer","expert","admin")
    image,record=image_and_record(db,image_id,user)
    assert_version(record,body.expected_version)
    before=normalized_provenance(image.provenance)
    if before["source_type"]=="synthetic" and body.provenance.source_type!="synthetic":
        raise HTTPException(422,"已登记为合成的图像不能改称真实文物影像；请另行上传真实原图")
    retained={k:before[k] for k in ("reference_image_id","catalog_version","metadata_sha256","view_type","view_type_label") if k in before}
    image.provenance={**declare_provenance(body.provenance,user,image.sha256),**retained}
    changed(db,record)
    audit(db,user,"update_image_provenance","image",image.id,record.id,before,image.provenance)
    db.commit()
    return {**image_dict(image),"record_version":record.version}


class ProvenanceReview(StrictModel):
    expected_version:int
    decision:Literal["verified","rejected"]
    comment:str=Field(min_length=1,max_length=4000)


@router.post("/images/{image_id}/provenance/review")
def review_provenance(image_id:str,body:ProvenanceReview,user:User=Depends(current_user),db:Session=Depends(get_db)):
    require_role(user,"expert","admin")
    image,record=image_and_record(db,image_id,user)
    assert_version(record,body.expected_version)
    before=normalized_provenance(image.provenance)
    if before.get("recorded_by")==user.id:raise HTTPException(403,"来源录入人与复核人须为不同账号")
    issues=provenance_issues(before)
    if body.decision=="verified" and issues:raise HTTPException(422,{"message":"来源/许可资料尚不完整","issues":issues})
    if not body.comment.strip():raise HTTPException(422,"请记录实际核对过的来源与许可依据")
    image.provenance={**before,"review_status":body.decision,"reviewer_id":user.id,"reviewer_name":user.name,
                      "reviewed_at":now(),"review_comment":body.comment,"image_sha256":image.sha256,
                      "review_scope":"来源与使用授权资料复核；不替代病害诊断、真伪鉴定或法律审批"}
    changed(db,record)
    audit(db,user,"review_image_provenance","image",image.id,record.id,before,image.provenance)
    db.commit()
    return {**image_dict(image),"record_version":record.version}


def readiness_data(db,user):
    records=list(db.scalars(select(Record).join(Artifact).where(Artifact.org==user.org)))
    by_id={r.id:r for r in records}
    images=[]
    for image in db.scalars(select(ImageAsset).where(ImageAsset.record_id.in_(by_id))):
        artifact=db.get(Artifact,by_id[image.record_id].artifact_id)
        images.append({**image_dict(image),"record_name":artifact.data.get("name",""),"is_demo":artifact.is_demo,
                       "record_kind":artifact.data.get("record_kind","teaching" if artifact.is_demo else "survey")})
    types=Counter(i["provenance"]["source_type"] for i in images)
    real=[i for i in images if i["provenance"]["source_type"] in REAL_SOURCE_TYPES]
    verified=[i for i in real if i["provenance"]["review_status"]=="verified" and not i["provenance_issues"]]
    ready_eval=[i for i in verified if permitted(i["provenance"],"evaluation",real_only=True) and i["provenance"]["site_group"].strip()]
    complete_cases=list(db.scalars(select(CaseReference).where(CaseReference.org==user.org)))
    counts={"total_images":len(images),"real_images":len(real),"synthetic_images":types["synthetic"],
            "unknown_images":types["unknown"],"verified_real_images":len(verified),"unverified_real_images":len(real)-len(verified),
            "public_dataset_images":types["public_dataset"],"field_capture_images":types["field_capture"],"partner_archive_images":types["partner_archive"],
            "evaluation_ready_images":len(ready_eval),"training_ready_images":sum(permitted(i["provenance"],"training",real_only=True) for i in images),
            "redistribution_ready_images":sum(permitted(i["provenance"],"redistribution") for i in images),
            "calibrated_real_images":sum(bool(i.get("calibration")) for i in real),
            "site_groups":len({i["provenance"]["site_group"] for i in real if i["provenance"]["site_group"].strip()}),
            "licensed_complete_cases":sum(c.data.get("completeness")=="complete" and c.data.get("verified") is True and bool(c.data.get("license_note","")) for c in complete_cases)}
    real_ids={i["id"] for i in real}
    diseases=list(db.scalars(select(Disease).where(Disease.image_id.in_(real_ids))))
    counts["confirmed_real_disease_instances"]=sum(d.confirmed for d in diseases)
    counts["field_capture_artifacts"]=len({i["artifact_id"] for i in images if i["provenance"]["source_type"]=="field_capture" and not i["is_demo"] and i["record_kind"]=="survey"})
    gaps=[{"id":"sources","title":"逐图来源与许可复核","status":"complete" if images and not counts["unknown_images"] and len(verified)==len(real) else "pending",
           "current":len(verified),"target":None,"description":"当前计数来自本机构上传记录；真实来源为用户申报，经独立账号核查后才计入已复核。"},
          {"id":"target_domain","title":"单地域实地调查对象","status":"pending","current":counts["field_capture_artifacts"],"target":30,
           "description":"按文物对象去重计数并排除演示/公开参考记录。指南14天验证先收30–50张图；试点阶段为3家、10位使用者、30件文物，两种计量单位不可混用。"},
          {"id":"annotations","title":"六类病害人工标注与仲裁","status":"pending","current":counts["confirmed_real_disease_instances"],"target":"每类至少 100 个实例；两人独立标注及第三人仲裁",
           "description":"已确认病害数不等于完成双人标注；仍需标注一致性、审核记录和病害级测试集。"},
          {"id":"evaluation","title":"真实独立测试集","status":"pending","current":len(ready_eval),"target":None,
           "description":"此计数仅表示来源复核、评测授权与分组字段就绪，不代表有专家真值或已完成模型评测；合成图不计入。"},
          {"id":"cases","title":"获授权完整病例","status":"complete" if counts["licensed_complete_cases"]>=20 else "pending","current":counts["licensed_complete_cases"],"target":20,
           "description":"需要调查依据、处理过程、结果、出处及授权，并经其他账号复核；公开摘要不计为完整修复病例。"}]
    return {"counts":counts,"images":images,"gaps":gaps,"per_disease_confirmed":dict(Counter(d.type for d in diseases if d.confirmed)),
            "notice":"来源复核不自动确认图像内容、标注质量、标准符合性或算法效果。"}


@router.get("/data/readiness")
def data_readiness(user:User=Depends(current_user),db:Session=Depends(get_db)):
    return readiness_data(db,user)
