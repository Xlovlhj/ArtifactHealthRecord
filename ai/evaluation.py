"""Executable E2–E6 study scoring; human observations remain human observations."""
from __future__ import annotations

from collections import defaultdict
import json
import math
import numpy as np


SCHEMAS = {
    "E2": {"id": "病害图/文物ID", "method": "manual | template | system", "rework_count": "非负整数",
           "expert_reviews": [{"rater_id": "专家ID", "compliant": "bool：按预先固定的合规检查表复核"}]},
    "E3": {"id": "原始记录ID", "method": "manual | vlm | vlm_schema", "gold": {"field": "专家确认值；null表示未知而非负例"},
           "prediction": {"field": "系统抽取值；null/空值为未填"}},
    "E4": {"id": "查询ID", "method": "clip | dinov2 | dinov2_filters", "relevant_ids": ["专家判为相关的案例ID"],
           "ranked_ids": ["实际返回的案例ID，按名次"], "relevance_grades": {"case_id": "可选：专家0..3级相关性"}},
    "E5": {"id": "病例ID", "method": "llm | rag | rag_rules", "blinded": True,
           "expert_reviews": [{"rater_id": "盲评专家ID", "completeness": "1..5", "evidence": "1..5",
                               "risk": "1..5，越高越妥善处理风险", "executability": "1..5"}],
           "citations": [{"claim_id": "主张ID", "source_id": "证据ID", "supported": "bool：人工核对原文是否支持"}]},
    "E6": {"id": "文物/同一操作任务ID", "participant_id": "受试者ID", "site_id": "场地ID",
           "method": "manual | system", "seconds": "实际计时的正数", "rework_count": "非负整数",
           "sus_answers": "可选，标准SUS十题1..5作答；每人每方法只计一次"},
}
METHODS = {"E2": {"manual", "template", "system"}, "E3": {"manual", "vlm", "vlm_schema"},
           "E4": {"clip", "dinov2", "dinov2_filters"}, "E5": {"llm", "rag", "rag_rules"},
           "E6": {"manual", "system"}}
TARGETS = {"E2": {"cases": 30, "experts": 3}, "E3": {"cases": 30}, "E4": {"queries": 50},
           "E5": {"cases": 10, "experts": 3}, "E6": {"sites": 3, "participants": 10, "artifacts": 30}}


def study_template(experiment):
    if experiment not in SCHEMAS:
        raise ValueError("实验编号必须为 E2..E6")
    return {"schema_version": 1, "experiment": experiment, "dataset_kind": "real",
            "protocol": {"sampling": "待填写实际采样规则", "gold_review": "待填写专家与复核方式",
                         "baseline": sorted(METHODS[experiment]), "target_from_guide": TARGETS[experiment]},
            "required_fields": [] if experiment == "E3" else None,
            "record_schema": SCHEMAS[experiment], "records": [], "failures": []}


def summarize(values, seed=42, bootstrap_samples=2000):
    values = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("统计值必须有限")
    n = len(values)
    if not n:
        return {"n": 0, "mean": None, "std": None, "ci95": None}
    result = {"n": n, "mean": float(values.mean()), "std": float(values.std(ddof=1)) if n > 1 else None,
              "ci95": None}
    if n > 1:
        # Chunked resampling bounds memory for large studies.
        generator, means = np.random.default_rng(seed), []
        for start in range(0, bootstrap_samples, 100):
            means.extend(values[generator.integers(0, n, size=(min(100, bootstrap_samples-start), n))].mean(1))
        result["ci95"] = np.quantile(means, [.025, .975]).tolist()
    return result


def _number(value, name, minimum=0, maximum=None, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} 必须是有限数字")
    if value < minimum or (maximum is not None and value > maximum) or (integer and int(value) != value):
        raise ValueError(f"{name} 超出允许范围")
    return float(value)


def _reviews(row):
    reviews = row.get("expert_reviews", [])
    if not reviews:
        raise ValueError("需要真实填写的专家评审，不自动生成专家分数")
    ids = [review.get("rater_id") for review in reviews]
    if any(not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("同一材料的评审专家ID必须非空且不重复")
    return reviews


def _present(value):
    return value is not None and value != "" and value != [] and value != {}


def _canonical(value):
    # Exact match is auditable; no LLM judges or invented fuzzy threshold.
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _e2(row, document):
    reviews = _reviews(row)
    if any(type(review.get("compliant")) is not bool for review in reviews):
        raise ValueError("合规评审必须明确填写 true/false")
    return {"compliance_rate": float(np.mean([review["compliant"] for review in reviews])),
            "rework_count": _number(row["rework_count"], "rework_count", integer=True),
            "expert_count": len(reviews)}


def _e3(row, document):
    fields = document.get("required_fields")
    if not fields or len(set(fields)) != len(fields):
        raise ValueError("E3 必须在采集前明确不重复的 required_fields")
    gold, prediction = row["gold"], row["prediction"]
    if not isinstance(gold, dict) or not isinstance(prediction, dict):
        raise ValueError("gold/prediction 必须是字段映射")
    known = [field for field in fields if gold.get(field) is not None]
    correct = sum(_canonical(prediction.get(field)) == _canonical(gold[field]) for field in known)
    filled = sum(_present(prediction.get(field)) for field in fields)
    unverified = sum(_present(prediction.get(field)) for field in fields if field not in known)
    return {"field_accuracy": correct / len(known) if known else None,
            "completeness": filled / len(fields), "known_field_count": len(known),
            "correct_field_count": correct, "unverified_filled_count": unverified}


def _e4(row, document):
    ranked = row.get("ranked_ids", [])
    relevant = set(row.get("relevant_ids", []))
    if len(set(ranked)) != len(ranked):
        raise ValueError("检索排序不允许重复案例ID占据多个名次")
    if not relevant:
        return {"hit_at_5": None, "precision_at_5": None, "recall_at_5": None, "mrr": None, "ndcg_at_5": None}
    top = ranked[:5]
    hits = sum(item in relevant for item in top)
    first = next((i+1 for i, item in enumerate(ranked) if item in relevant), None)
    grades = row.get("relevance_grades", {item: 1 for item in relevant})
    for grade in grades.values():
        _number(grade, "relevance_grade", maximum=3, integer=True)
    dcg = sum((2 ** grades.get(item, 0)-1) / math.log2(i+2) for i, item in enumerate(top))
    ideal = sum((2 ** grade-1) / math.log2(i+2) for i, grade in enumerate(sorted(grades.values(), reverse=True)[:5]))
    return {"hit_at_5": float(hits > 0), "precision_at_5": hits/5, "recall_at_5": hits/len(relevant),
            "mrr": 1/first if first else 0., "ndcg_at_5": dcg/ideal if ideal else None}


def _e5(row, document):
    if row.get("blinded") is not True:
        raise ValueError("E5 方案必须标记实际已盲评，不以未盲评结果冒充指南实验")
    reviews = _reviews(row)
    result = {}
    for dimension in ("completeness", "evidence", "risk", "executability"):
        result[dimension] = float(np.mean([_number(review[dimension], dimension, 1, 5) for review in reviews]))
    result["overall_score"] = float(np.mean(list(result.values())))
    result["acceptance_at_4"] = float(result["overall_score"] >= 4)
    citations = row.get("citations", [])
    if any(type(citation.get("supported")) is not bool or not citation.get("source_id") or not citation.get("claim_id") for citation in citations):
        raise ValueError("引文需要主张ID、证据ID、人工核对后的 supported 布尔值")
    identifiers = [(citation["claim_id"], citation["source_id"]) for citation in citations]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("同一主张/来源组合不重复计数")
    result["citation_accuracy"] = float(np.mean([citation["supported"] for citation in citations])) if citations else None
    result["unsupported_citation_rate"] = 1-result["citation_accuracy"] if citations else None
    result["citation_count"] = len(citations)
    result["expert_count"] = len(reviews)
    return result


def sus_score(answers):
    if not isinstance(answers, list) or len(answers) != 10:
        raise ValueError("标准 SUS 必须为十道题的原始 1..5 作答")
    checked = [_number(value, "SUS answer", 1, 5, True) for value in answers]
    return sum(value-1 if index % 2 == 0 else 5-value for index, value in enumerate(checked)) * 2.5


def _e6(row, document):
    if not row.get("participant_id") or not row.get("site_id"):
        raise ValueError("E6 需要 participant_id 和 site_id")
    seconds = _number(row["seconds"], "seconds", minimum=1e-9)
    result = {"seconds": seconds, "rework_count": _number(row["rework_count"], "rework_count", integer=True)}
    if row.get("sus_answers") is not None:
        result["sus"] = sus_score(row["sus_answers"])
    return result


def evaluate_study(document):
    experiment = document.get("experiment")
    if experiment not in SCHEMAS:
        raise ValueError("实验编号必须为 E2..E6")
    kind = document.get("dataset_kind")
    if kind not in {"real", "engineering_fixture"}:
        raise ValueError("dataset_kind 必须声明 real 或 engineering_fixture")
    records, scored, unique = document.get("records", []), [], set()
    scorer = {"E2": _e2, "E3": _e3, "E4": _e4, "E5": _e5, "E6": _e6}[experiment]
    for row in records:
        if not row.get("id") or row.get("method") not in METHODS[experiment]:
            raise ValueError("每条记录必须有ID和本实验规定的method")
        key = (row["id"], row["method"], row.get("participant_id"))
        if key in unique:
            raise ValueError("同一材料/参与者/方法重复，会使统计虚高")
        unique.add(key)
        if row.get("data_kind", kind) != kind:
            raise ValueError("真实记录与工程构造数据不得混合进入同一评估")
        scored.append({"id": row["id"], "method": row["method"], "participant_id": row.get("participant_id"),
                       "values": scorer(row, document)})
    metrics, methods = {}, sorted(METHODS[experiment])
    for method in methods:
        current = [row for row in scored if row["method"] == method]
        keys = sorted(set().union(*(row["values"] for row in current))) if current else []
        metric = {}
        for key in keys:
            if experiment == "E6":
                grouped = defaultdict(list)
                for row in current:
                    if key in row["values"]:
                        grouped[row["participant_id"]].append(row["values"][key])
                if key == "sus" and any(len(set(values)) > 1 for values in grouped.values()):
                    raise ValueError("同一参与者同一方法出现不同 SUS 作答；请确定唯一问卷而非重复计权")
                values = [float(np.mean(values)) for values in grouped.values()]
            else:
                values = [row["values"].get(key) for row in current]
            metric[key] = summarize(values)
        metrics[method] = {"record_count": len(current), "metrics": metric}
    paired = {}
    baseline = {"E2": "manual", "E3": "manual", "E4": "clip", "E5": "llm", "E6": "manual"}[experiment]
    for method in methods:
        if method == baseline:
            continue
        pairs = defaultdict(dict)
        for row in scored:
            if row["method"] in {baseline, method}:
                pairs[(row["id"], row["participant_id"])][row["method"]] = row["values"]
        deltas, percent = defaultdict(list), defaultdict(list)
        pair_count = 0
        for (identifier, participant), pair in pairs.items():
            if set(pair) != {baseline, method}:
                continue
            pair_count += 1
            for metric in pair[baseline].keys() & pair[method].keys():
                a, b = pair[baseline][metric], pair[method][metric]
                if a is not None and b is not None:
                    deltas[(metric, participant)].append(b-a)
                    if metric == "seconds" and a > 0:
                        percent[participant].append((a-b)/a)
        by_metric = defaultdict(list)
        for (metric, participant), values in deltas.items():
            by_metric[metric].extend([float(np.mean(values))] if experiment == "E6" else values)
        paired[method] = {"baseline": baseline, "matched_pairs": pair_count,
                          "delta_method_minus_baseline": {metric: summarize(values) for metric, values in by_metric.items()}}
        if experiment == "E6":
            paired[method]["time_reduction_fraction"] = summarize([float(np.mean(values)) for values in percent.values()])
    counts = {"records": len(records), "distinct_materials": len({row["id"] for row in records}),
              "experts": len({review["rater_id"] for row in records for review in row.get("expert_reviews", [])}),
              "participants": len({row["participant_id"] for row in records if row.get("participant_id")}),
              "sites": len({row["site_id"] for row in records if row.get("site_id")})}
    return {"experiment": experiment, "dataset_kind": kind, "status": "measured" if records else "awaiting_observations",
            "counts": counts, "guide_target": TARGETS[experiment], "by_method": metrics, "paired_comparisons": paired,
            "real_world_metrics": {"by_method": metrics, "paired_comparisons": paired} if kind == "real" and records else None,
            "per_record": scored, "failures": document.get("failures", []),
            "statistics": {"std": "sample ddof=1", "ci": "2000 次确定性百分位 bootstrap 95% CI，seed=42；n<2为null",
                           "unit": "E2–E5按独立材料/查询；E6按参与者汇总重复任务，不能把同人多任务当独立受试者",
                           "pairing": "同一材料ID；E6同时匹配参与者ID；不完整配对不参与差值",
                           "citation_accuracy": "专家标注的受支持主张-来源对比例；未提供人工核对为null",
                           "acceptance": "四维度先平均专家评分、再等权均值≥4；报告原始维度，不替代专家判定",
                           "unknown_gold": "E3未知gold不进入准确率分母，另计未验证填充值",
                           "top5": "同时报告Hit@5和Precision@5，后者分母固定为5；无相关真值则null"},
            "claim": "工程构造输入仅验证统计程序，不代表真实实验结果" if kind != "real" else "对录入的实际观察进行统计；专业效能需结合采样、盲法、专家一致性审阅"}


def inter_rater_dice(masks):
    """Pairwise six-class Dice, jointly ignoring uncertain/overlapping pixels."""
    from .labels import CLASS_NAMES
    if len(masks) < 2:
        raise ValueError("至少两位独立标注者的掩膜")
    arrays = {name: np.asarray(mask) for name, mask in masks.items()}
    shapes = {array.shape for array in arrays.values()}
    if len(shapes) != 1 or len(next(iter(shapes))) != 2:
        raise ValueError("所有标注必须是同一原图坐标系的二维掩膜")
    if any(not np.isin(array, [0, 1, 2, 3, 4, 5, 6, 255]).all() for array in arrays.values()):
        raise ValueError("掩膜只接受0..6/255")
    results = []
    names = sorted(arrays)
    for index, first in enumerate(names):
        for second in names[index+1:]:
            a, b = arrays[first], arrays[second]
            valid = (a != 255) & (b != 255)
            scores = {}
            for label in range(1, 7):
                aa, bb = (a == label) & valid, (b == label) & valid
                denominator = int(aa.sum()+bb.sum())
                scores[CLASS_NAMES[label]] = 2*int((aa & bb).sum())/denominator if denominator else None
            results.append({"raters": [first, second], "per_class_dice": scores,
                            "review_below_guide_example_075": [label for label, score in scores.items() if score is not None and score < .75],
                            "jointly_valid_fraction": float(valid.mean())})
    return {"pairs": results, "threshold_basis": "0.75来自指南的一致性示例；不是专业诊断准确率"}
