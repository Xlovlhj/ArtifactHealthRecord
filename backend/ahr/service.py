import hashlib
import json
from sqlalchemy import select
from fastapi import HTTPException
from .db import Artifact, Survey, Record, ImageAsset, Disease, Plan, Consultation, Simulation, AuditLog, User, ArchiveEntry, now, asdict
from .catalog import RULES_VERSION, STANDARD_VERSION


def authorized_record(db, record_id, user, lock=False):
    stmt = select(Record).where(Record.id == record_id)
    if lock: stmt = stmt.with_for_update().execution_options(populate_existing=True)
    record = db.scalar(stmt)
    if record is None or db.get(Artifact,record.artifact_id).org != user.org:
        raise HTTPException(404,"病历不存在或无访问权限")
    return record


def image_dict(row):
    data = asdict(row)
    data.pop("storage_key",None)
    data["url"] = f"/api/v1/images/{row.id}/file"
    from .provenance import normalized_provenance, provenance_issues
    data["provenance"] = normalized_provenance(row.provenance)
    data["provenance_issues"] = provenance_issues(data["provenance"])
    return data


def plan_dict(row):
    return asdict(row)


def record_detail(db, record, include_audit=True):
    artifact = db.get(Artifact,record.artifact_id)
    survey = db.get(Survey,record.survey_id)
    result = {**asdict(record), "artifact": {"id":artifact.id,**artifact.data}, "survey":{"id":survey.id,**survey.data}, "is_demo":artifact.is_demo}
    result["images"] = [image_dict(x) for x in db.scalars(select(ImageAsset).where(ImageAsset.record_id==record.id).order_by(ImageAsset.created_at))]
    result["diseases"] = [asdict(x) for x in db.scalars(select(Disease).where(Disease.record_id==record.id))]
    result["plans"] = [plan_dict(x) for x in db.scalars(select(Plan).where(Plan.record_id==record.id).order_by(Plan.version.desc()))]
    result["consultations"] = []
    for c in db.scalars(select(Consultation).where(Consultation.record_id==record.id).order_by(Consultation.created_at.desc())):
        user = db.get(User,c.user_id)
        result["consultations"].append({**asdict(c),"author":user.name if user else c.user_id})
    result["simulations"] = [{"id":s.id,"image_id":s.image_id,"created_at":s.created_at,"url":f"/api/v1/simulations/{s.id}/file",**s.data,"uncertainty_url":f"/api/v1/simulations/{s.id}/uncertainty" if s.data.get("uncertainty_storage_key") else None} for s in db.scalars(select(Simulation).where(Simulation.record_id==record.id))]
    from .casebook import selected_evidence
    from .archive import entry_dict,archive_status
    result["evidence_sources"]=selected_evidence(db,record,artifact.org)
    result["archive_entries"]=[entry_dict(e) for e in db.scalars(select(ArchiveEntry).where(ArchiveEntry.record_id==record.id))]
    result["archive_completeness"]=archive_status(result)
    if include_audit:
        result["audit"] = [asdict(a) for a in db.scalars(select(AuditLog).where(AuditLog.record_id==record.id).order_by(AuditLog.created_at.desc()).limit(100))]
    return result


def snapshot(db,record):
    data = record_detail(db,record,False)
    return {k:v for k,v in data.items() if k not in ("plans","consultations","simulations")}


def audit(db,user,action,kind,obj_id,record_id=None,before=None,after=None):
    previous = db.scalar(select(AuditLog).where(AuditLog.record_id==record_id).order_by(AuditLog.created_at.desc()).limit(1))
    created = now()
    payload={"user_id":user.id if hasattr(user,"id") else str(user),"action":action,"object_type":kind,"object_id":obj_id,"record_id":record_id,"before":before,"after":after,"created_at":created,"metadata_versions":{"rules":RULES_VERSION,"standards":STANDARD_VERSION},"previous_hash":previous.entry_hash if previous else ""}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()
    row=AuditLog(**payload,entry_hash=digest)
    db.add(row)
    return row


def changed(db,record):
    record.version += 1
    record.updated_at = now()
    record.status = "draft"
    for plan in db.scalars(select(Plan).where(Plan.record_id==record.id,Plan.status.in_(["review","approved"]))):
        plan.status="superseded"


def assert_version(record,expected):
    if expected != record.version:
        raise HTTPException(409,"病历已被其他操作修改，请刷新后再保存")


def content_hash(plan):
    payload={"id":plan.id,"record_id":plan.record_id,"version":plan.version,"record_version":plan.record_version,"record_snapshot":plan.record_snapshot,"sections":plan.sections,"citations":plan.citations}
    if plan.evidence_snapshot:payload["evidence_snapshot"]=plan.evidence_snapshot
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

