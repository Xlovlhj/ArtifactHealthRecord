"""Versioned process checks. Project guardrails are not represented as normative clauses."""
import re
from decimal import Decimal, InvalidOperation
from .catalog import PLAN_SECTIONS, RULES_VERSION
from .knowledge import load_sources


def positive_phrase(text, pattern):
    for clause in re.split(r"[。；;\n]", text):
        for match in re.finditer(pattern, clause):
            prefix = clause[max(0, match.start()-10):match.start()]
            if not re.search(r"不|禁止|避免|不得|拒绝|未采用|无需", prefix):
                return True
    return False


def check_plan(plan, record):
    sections = plan.get("sections", {})
    text = "\n".join(v.get("content", "") for v in sections.values())
    survey = record.get("survey", {})
    diseases = {d["type"] for d in record.get("diseases", [])}
    source_ids = {s["id"] for s in [*load_sources(),*plan.get("evidence_snapshot",[])]}
    items = []

    def add(rule_id, name, result, message, basis, basis_status="project_policy"):
        items.append(dict(rule_id=rule_id, name=name, result=result, message=message, basis=basis, basis_status=basis_status))

    measures = sections.get("3.6", {}).get("content", "")
    active_water = survey.get("water_leak") is True
    environment_checked = bool(re.search(r"渗水|水源|环境调查|环境监测|环境控制|含水率", measures))
    add("R-ENV-001", "环境调查与控制", "warn" if active_water and not environment_checked else "pass", "已记录渗水，但技术路线未交代环境调查/控制；需专家确定先后次序。" if active_water and not environment_checked else "按已记录的环境事实核查；不采用指南示例中的固定70%阈值。", "GB/T 30236-2013 3.4.1、3.4.4、3.6；具体提醒逻辑为项目规则", "verified_structure")
    risky_material = positive_phrase(text, r"不可逆高分子|强酸清洗|强碱清洗")
    has_trial = bool(re.search(r"兼容性试验|相容性试验|材料筛选|小样试验", text))
    add("R-MAT-001", "材料适配证据", "warn" if risky_material and not has_trial else "pass", "拟用材料缺少适配/筛选试验记录，请专家补充依据。" if risky_material and not has_trial else "未发现需提醒的材料表述；不代表材料适用性已获认证。", "GB/T 30236-2013 3.4.5；项目文本筛查")
    irreversible = positive_phrase(text, r"永久性封护|永久封护|不可逆处理")
    add("R-REV-001", "再处理能力", "warn" if irreversible else "pass", "拟采用永久性措施，需补充可再处理性与风险论证。" if irreversible else "未检出肯定式永久封护承诺。", "项目保护原则审查；需专家判断")
    hypothesis = record.get("diagnosis", {}).get("hypothesis", "")
    stable = any("稳定" in clause and not re.search(r"不稳定|未.*稳定|尚.*稳定|是否.*稳定|待.*稳定",clause) for clause in re.split(r"[。；;\n]",hypothesis))
    broad = positive_phrase(text, r"大面积补全|全面重绘|整体重绘")
    add("R-MIN-001", "干预范围", "warn" if stable and broad else "pass", "病历描述稳定，但方案拟大范围补全，请说明必要性。" if stable and broad else "未检出稳定状态与大范围干预的组合。", "项目最小干预审查规则")
    invisible = positive_phrase(text, r"完全做旧|无法辨别修补|看不出修补|看不出修复")
    add("R-REC-001", "补全部分可识别", "block" if invisible else "pass", "方案包含无法辨别修补的目标表述，需修改后再提交。" if invisible else "未检出消除修补可识别性的肯定式要求。", "项目提交门槛；非自动文保鉴定")
    old = "GB/T 30237-2013" in text and not re.search(r"已替代|已被.*替代|历史引用|原文引用", text)
    add("R-STD-001", "病害标准版本", "warn" if old else "pass", "GB/T 30237-2013已被2025版全部代替；请人工核对适用版本。" if old else "未检出直接以2013版病害标准作为现行依据。", "国家标准平台：GB/T 30237-2025替代关系", "verified_metadata")
    missing = [s["key"] + " " + s["title"] for s in PLAN_SECTIONS if not sections.get(s["key"], {}).get("content", "").strip()]
    add("R-STD-002", "方案章节完整性", "block" if missing else "pass", "缺少：" + "、".join(missing) if missing else "13节均有内容；完整性不等于技术方案获批。", "GB/T 30236-2013 3.1—3.13", "verified_fulltext")
    dangerous = positive_phrase(text, r"使用易燃|采用易燃|使用腐蚀|采用腐蚀")
    protection = bool(re.search(r"通风|防火|防护|危险品管理", sections.get("3.7", {}).get("content", "")))
    add("R-SAFE-001", "施工安全说明", "warn" if dangerous and not protection else "pass", "拟用危险材料而安全章节缺少对应防护说明。" if dangerous and not protection else "安全章节表述已核查；现场风险仍需人工评估。", "GB/T 30236-2013 3.7；项目关键词提醒")
    budget = sections.get("3.9", {}).get("content", "")
    budget_missing = not re.search(r"\d", budget) or "待" in budget
    arithmetic_error = False
    # Only check explicit single-item arithmetic. No invented market-price threshold.
    for line in re.split(r"[。；;\n]",budget):
        amount=re.search(r"(?:面积|数量)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:平方米|m2|m²|件)",line)
        price=re.search(r"单价\s*([0-9]+(?:\.[0-9]+)?)\s*元",line)
        total=re.search(r"(?:合计|总额|总价)\s*([0-9]+(?:\.[0-9]+)?)\s*元",line)
        if amount and price and total:
            computed=(Decimal(amount[1])*Decimal(price[1])).quantize(Decimal("0.01"))
            arithmetic_error |= computed != Decimal(total[1]).quantize(Decimal("0.01"))
    add("R-BUD-001", "预算与工作量依据", "warn" if budget_missing or arithmetic_error else "pass", "显式单项数量×单价与合计不一致，请核对算术。" if arithmetic_error else ("预算尚待人工计量/报价，系统不虚构工程单价。" if budget_missing else "已填写数值，仍需人工审核计量依据与当地单价。"), "GB/T 30236-2013 3.8、3.9；算术检查为项目规则，未使用未标定单价阈值")
    missing_refs = [k for k,v in sections.items() if not v.get("citations")]
    invalid_refs = sorted({c for v in sections.values() for c in v.get("citations", []) if c not in source_ids})
    add("R-EVI-001", "引用可追溯性", "block" if invalid_refs else ("warn" if missing_refs else "pass"), "不存在的引用："+"、".join(invalid_refs) if invalid_refs else ("无引用章节："+"、".join(missing_refs) if missing_refs else "引用ID均存在；内容是否支持结论仍须逐条复核。"), "项目循证输出规范")
    originals = [i for i in record.get("images", []) if i.get("image_type") in ("original", "followup")]
    lacks = []
    if not record.get("artifact", {}).get("name"): lacks.append("文物名称")
    if not survey.get("date"): lacks.append("调查日期")
    if not originals: lacks.append("原始影像")
    if originals and not any(i.get("calibration") for i in originals): lacks.append("尺度标定")
    add("R-DATA-001", "病历资料完整性", "block" if lacks else "pass", "待补充："+"、".join(lacks) if lacks else "必要资料已填写；真实性由调查人员负责。", "项目提交门槛，参考档案/调查规范")
    contradiction = stable and positive_phrase(measures, r"立即紧急加固|紧急加固")
    add("R-CONS-001", "诊断与措施一致性", "warn" if contradiction else "pass", "稳定描述与紧急加固同时出现，请专家解释或修订。" if contradiction else "未检出预设的一致性冲突；非完整语义推理。", "项目一致性审查规则")
    hollow = [d for d in record.get("diseases", []) if d["type"] == "空鼓" and d.get("confirmed") and not d.get("field_evidence", "").strip()]
    add("R-FIELD-001", "空鼓现场证据", "block" if hollow else "pass", "空鼓确认缺少现场检测证据，普通照片不能单独确诊。" if hollow else "空鼓确认证据检查完成。", "项目多模态证据门槛")
    from .structured_checks import check_structured
    items.extend(check_structured(plan,record))
    overall = "block" if any(i["result"] == "block" for i in items) else ("warn" if any(i["result"] == "warn" for i in items) else "pass")
    return {"plan_id": plan.get("id"), "overall": overall, "items": items, "rules_version": RULES_VERSION}
