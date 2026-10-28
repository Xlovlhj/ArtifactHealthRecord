"""Constructed observations test formulas; no fabricated study participants/results."""
import numpy as np
import pytest
from ai.evaluation import evaluate_study, study_template, sus_score, inter_rater_dice, summarize


def document(experiment, records):
    return {**study_template(experiment), "dataset_kind": "engineering_fixture", "records": records}


@pytest.mark.parametrize("experiment", ["E2", "E3", "E4", "E5", "E6"])
def test_empty_studies_have_no_measured_performance(experiment):
    report = evaluate_study(study_template(experiment))
    assert report["status"] == "awaiting_observations" and report["real_world_metrics"] is None


def test_e2_compliance_and_paired_rework():
    rows = [{"id": "fixture", "method": method, "rework_count": count,
             "expert_reviews": [{"rater_id": "mock1", "compliant": status}]} for method, count, status in [("manual", 3, False), ("system", 1, True)]]
    report = evaluate_study(document("E2", rows))
    assert report["by_method"]["system"]["metrics"]["compliance_rate"]["mean"] == 1
    assert report["paired_comparisons"]["system"]["delta_method_minus_baseline"]["rework_count"]["mean"] == -2
    assert report["real_world_metrics"] is None


def test_e3_unknown_gold_is_not_negative_and_abstention_not_correct():
    doc = document("E3", [{"id": "fixture", "method": "vlm_schema", "gold": {"a": "甘肃", "b": None, "c": "莫高窟"},
                           "prediction": {"a": " 甘肃 ", "b": "未经验证", "c": None}}])
    doc["required_fields"] = ["a", "b", "c"]
    values = evaluate_study(doc)["per_record"][0]["values"]
    assert values["field_accuracy"] == .5 and values["completeness"] == pytest.approx(2/3)
    assert values["unverified_filled_count"] == 1


def test_e4_ranking_metrics_and_empty_relevance():
    doc = document("E4", [{"id": "fixture1", "method": "clip", "relevant_ids": ["a", "c"], "ranked_ids": ["x", "a", "b", "c"]},
                          {"id": "fixture2", "method": "clip", "relevant_ids": [], "ranked_ids": ["a"]}])
    values = evaluate_study(doc)["per_record"]
    assert values[0]["values"]["mrr"] == .5
    assert values[0]["values"]["precision_at_5"] == .4 and values[0]["values"]["recall_at_5"] == 1
    assert values[1]["values"]["hit_at_5"] is None


def test_e5_human_citation_support_and_blinded_ratings():
    row = {"id": "fixture", "method": "rag_rules", "blinded": True,
           "expert_reviews": [{"rater_id": "mock1", **dict.fromkeys(["completeness", "evidence", "risk", "executability"], 4)}],
           "citations": [{"claim_id": "c1", "source_id": "s1", "supported": True},
                         {"claim_id": "c2", "source_id": "s2", "supported": False}]}
    values = evaluate_study(document("E5", [row]))["per_record"][0]["values"]
    assert values["acceptance_at_4"] == 1 and values["citation_accuracy"] == .5
    row["blinded"] = False
    with pytest.raises(ValueError, match="盲评"):
        evaluate_study(document("E5", [row]))


def test_e6_sus_scoring_pairing_and_participant_cluster_unit():
    assert sus_score([5, 1]*5) == 100 and sus_score([1, 5]*5) == 0
    rows = []
    for subject, identifier in [("mock1", "x"), ("mock1", "y"), ("mock2", "z")]:
        for method, seconds in [("manual", 100), ("system", 60)]:
            rows.append({"id": identifier, "participant_id": subject, "site_id": "fixture", "method": method,
                         "seconds": seconds, "rework_count": 0, "sus_answers": [5, 1]*5})
    report = evaluate_study(document("E6", rows))
    paired = report["paired_comparisons"]["system"]
    assert paired["matched_pairs"] == 3 and paired["time_reduction_fraction"]["mean"] == .4
    assert paired["time_reduction_fraction"]["n"] == 2
    assert report["by_method"]["system"]["metrics"]["sus"]["n"] == 2


def test_mixed_synthetic_observations_and_duplicate_records_rejected():
    row = {"id": "fixture", "method": "clip", "relevant_ids": ["a"], "ranked_ids": ["a"]}
    with pytest.raises(ValueError, match="重复"):
        evaluate_study(document("E4", [row, row]))
    with pytest.raises(ValueError, match="混合"):
        evaluate_study(document("E4", [{**row, "data_kind": "real"}]))


def test_interrater_dice_and_ignored_region():
    a = np.array([[1, 1, 0], [255, 2, 0]], np.uint8)
    b = np.array([[1, 0, 0], [1, 2, 0]], np.uint8)
    pair = inter_rater_dice({"r1": a, "r2": b})["pairs"][0]
    assert pair["per_class_dice"]["起甲"] == pytest.approx(2/3)
    assert pair["per_class_dice"]["酥碱"] == 1 and pair["per_class_dice"]["空鼓"] is None
    assert pair["review_below_guide_example_075"] == ["起甲"]


def test_sample_sd_and_repeatable_bootstrap():
    stats = summarize([1, 2, 3])
    assert stats["std"] == 1 and stats == summarize([1, 2, 3])
    assert summarize([1])["ci95"] is None and summarize([])["mean"] is None
