"""Offline transport fixtures: fallback logic, not a live-model capability test."""
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.ahr import generation


@pytest.fixture
def fixture_record():
    return {
        "artifact": {"name": "LLM工程测试", "region": "甘肃", "location": "不应发送的精确位置"},
        "survey": {"date": "2026-10-28"}, "chief_complaint": "构造测试文本", "history": "",
        "diagnosis": {"hypothesis": "待确认", "evidence": []}, "diseases": [], "is_demo": True,
    }


@pytest.fixture
def configured_mock(monkeypatch):
    config = SimpleNamespace(llm_model="offline-mock-model", llm_base_url="https://offline.invalid/v1",
                             llm_api_key="dummy-not-a-real-key", allow_external_models=True)
    monkeypatch.setattr(generation, "settings", lambda: config)
    return config


@pytest.mark.parametrize("failure", ["malformed_json", "forged_citation", "missing_section"])
def test_invalid_model_output_falls_back_without_leaking_unchecked_text(monkeypatch, configured_mock, fixture_record, failure):
    sections = generation.make_template(fixture_record)
    sections["3.6"]["content"] = "UNTRUSTED_TEXT_MUST_NOT_SURVIVE"
    if failure == "forged_citation":
        sections["3.6"]["citations"] = ["FABRICATED-EXPERT-CLAUSE"]
    if failure == "missing_section":
        sections.pop("3.9")
    content = "{broken json" if failure == "malformed_json" else json.dumps({"sections": sections})
    requests = []

    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert "不应发送的精确位置" not in payload["messages"][1]["content"]
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    original_client = httpx.Client
    monkeypatch.setattr(generation.httpx, "Client", lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs))
    result = generation.generate_plan(fixture_record)
    assert len(requests) == 2  # exactly one correction attempt
    assert result["provider"] == "template_fallback"
    assert result["model_version"] == "evidence-template-v1"
    assert "UNTRUSTED_TEXT_MUST_NOT_SURVIVE" not in json.dumps(result)
    assert len(result["sections"]) == 13
    assert "回退" in result["generation_note"]


def test_real_record_without_external_authorization_stays_local(monkeypatch, configured_mock, fixture_record):
    fixture_record["is_demo"] = False
    configured_mock.allow_external_models = False

    def forbidden_call(*args, **kwargs):
        raise AssertionError("未授权真实病历不应调用外部模型")

    monkeypatch.setattr(generation, "call_json", forbidden_call)
    result = generation.generate_plan(fixture_record)
    assert result["provider"] == "template_fallback"
    assert "授权" in result["generation_note"] and "本地" in result["generation_note"]


def test_mock_valid_output_still_cannot_sign_as_an_expert(monkeypatch, configured_mock, fixture_record):
    sections = generation.make_template(fixture_record)
    sections["3.13"]["content"] = "虚构专家已签字批准"
    monkeypatch.setattr(generation, "call_json", lambda *args, **kwargs: {"sections": sections})
    result = generation.generate_plan(fixture_record)
    assert result["provider"] == "openai_compatible"  # transport is mocked in this test only
    assert result["model_version"] == "offline-mock-model"
    assert "虚构专家" not in result["sections"]["3.13"]["content"]
    assert "AI未签字" in result["sections"]["3.13"]["content"]


@pytest.mark.parametrize("authorized", [False, True])
def test_optional_vision_extraction_respects_authorization_and_model(monkeypatch, configured_mock, fixture_record, authorized):
    configured_mock.vision_model="offline-vision-model"
    configured_mock.allow_external_models=authorized
    calls=[]
    image="data:image/jpeg;base64,OFFLINE_TEST_IMAGE"
    def handler(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body["model"]=="offline-vision-model"
        assert body["messages"][1]["content"][1]["image_url"]["url"]==image
        output={"chief_complaint":"原文观察","history":"","diagnosis":{"hypothesis":"","evidence":[],"uncertainty":"待核"}}
        return httpx.Response(200,json={"choices":[{"message":{"content":json.dumps(output)}}]})
    original_client=httpx.Client
    monkeypatch.setattr(generation.httpx,"Client",lambda **kwargs:original_client(transport=httpx.MockTransport(handler),**kwargs))
    result=generation.extract_record("观察文字",fixture_record,image)
    assert len(calls)==int(authorized)
    assert result["provider"]==("vision_openai_compatible" if authorized else "manual_fallback")
