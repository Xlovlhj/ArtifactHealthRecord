"""Engineering checks for guide §10.3; these are not professional accuracy data.

Ten injected conflicts and ten paired controls exercise process checks. They do
not establish diagnostic accuracy, expert agreement, or normative compliance.
The budget conflict uses elementary arithmetic, not an invented market price.
"""
from copy import deepcopy

import pytest

from backend.ahr.generation import make_template
from backend.ahr.rules import check_plan


@pytest.fixture
def baseline():
    record = {
        "artifact": {"name": "工程规则测试壁画", "region": "甘肃", "type": "石窟寺壁画"},
        "survey": {"date": "2026-10-28", "water_leak": False},
        "chief_complaint": "仅用于软件回归的构造输入", "history": "无真实机构与专家声明",
        "diagnosis": {"hypothesis": "待结合调查形成判断"},
        "diseases": [{"type": "裂隙", "confirmed": False, "field_evidence": ""}],
        "images": [{"id": "fixture-image", "image_type": "original", "calibration": {"cm_per_pixel": .1}}],
        "is_demo": True,
    }
    plan = {"id": "fixture-plan", "sections": make_template(record)}
    plan["sections"]["3.9"]["content"] = "面积10平方米，单价100元/平方米，预算合计1000元。"
    return plan, record


def result_for(plan, record, rule_id):
    results = check_plan(plan, record)
    return next(item for item in results["items"] if item["rule_id"] == rule_id)


CASES = [
    ("water_without_control", "R-ENV-001", "warn"),
    ("superseded_standard", "R-STD-001", "warn"),
    ("missing_budget_section", "R-STD-002", "block"),
    ("invisible_reconstruction", "R-REC-001", "block"),
    ("stable_broad_intervention", "R-MIN-001", "warn"),
    ("flammable_without_protection", "R-SAFE-001", "warn"),
    ("budget_arithmetic_conflict", "R-BUD-001", "warn"),
    ("missing_citation", "R-EVI-001", "warn"),
    ("missing_original_image", "R-DATA-001", "block"),
    ("stable_emergency_contradiction", "R-CONS-001", "warn"),
]


def inject(case, plan, record, conflict):
    if case == "water_without_control":
        record["survey"]["water_leak"] = True
        plan["sections"]["3.6"]["content"] = "先实施本体加固。" if conflict else "先完成水源调查和环境控制，再由专家决定处理顺序。"
    elif case == "superseded_standard":
        plan["sections"]["3.4"]["content"] = "本次病害调查采用GB/T 30237-2013。" if conflict else "历史引用GB/T 30237-2013，该版本已被GB/T 30237-2025替代；本次核对现行版本。"
    elif case == "missing_budget_section":
        if conflict:
            plan["sections"].pop("3.9")
    elif case == "invisible_reconstruction":
        plan["sections"]["3.6"]["content"] = "对修补区域完全做旧，使人看不出修补。" if conflict else "禁止完全做旧；修补部分保持可识别性。"
    elif case == "stable_broad_intervention":
        record["diagnosis"]["hypothesis"] = "目前病害稳定。"
        plan["sections"]["3.6"]["content"] = "开展大面积补全。" if conflict else "保持监测，仅在必要区域进行局部处理。"
    elif case == "flammable_without_protection":
        plan["sections"]["3.6"]["content"] = "使用易燃材料进行处理。"
        plan["sections"]["3.7"]["content"] = "安排施工人员。" if conflict else "落实通风、防火、人员防护和危险品管理。"
    elif case == "budget_arithmetic_conflict":
        plan["sections"]["3.8"]["content"] = "单项处理面积100平方米。"
        plan["sections"]["3.9"]["content"] = "面积100平方米，单价100元/平方米，预算合计1元。" if conflict else "面积100平方米，单价100元/平方米，预算合计10000元。"
    elif case == "missing_citation":
        if conflict:
            plan["sections"]["3.6"]["citations"] = []
    elif case == "missing_original_image":
        if conflict:
            record["images"] = []
    elif case == "stable_emergency_contradiction":
        record["diagnosis"]["hypothesis"] = "当前状态稳定。"
        plan["sections"]["3.6"]["content"] = "立即紧急加固。" if conflict else "不需要紧急加固；继续定期监测。"
    else:
        raise AssertionError(f"未知测试用例: {case}")


@pytest.mark.parametrize("case,rule_id,expected", CASES, ids=[row[0] for row in CASES])
def test_guide_ten_injected_conflicts(baseline, case, rule_id, expected):
    plan, record = deepcopy(baseline)
    inject(case, plan, record, conflict=True)
    finding = result_for(plan, record, rule_id)
    assert finding["result"] == expected, finding


@pytest.mark.parametrize("case,rule_id,unused", CASES, ids=[row[0] for row in CASES])
def test_guide_ten_paired_controls(baseline, case, rule_id, unused):
    plan, record = deepcopy(baseline)
    inject(case, plan, record, conflict=False)
    finding = result_for(plan, record, rule_id)
    assert finding["result"] == "pass", finding


def test_complete_control_is_not_blocked(baseline):
    assert check_plan(*baseline)["overall"] == "pass"


@pytest.mark.parametrize("diagnosis", ["病害尚不稳定，存在继续发展的证据。", "尚未确认病害稳定，需继续调查。"])
def test_negated_or_unconfirmed_stability_is_not_a_stable_diagnosis(baseline, diagnosis):
    plan, record = deepcopy(baseline)
    record["diagnosis"]["hypothesis"] = diagnosis
    plan["sections"]["3.6"]["content"] = "结合新证据由专家判断是否需要紧急加固。"
    finding = result_for(plan, record, "R-CONS-001")
    assert finding["result"] == "pass", finding


def test_hollowing_requires_field_evidence_even_with_a_photo(baseline):
    plan, record = deepcopy(baseline)
    record["diseases"] = [{"type": "空鼓", "confirmed": True, "field_evidence": ""}]
    assert result_for(plan, record, "R-FIELD-001")["result"] == "block"
    record["diseases"][0]["field_evidence"] = "工程测试：现场检测记录编号X（非真实鉴定）"
    assert result_for(plan, record, "R-FIELD-001")["result"] == "pass"


def test_known_and_forged_citations_are_distinguished(baseline):
    plan, record = deepcopy(baseline)
    assert result_for(plan, record, "R-EVI-001")["result"] == "pass"
    plan["sections"]["3.6"]["citations"] = ["FABRICATED-CLAUSE-DOES-NOT-EXIST"]
    assert result_for(plan, record, "R-EVI-001")["result"] == "block"
