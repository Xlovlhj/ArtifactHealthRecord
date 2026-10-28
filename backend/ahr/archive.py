import json
from sqlalchemy import select
from .config import ROOT
from .db import ArchiveEntry, asdict


def archive_sections():
    return json.loads((ROOT/"data/knowledge/archive_sections.json").read_text())


def entry_dict(row):
    data=asdict(row);data.pop("storage_key",None)
    data["file_url"]=f"/api/v1/archive-entries/{row.id}/file" if row.storage_key else None
    return data


def archive_status(record):
    count={s["key"]:0 for s in archive_sections()}
    count["4.1"]=int(bool(record.get("artifact",{}).get("name")))
    count["4.2"]=int(bool(record.get("survey",{}).get("date")))
    count["4.3"]=len((record.get("clinical_data") or {}).get("examinations",[]))
    count["4.5"]=len(record.get("plans",[]))
    count["4.7"]=int(bool(record.get("diseases")))
    count["4.8"]=len(record.get("images",[]))
    for entry in record.get("archive_entries",[]):count[entry["section"]]+=1
    return [{**s,"count":count[s["key"]],"status":"present" if count[s["key"]] else "missing",
             "notice":"已录入不等于正式档案审查合格"} for s in archive_sections()]
