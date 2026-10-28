import json
from .config import ROOT

PLAN_TITLES = ["概述", "基本信息", "价值评估", "前期调查与研究", "保护修复工作目标", "保护修复技术路线及工艺措施", "施工安全措施", "工作量与进度安排", "经费预算", "保存条件建议", "信息资料管理", "方案委托及编制单位基本信息", "各方签章"]
PLAN_SECTIONS = [{"key": f"3.{i+1}", "title": title} for i, title in enumerate(PLAN_TITLES)]
DISEASES = json.loads((ROOT/"data/knowledge/disease_catalog.json").read_text(encoding="utf-8"))
DISEASE_NAMES = {d["type"] for d in DISEASES}
RULES_VERSION = "ahr-rules-1.1"
STANDARD_VERSION = "GB/T 30237-2025;GB/T 30235-2013;GB/T 30236-2013"


def symbol_package():
    return json.loads((ROOT/"data/knowledge/symbol_package_gbt30237_2025.json").read_text(encoding="utf-8"))


def dictionary():
    result = {"diseases": DISEASES, "plan_sections": PLAN_SECTIONS, "rules_version": RULES_VERSION,
              "standards": [{"code": n, "status": "现行，官方平台核验", "symbols_verified": symbol_package().get("verified",False) if "30237" in n else None} for n in STANDARD_VERSION.split(";")],
              "symbol_package":symbol_package()}
    path = ROOT / "data/knowledge/standards.json"
    if path.exists():
        result["verification"] = json.loads(path.read_text(encoding="utf-8"))
    from .archive import archive_sections
    result["archive_sections"]=archive_sections()
    return result

