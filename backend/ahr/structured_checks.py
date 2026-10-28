import json
from decimal import Decimal
from .config import ROOT


def check_structured(plan,record):
    findings=[]
    def add(id,name,result,message,basis,status="project_policy",**extra):
        findings.append({"rule_id":id,"name":name,"result":result,"message":message,"basis":basis,"basis_status":status,**extra})
    operations=plan.get("sections",{}).get("3.6",{}).get("measures",[])
    positions={m["id"]:i for i,m in enumerate(operations)}
    wrong=[m["id"] for i,m in enumerate(operations) if any(p not in positions or positions[p]>=i for p in m.get("prerequisites",[]))]
    add("R-ORDER-001","工序先后与依赖","block" if wrong else "pass","前置工序未先完成或存在依赖循环："+"、".join(wrong) if wrong else "工序依赖顺序一致；实际开工仍须通过现场与专家确认。","指南§5.5的工序顺序，项目结构化提交检查")
    if record.get("survey",{}).get("water_leak") is True and operations:
        first_body=next((i for i,m in enumerate(operations) if m["category"]=="body"),None)
        first_environment=next((i for i,m in enumerate(operations) if m["category"]=="environment"),None)
        bad=first_body is not None and (first_environment is None or first_environment>first_body)
        add("R-ENV-ORDER","渗水情况下的工序顺序","warn" if bad else "pass","已记录渗水，但本体处理排在环境控制之前或缺少环境工序。" if bad else "环境工序排在本体处理之前；不设置通用湿度阈值。","GB/T30236-2013 3.6；先环境后本体为待专家确认的项目规则")
    valid={s["id"] for s in plan.get("evidence_snapshot",[])}
    from .knowledge import load_sources
    valid|={s["id"] for s in load_sources()}
    absent=[m["id"] for m in operations if not m.get("citations")]
    invalid=[m["id"] for m in operations if set(m.get("citations",[]))-valid]
    add("R-EVI-MEASURE","逐项措施依据","block" if invalid else ("warn" if absent else "pass"),"措施引用不存在："+"、".join(invalid) if invalid else ("缺少依据的措施："+"、".join(absent) if absent else "已逐项核对措施引用；引用支持程度需专家判断。"),"指南§9.5；版本化规范、病例、专家意见")
    budget=plan.get("sections",{}).get("3.9",{}).get("budget_items",[])
    errors=[];missing=[]
    for item in budget:
        if item.get("unit_price") is None or item.get("total") is None or not item.get("source","").strip():
            missing.append(item["item"]);continue
        computed=(Decimal(str(item["quantity"]))*Decimal(str(item["unit_price"]))).quantize(Decimal("0.01"))
        if computed!=Decimal(str(item["total"])).quantize(Decimal("0.01")):errors.append(item["item"])
    if budget:add("R-BUD-STRUCTURED","分项计量与预算算术","warn" if errors or missing else "pass",f"算术不符：{'、'.join(errors) or '无'}；单价/总额/依据缺失：{'、'.join(missing) or '无'}","GB/T30236-2013 3.8/3.9；仅核对录入数量与单价，不推断市场价格")
    path=ROOT/"data/rules/flaking-material-checks.json"
    rules=json.loads(path.read_text()) if path.exists() else []
    diseases={d["type"] for d in record.get("diseases",[])}
    for number,test in enumerate((record.get("clinical_data") or {}).get("material_tests",[]),1):
        for rule in rules:
            if rule["requires_disease"] not in diseases or rule["scope"]!=test.get("scope"):continue
            value=test.get("values",{}).get(rule["field"])
            if value is None:continue
            evidence=bool(test.get("method","").strip() and test.get("source","").strip())
            out=(rule["min"] is not None and value<rule["min"]) or (rule["max"] is not None and value>rule["max"])
            add(rule["id"]+f"-T{number}",rule["name"],"warn" if out or not evidence else "pass",
                f"试验{number}录入值 {value} {rule['unit']}；本条范围 {rule['min'] if rule['min'] is not None else '无下限'} 至 {rule['max'] if rule['max'] is not None else '无上限'}。"+("超出条款范围，需复测及专家确认。" if out else "录入值在条款范围内；不等于材料获准使用。")+("缺少方法/检测出处。" if not evidence else ""),
                f"{rule['standard']} {rule['clause']}；{rule['method']}","verified_fulltext",source_url=rule["source_url"],scope=rule["scope"],field=rule["field"],measured_value=value)
    return findings
