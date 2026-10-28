"""Organization-scoped case library and versioned evidence selection."""
from sqlalchemy import select
from fastapi import HTTPException
from .db import CaseReference, Consultation, User, ArchiveEntry
from .knowledge import load_sources, rank_rows, optional_vector_search
from .config import settings


def case_dict(row, org):
    data={**row.data,"id":row.id,"source_url":row.source,"version":row.version,
          "record_id":row.record_id,"editable":row.org==org,"is_public":row.org is None}
    data.setdefault("completeness","abstract")
    data.setdefault("license_note",data.get("rights", "仅保存公开资料的自行整理摘要；原始影像许可另核"))
    data.setdefault("plan_summary",data.get("treatment",""))
    data.setdefault("expert_note","")
    return data


def get_case(db,case_id,org):
    row=db.get(CaseReference,case_id)
    if row and row.org in (None,org):return case_dict(row,org)
    for source in load_sources():
        if source["id"]==case_id and source.get("kind")=="case":
            return {**source,"editable":False,"is_public":True,"version":1,"completeness":source.get("completeness","abstract")}
    raise HTTPException(404,"病例不存在或无访问权限")


def case_rows(db,org):
    rows={s["id"]:{**s,"editable":False,"is_public":True,"version":1,"completeness":s.get("completeness","abstract")} for s in load_sources() if s.get("kind")=="case"}
    for row in db.scalars(select(CaseReference).where(CaseReference.org==org)):
        rows[row.id]=case_dict(row,org)
    return list(rows.values())


def list_cases(db,org,q="",disease="",region="",material=""):
    rows=case_rows(db,org)
    if disease:rows=[r for r in rows if disease in r.get("diseases",[])]
    if region:rows=[r for r in rows if region in r.get("region","")]
    if material:rows=[r for r in rows if material in str(r.get("material",""))]
    return rank_rows(q,rows,100) if q else rows


def selected_evidence(db,record,org):
    result=[]
    for case_id in record.evidence_ids or []:
        result.append(get_case(db,case_id,org))
    for note in db.scalars(select(Consultation).where(Consultation.record_id==record.id)):
        author=db.get(User,note.user_id)
        if author and author.role=="expert":
            result.append({"id":note.id,"kind":"expert","title":f"会诊意见 · {author.name}",
                "text":note.comment,"source_url":f"/api/v1/records/{record.id}","publisher":author.name,
                "created_at":note.created_at,"plan_id":note.plan_id,"decision":note.decision,
                "verified":True,"is_demo":author.name.startswith("演示·"),"scope":"本病历内部会诊记录"})
    for entry in db.scalars(select(ArchiveEntry).where(ArchiveEntry.record_id==record.id,ArchiveEntry.section.in_(["4.3","4.4"]))):
        result.append({"id":entry.id,"kind":"material" if entry.section=="4.4" else "investigation",
            "title":entry.title,"text":entry.text,"source_url":f"/api/v1/records/{record.id}",
            "publisher":entry.author,"date":entry.date,"verified":False,"scope":"本机构录入资料，须人工核对附件"})
    return result


def retrieve_cases(db,record,org,disease="",region="",material="",image_path=None):
    artifact=record["artifact"]
    diseases={d["type"] for d in record.get("diseases",[])}
    query=" ".join([artifact.get("region",""),artifact.get("ground_type",""),*sorted(diseases),record.get("chief_complaint","")])
    candidates=list_cases(db,org,"",disease,region,material)
    ranked=rank_rows(query,candidates,len(candidates),include_zero=True)
    ranked.sort(key=lambda x:(bool(set(x.get("diseases",[]))&diseases),artifact.get("region","") in x.get("region",""),x.get("score") or 0),reverse=True)
    method="BM25 + 病害/地域优先；材质/病害/地域显式过滤"
    if settings().allow_external_models:
        ranked, vector_method=optional_vector_search(query,ranked)
        method+="；"+vector_method
    image_result=None
    if image_path:
        from ai.retrieval import search_images
        from .storage import get_path
        images=[]
        for c in ranked:
            for item in c.get("images",[]):
                if item.get("storage_key"):
                    images.append({**c,"path":str(get_path(item["storage_key"]))})
        cfg=settings()
        image_result=search_images(image_path,images,model_dir=cfg.retrieval_model_dir or None,backend=cfg.retrieval_backend,top_k=8)
        if image_result.get("status")=="ok":
            by_id={c["id"]:c for c in ranked}
            ranked=[{**by_id[item["id"]],**item} for item in image_result["items"]]
            method=image_result["method"]
    return {"items":ranked[:8],"method":method,"image_retrieval":image_result,"cache_hit":False}
