"""Exercise the real compiled UI against an isolated, temporary backend.

Run from the project root with the conda interpreter:
    python3 frontend/tests/browser_smoke.py

No existing records are touched. Screenshots contain teaching/test fixtures only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler

from playwright.sync_api import expect, sync_playwright
from PIL import Image, PngImagePlugin


ROOT = Path(__file__).resolve().parents[2]
PORT = 18765
BASE = f"http://127.0.0.1:{PORT}"
SCREENSHOTS = ROOT / "runtime/screenshots"
REPORT = ROOT / "docs/frontend-validation.json"


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    checks: list[str] = []
    outputs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ahr-browser-") as temporary:
        env = dict(os.environ)
        env.update(
            AHR_RUNTIME_DIR=temporary,
            AHR_DATABASE_URL=f"sqlite:///{temporary}/browser.db",
            AHR_DEMO_MODE="true",
            AHR_ENV="development",
            AHR_STORAGE="local",
            AHR_REDIS_URL="",
            AHR_ALLOW_EXTERNAL_MODELS="false",
            AHR_INPAINT_METHOD="interpolation",
            AHR_INPAINT_CHECKPOINT="",
            AHR_BOOTSTRAP_PASSWORD="ahr-demo-2026",
            AHR_ALLOWED_ORIGINS=BASE,
            AHR_LLM_BASE_URL="",
            AHR_LLM_API_KEY="",
            AHR_VISION_MODEL="",
            AHR_SEGMENTATION_CHECKPOINT="",
            AHR_SAM_MODEL_DIR="",
        )
        log = open(Path(temporary) / "server.log", "w+")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "backend.ahr.main:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            opener = build_opener(ProxyHandler({}))
            for _ in range(100):
                if server.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read())
                try:
                    opener.open(BASE + "/api/v1/health", timeout=.5).close()
                    break
                except OSError:
                    time.sleep(.15)
            else:
                raise RuntimeError("Temporary backend did not start")
            with sync_playwright() as playwright:
                executable = shutil.which("google-chrome") or shutil.which("chromium")
                browser = playwright.chromium.launch(
                    executable_path=executable,
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = browser.new_context(
                    viewport={"width": 1440, "height": 1000},
                    accept_downloads=True, locale="zh-CN",
                )
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("response", lambda response: errors.append(
                    f"HTTP {response.status}: {response.url}") if response.status >= 500 else None)

                def screenshot(name: str) -> None:
                    while page.locator(".toast .icon-button").count():
                        page.locator(".toast .icon-button").first.click()
                    page.evaluate("window.scrollTo(0, 0)")
                    path = SCREENSHOTS / f"{name}.png"
                    page.screenshot(path=str(path), full_page=True, animations="disabled")
                    outputs.append(str(path.relative_to(ROOT)))

                def login(role: str) -> None:
                    page.goto(BASE)
                    page.get_by_label("工作身份").select_option(role)
                    page.get_by_label("登录密码").fill("ahr-demo-2026")
                    page.get_by_role("button", name="进入工作台").click()
                    expect(page.locator(".sidebar")).to_be_visible()

                def request(action, method: str, suffix: str):
                    with page.expect_response(lambda response: response.request.method == method
                                              and suffix in response.url) as response:
                        try:
                            action()
                        except Exception:
                            screenshot("failure")
                            print("PAGE ERRORS:", errors)
                            print(page.locator("body").inner_text()[-6000:])
                            raise
                    result = response.value
                    assert result.ok, f"{method} {suffix}: {result.status} {result.text()}"
                    return result.json()

                login("restorer")
                expect(page.get_by_role("heading", name="让保护，有据可循。")).to_be_visible()
                expect(page.locator(".stat-card")).to_have_count(4)
                screenshot("01-dashboard-desktop")
                checks.append("Real dashboard statistics and authenticated session")

                page.goto(BASE + "/#records")
                page.get_by_role("button", name="新建病历", exact=True).click()
                page.get_by_label("文物 / 壁画名称").fill("浏览器验收 · 教学调查记录")
                expect(page.get_by_label("地区", exact=True)).to_have_value("甘肃")
                created = request(lambda: page.get_by_role("button", name="创建病历", exact=True).click(), "POST", "/records")
                record_id = created["id"]
                assert created["artifact"]["area_m2"] is None
                assert created["survey"]["humidity"] is None
                assert created["survey"]["water_leak"] is None
                expect(page.get_by_role("heading", name="浏览器验收 · 教学调查记录")).to_be_visible()
                checks.append("Create record; Gansu default; unknown measurements stay null")

                fixture = next(Path(temporary).rglob("demo.png"))
                assert fixture.is_file()
                request(lambda: page.locator("input[type=file]").set_input_files(str(fixture)), "POST", "/images")
                page.get_by_role("button", name="补录 / 修改影像来源", exact=True).click()
                dialog = page.get_by_role("dialog", name="编辑影像来源与授权")
                dialog.get_by_label("影像来源类型").select_option("synthetic")
                dialog.get_by_label("数据集 / 来源名称").fill("原创浏览器教学夹具")
                dialog.get_by_label("许可证名称", exact=True).fill("项目原创素材")
                dialog.get_by_label("授权证据与使用限制").fill("backend/ahr/seed.py 程序生成，仅供工程测试。")
                dialog.get_by_label("内部展示", exact=True).check()
                expect(dialog.get_by_label("真实数据评测", exact=True)).to_be_disabled()
                provenance = request(lambda: dialog.get_by_role("button", name="保存影像来源", exact=True).click(), "PUT", "/provenance")
                assert provenance["provenance"]["source_type"] == "synthetic"
                assert provenance["provenance"]["review_status"] == "pending"
                expect(page.locator(".image-thumb").first).to_contain_text("合成 / 教学素材")
                checks.append("Image-level source editing persists provenance; synthetic images visibly labelled and cannot be authorized for real-data evaluation")
                duplicate = request(lambda: page.locator("input[type=file]").set_input_files(str(fixture)), "POST", "/images")
                assert duplicate["duplicate"] is True and duplicate["provenance"]["source_type"] == "synthetic"
                expect(page.locator(".toast").filter(has_text="相同原始文件已存在")).to_be_visible()
                expect(page.locator(".image-thumb")).to_have_count(1)
                checks.append("Duplicate image upload reports no new file and no provenance overwrite, with an explicit correction path")
                expect(page.locator("svg[aria-label='原图病害多边形标注画布']")).to_be_visible()
                page.get_by_role("button", name="多边形", exact=True).click()
                canvas = page.locator("svg[aria-label='原图病害多边形标注画布']")
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                assert box
                for x, y in [(200, 200), (340, 200), (340, 330), (200, 330)]:
                    page.mouse.click(box["x"] + x / 1100 * box["width"],
                                     box["y"] + y / 760 * box["height"])
                page.get_by_role("button", name="闭合区域").click()
                page.get_by_label("影像观察依据").fill("浏览器端到端测试的人工教学标注。")
                page.get_by_label("已人工核对并确认").check()
                annotated = request(lambda: page.get_by_role("button", name="保存标注").click(), "PUT", "/diseases")
                assert len(annotated["diseases"]) == 1
                assert abs(annotated["diseases"][0]["area_px"] - 18200) < 5
                assert annotated["diseases"][0]["confidence"] is None
                checks.append("Upload original image; polygon uses original image coordinates; server computes area")

                page.get_by_role("button", name="标尺", exact=True).click()
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                assert box
                for x, y in [(100, 650), (300, 650)]:
                    page.mouse.click(box["x"] + x / 1100 * box["width"],
                                     box["y"] + y / 760 * box["height"])
                page.get_by_label("两点之间实际长度厘米").fill("20")
                request(lambda: page.get_by_role("button", name="保存标定").click(), "PUT", "/calibration")
                expect(page.get_by_text("已标定：20 cm / 两点距离")).to_be_visible()
                page.get_by_role("button", name="质量检查 / 分割候选").click()
                expect(page.get_by_text("分割模型未配置", exact=True)).to_be_visible(timeout=30000)
                screenshot("02-annotation-desktop")
                checks.append("Two-point calibration and honest unavailable-model quality analysis")

                # A second image makes source-image history and longitudinal comparison testable.
                followup_fixture=Path(temporary)/"followup-teaching.png"
                metadata=PngImagePlugin.PngInfo();metadata.add_text("fixture","same-pixels-distinct-file-for-comparison")
                Image.open(fixture).save(followup_fixture,pnginfo=metadata)
                second_image = request(lambda: page.locator("input[type=file]").set_input_files(str(followup_fixture)), "POST", "/images")
                page.get_by_role("button", name="结构化病历", exact=True).click()
                before_extraction = page.request.get(f"{BASE}/api/v1/records/{record_id}").json()
                include_image = page.get_by_label("同时读取当前影像／档案图")
                expect(include_image).not_to_be_checked()
                include_image.check()
                page.get_by_label("原始调查文字").fill("教学测试：记录图案局部情况，尚无现场检测证据。")
                selected_image_id = page.get_by_label("用于抽取的影像／档案图").input_value()
                with page.expect_request(lambda req: req.method == "POST" and req.url.endswith("/extract")) as extract_request:
                    extracted = request(lambda: page.get_by_role("button", name="抽取为病历草稿").click(), "POST", "/extract")
                assert extract_request.value.post_data_json["image_id"] == selected_image_id
                assert extracted["provider"] == "manual_fallback"
                expect(page.locator(".extraction-preview")).to_contain_text(extracted["uncertainty"])
                after_extraction = page.request.get(f"{BASE}/api/v1/records/{record_id}").json()
                assert all(after_extraction[key] == before_extraction[key] for key in ("version", "chief_complaint", "history", "diagnosis"))
                screenshot("07-extraction-fallback")
                checks.append("Optional image extraction defaults off; selected image_id sent; unconfigured VLM returns explicit manual fallback without persisting drafts")
                page.get_by_label("诊断假设", exact=True).fill("教学样板，需依据真实检测确认。")
                page.get_by_label("依据清单（每行一项）").fill("项目原创教学影像")
                clinical_fields = {
                    "既往处置": {"处置方法":"教学历史处置记录", "实施者":"测试人员", "记录出处":"本地测试档案"},
                    "检查与检测": {"方法 / 仪器":"教学观察", "结果 / 实测值":"未进行真实文物检测", "报告 / 来源":"测试报告"},
                    "鉴别诊断与待核查假设": {"候选解释":"待核查的教学假设", "支持证据":"人工标注", "需要补充的检查":"现场复核"},
                    "随访与复查": {"观察记录人":"测试人员", "观察到的变化":"教学状态记录", "后续行动":"继续观察"},
                }
                for title, fields in clinical_fields.items():
                    page.locator(".structured-section summary").filter(has_text=title).click()
                    page.get_by_role("button", name="新增"+title, exact=True).click()
                    for label, text in fields.items():
                        page.get_by_label(f"{title} 1 · {label}", exact=True).fill(text)
                page.locator(".structured-section summary").filter(has_text="材料筛选与现场小试").click()
                page.get_by_role("button", name="新增材料试验", exact=True).click()
                page.get_by_label("材料试验 1 · 材料类别", exact=True).fill("教学筛选材料")
                page.get_by_label("材料试验 1 · 方法 / 仪器", exact=True).fill("浏览器测试数值输入，非实际检测")
                page.get_by_label("材料试验 1 · pH", exact=True).fill("7")
                page.get_by_label("材料试验 1 · 报告出处", exact=True).fill("浏览器测试夹具，不用于材料认证")
                page.get_by_label("风险等级").select_option("medium")
                page.get_by_label("风险评估依据", exact=True).fill("教学风险记录，需专业复核")
                updated = request(lambda: page.get_by_role("button", name="保存病历与诊断").click(), "PUT", f"/records/{record_id}")
                clinical = updated["clinical_data"]
                assert all(len(clinical[key]) == 1 for key in ("previous_treatments","examinations","differential_diagnoses","followups","material_tests"))
                assert clinical["material_tests"][0]["values"] == {"ph":7}
                assert clinical["risk"]["level"] == "medium" and clinical["risk"]["assessed_by"]
                page.reload()
                try:
                    expect(page.get_by_label("既往处置 1 · 处置方法", exact=True)).to_have_value("教学历史处置记录")
                except Exception:
                    print("RELOAD PAGE", page.url, page.locator("body").inner_text()[-10000:])
                    print("PAGE ERRORS", errors)
                    screenshot("failure-clinical-reload")
                    raise
                expect(page.get_by_label("材料试验 1 · 色差 ΔE", exact=True)).to_have_value("")
                screenshot("08-clinical-structured")
                checks.append("Clinical history, examinations, differentials, follow-ups, scoped material tests and manual risk persist; unmeasured test values remain absent")

                page.goto(BASE + "/#cases")
                page.get_by_role("button",name="录入保护病例",exact=True).click()
                case_fields={"病例名称":"浏览器验收 · 授权教学病例", "材质 / 地仗与颜料":"教学泥地仗", "原始发布机构":"项目教学测试", "原始资料链接":"https://example.org/ahr-browser-fixture", "病害与诊断依据":"测试诊断依据，不代表真实文物项目", "保护工艺与历史方案":"教学工序，原始文物方案未知", "效果、失败及持续观察":"仅验证资料录入，无真实效果结论", "来源许可与使用边界":"项目原创测试图，仅供教学验收；非真实文物"}
                for label,text in case_fields.items():page.get_by_label(label,exact=True).fill(text)
                page.get_by_label("起甲",exact=True).check()
                page.get_by_label("病例完整程度").select_option("complete")
                private_case=request(lambda:page.get_by_role("button",name="创建病例",exact=True).click(),"POST","/cases")
                case_id=private_case["id"]
                assert private_case["editable"] and private_case["completeness"]=="complete"
                card=page.locator(".case-card").filter(has=page.get_by_role("heading",name="浏览器验收 · 授权教学病例",exact=True))
                card.get_by_role("button",name="查看病例详情",exact=True).click()
                uploaded_case=request(lambda:page.get_by_label("病例影像文件").set_input_files(str(fixture)),"POST",f"/cases/{case_id}/images")
                assert len(uploaded_case["images"])==1
                expect(page.locator(".case-image-grid img")).to_have_count(1)
                page.get_by_role("button",name="关闭",exact=True).click()
                card.get_by_role("button",name="编辑病例",exact=True).click()
                page.get_by_label("专家意见 / 评议记录",exact=True).fill("教学评议：字段完整不等于专业验收")
                revised_case=request(lambda:page.get_by_role("button",name="保存病例修订",exact=True).click(),"PUT",f"/cases/{case_id}")
                assert revised_case["version"]==uploaded_case["version"]+1 and len(revised_case["images"])==1
                page.get_by_label("病例地区筛选").fill("甘肃")
                page.get_by_label("病例材质筛选").fill("教学泥地仗")
                page.get_by_role("button",name="检索病例",exact=True).click()
                expect(page.locator(".case-card")).to_have_count(1)
                screenshot("09-case-library")
                checks.append("Private structured case creation, version-safe edit, permissioned image upload and region/material filtering; image survives revision")

                page.goto(BASE+f"/#records/{record_id}?tab=evidence")
                page.get_by_label("病例材质筛选").fill("教学泥地仗")
                page.get_by_label("同时使用所选影像检索",exact=True).check()
                searched=request(lambda:page.get_by_role("button",name="检索病例",exact=True).click(),"GET","/similar-cases?")
                assert any(item["id"]==case_id for item in searched["items"])
                page.locator(".case-card").filter(has=page.get_by_role("heading",name="浏览器验收 · 授权教学病例",exact=True)).get_by_role("button",name="选为方案依据",exact=True).click()
                selected=request(lambda:page.get_by_role("button",name="保存所选病例（1）",exact=True).click(),"PUT","/evidence")
                assert case_id in selected["evidence_ids"]
                assert any(source["id"]==case_id for source in selected["evidence_sources"])
                checks.append("Filtered optional-image case retrieval reports real method; selected case saved as versioned plan evidence")

                page.get_by_role("button", name="修复方案", exact=True).click()
                generated = request(lambda: page.get_by_role("button", name="生成方案草案", exact=True).click(), "POST", "/plans")
                assert generated["provider"] == "template_fallback"
                assert any(source["id"]==case_id for source in generated["evidence_snapshot"])
                expect(page.locator(".chapter-nav button")).to_have_count(13)
                page.get_by_role("button", name="修订方案").click()
                body = page.get_by_label("章节正文")
                body.fill(body.input_value() + "\n浏览器验收补充：保留教学资料出处。")
                edited = request(lambda: page.get_by_role("button", name="保存新版本").click(), "PUT", "/plans/")
                assert edited["version"] == generated["version"] + 1
                page.get_by_role("button", name="版本对比", exact=True).click()
                expect(page.locator(".diff-row")).to_have_count(1)
                page.get_by_role("button", name="关闭对比").click()
                page.locator(".chapter-nav button").filter(has_text="保护修复技术路线及工艺措施").click()
                expect(page.get_by_role("heading",name="有序工序与前置条件",exact=True)).to_be_visible()
                page.get_by_role("button",name="修订方案",exact=True).click()
                page.get_by_label("上移工序2",exact=True).click()
                bad_order=request(lambda:page.get_by_role("button",name="保存新版本",exact=True).click(),"PUT","/plans/")
                order_check=request(lambda:page.get_by_role("button",name="运行检查",exact=True).click(),"POST","/check")
                assert any(item["rule_id"]=="R-ORDER-001" and item["result"]=="block" for item in order_check["items"])
                page.get_by_role("button",name="版本对比",exact=True).click()
                expect(page.locator(".diff-row")).to_have_count(1)
                expect(page.locator(".diff-row")).to_contain_text("工序、预算、引用及不确定性差异")
                page.get_by_role("button",name="关闭对比").click()
                page.locator(".chapter-nav button").filter(has_text="保护修复技术路线及工艺措施").click()
                page.get_by_role("button",name="修订方案",exact=True).click()
                page.get_by_label("上移工序2",exact=True).click()
                page.locator(".chapter-nav button").filter(has_text="经费预算").click()
                page.get_by_role("button",name="新增预算项",exact=True).click()
                for label,value in {"项目":"教学计量", "数量":"2", "单位":"项", "单价":"10", "合计":"20", "依据":"纯测试金额，非文保工程报价"}.items():page.get_by_label(f"预算1 · {label}",exact=True).fill(value)
                request(lambda:page.get_by_role("button",name="保存新版本",exact=True).click(),"PUT","/plans/")
                checked = request(lambda: page.get_by_role("button", name="运行检查").click(), "POST", "/check")
                assert checked["overall"] != "block", checked
                assert any(item["rule_id"]=="R-BUD-STRUCTURED" and item["result"]=="pass" for item in checked["items"])
                assert any(item.get("scope")=="flaking_adhesive_test" and item.get("measured_value")==7 for item in checked["items"])
                checks.append("Measures reorder affects version diff and blocks invalid dependencies; scoped measured material clauses and explicit budget arithmetic checked")
                submitted = request(lambda: page.get_by_role("button", name="提交专家审核").click(), "POST", "/submit")
                assert submitted["status"] == "review"
                screenshot("03-plan-desktop")
                checks.append("13-section template provenance; immutable revision; real version diff; rule checks and submission")

                page.get_by_role("button", name="模拟与对比", exact=True).click()
                page.get_by_role("button", name="生成带水印模拟").click()
                expect(page.locator(".image-comparison")).to_be_visible(timeout=30000)
                expect(page.locator(".comparison-divider")).to_be_visible()
                expected_image=page.get_by_label("选择原始影像",exact=True).input_value()
                page.get_by_label("在原图上查看不确定区域",exact=True).check()
                expect(page.get_by_alt_text("模拟不确定区域",exact=True)).to_be_visible()
                screenshot("04-simulation-desktop")
                page.reload()
                page.get_by_label("选择原始影像",exact=True).select_option(second_image["id"])
                page.locator(".simulation-card").first.click()
                expect(page.get_by_label("选择原始影像",exact=True)).to_have_value(expected_image)
                page.get_by_label("在原图上查看不确定区域",exact=True).check()
                expect(page.get_by_alt_text("模拟不确定区域",exact=True)).to_be_visible()
                page.get_by_label("复查 / 对比影像",exact=True).select_option(second_image["id"])
                page.get_by_role("button",name="运行影像对比",exact=True).click()
                expect(page.get_by_text("影像已自动配准 · 需复核",exact=True)).to_be_visible(timeout=30000)
                page.reload()
                expect(page.locator(".simulation-card").filter(has_text="前后影像对比")).to_have_count(1)
                page.locator(".simulation-card").filter(has_text="前后影像对比").click()
                expect(page.get_by_text("影像已自动配准 · 需复核",exact=True)).to_be_visible()
                checks.append("Simulation retains uncertainty overlay and selects historical source image after reload; actual alignment comparison remains accessible in task history")

                page.get_by_role("button", name="切换身份 / 退出").click()
                login("expert")
                page.goto(BASE + f"/#records/{record_id}?tab=consultation")
                expect(page.get_by_label("审核人署名")).to_have_value("演示·会诊专家")
                page.get_by_label("审核意见", exact=True).fill("浏览器测试：仅审核教学流程，不构成真实文物修复意见。")
                reviewed = request(lambda: page.get_by_role("button", name="确认审核并记录署名").click(), "POST", "/review")
                assert reviewed["status"] == "approved"
                screenshot("05-review-desktop")
                checks.append("Separate expert identity, exact account-name signature, version-bound approval")

                page.get_by_role("button", name="档案归集", exact=True).click()
                for extension in ("JSON", "PDF", "ZIP"):
                    with page.expect_download() as downloaded:
                        page.get_by_role("button", name=f"导出 {extension}", exact=True).click()
                    path = Path(downloaded.value.path())
                    assert path.stat().st_size > 100
                checks.append("Authenticated JSON/PDF/ZIP exports through UI")

                expect(page.locator(".archive-section-status")).to_have_count(10)
                page.get_by_label("档案类别",exact=True).select_option("4.6")
                page.get_by_label("档案条目名称",exact=True).fill("浏览器验收 · 保护修复日志")
                page.get_by_label("档案内容与来源",exact=True).fill("教学过程记录，没有实施真实文物修复。")
                archived=request(lambda:page.get_by_role("button",name="保存档案条目",exact=True).click(),"POST","/archive-entries")
                archive_entry=next(entry for entry in archived["archive_entries"] if entry["title"]=="浏览器验收 · 保护修复日志")
                assert next(item for item in archived["archive_completeness"] if item["key"]=="4.6")["status"]=="present"
                attachment=Path(temporary)/"teaching-log.txt";attachment.write_text("原创教学日志，仅浏览器测试。",encoding="utf-8")
                attached=request(lambda:page.get_by_label("附件 浏览器验收 · 保护修复日志",exact=True).set_input_files(str(attachment)),"POST",f"/archive-entries/{archive_entry['id']}/file")
                assert next(entry for entry in attached["archive_entries"] if entry["id"]==archive_entry["id"])["sha256"]
                screenshot("10-archive-completeness")
                checks.append("Ten verified archive composition items, process-log entry, attachment checksum and actual completeness update")

                page.get_by_role("button",name="切换身份 / 退出",exact=True).click()
                login("restorer")
                page.goto(BASE+f"/#records/{record_id}?tab=record")
                page.get_by_label("资料敏感级别").select_option("sensitive")
                sensitive=request(lambda:page.get_by_role("button",name="保存病历与诊断",exact=True).click(),"PUT",f"/records/{record_id}")
                assert sensitive["artifact"]["sensitivity"]=="sensitive"
                denied=page.request.get(f"{BASE}/api/v1/records/{record_id}/archive.json")
                assert denied.status==403
                page.get_by_role("button",name="档案归集",exact=True).click()
                page.get_by_label("导出目的与使用范围",exact=True).fill("教学验收本地存档，限本次测试。")
                application=request(lambda:page.get_by_role("button",name=f"申请导出病历 v{sensitive['version']}",exact=True).click(),"POST","/export-requests")
                page.get_by_role("button",name="切换身份 / 退出",exact=True).click()
                login("admin")
                page.goto(BASE+f"/#records/{record_id}?tab=archive")
                page.get_by_label(f"审批意见 {application['id']}",exact=True).fill("批准当前版本教学测试导出，非真实项目审批。")
                reviewed_export=request(lambda:page.get_by_role("button",name="批准当前版本导出",exact=True).click(),"POST",f"/export-requests/{application['id']}/review")
                assert reviewed_export["status"]=="approved"
                screenshot("11-sensitive-export-review")
                page.get_by_role("button",name="切换身份 / 退出",exact=True).click()
                login("restorer")
                page.goto(BASE+f"/#records/{record_id}?tab=archive")
                with page.expect_download() as approved_download:page.get_by_role("button",name="导出 JSON",exact=True).click()
                exported=json.loads(Path(approved_download.value.path()).read_text())
                assert exported["clinical_data"]["risk"]["level"]=="medium"
                assert any(entry["id"]==archive_entry["id"] for entry in exported["archive_entries"])
                page.get_by_role("button",name="结构化病历",exact=True).click()
                page.get_by_label("现状主诉",exact=True).fill("导出审批后新版本教学记录")
                request(lambda:page.get_by_role("button",name="保存病历与诊断",exact=True).click(),"PUT",f"/records/{record_id}")
                assert page.request.get(f"{BASE}/api/v1/records/{record_id}/archive.json").status==403
                checks.append("Sensitive export is denied until admin approval; grant only authorizes requesting account/current version; changed record revokes applicability")
                dashboard=page.request.get(f"{BASE}/api/v1/dashboard").json()
                assert any(row["name"]=="medium" and row["count"]>=1 for row in dashboard["by_risk"])

                page.goto(BASE + "/#data")
                expect(page.get_by_role("heading", name="数据来源与缺口", exact=True)).to_be_visible()
                expect(page.locator(".loading")).to_have_count(0)
                catalog = page.request.get(BASE + "/api/v1/reference-images").json()
                assert catalog["image_count"] > 0, "Public reference images must be available in the source package"
                public_panel = page.locator(".panel").filter(has=page.get_by_role("heading", name="公开真实壁画参考图库", exact=True))
                expect(public_panel.locator(".provenance-image-card")).to_have_count(min(6, catalog["artifact_count"]))
                public_panel.get_by_role("button", name="查看全部影像", exact=True).first.click()
                expect(page.locator(".reference-full-image img").first).to_be_visible()
                page.get_by_role("button", name="关闭", exact=True).click()
                imported = request(lambda: public_panel.get_by_role("button", name="导入参考病历", exact=True).first.click(), "POST", "/import")
                assert imported["artifact"]["record_kind"] == "public_reference"
                assert imported["images"] and not imported["diseases"]
                assert all(i["provenance"]["source_type"] == "public_dataset" for i in imported["images"])
                expect(page.get_by_text("公开馆藏参考 · 非现场调查", exact=True)).to_be_visible()
                page.locator(".record-workflow > summary").click()
                expect(page.locator(".record-workflow li")).to_have_count(8)
                page.locator(".record-workflow > summary").click()
                screenshot("12-public-reference-import")
                checks.append("Real licensed museum photos displayed with sources; all object images import into explicit public-reference record with zero invented diagnoses")

                page.get_by_role("button", name="切换身份 / 退出", exact=True).click()
                login("expert")
                page.goto(BASE + f"/#records/{imported['id']}?tab=images")
                page.get_by_text("复核来源与授权证据", exact=True).click()
                page.get_by_label("影像来源复核意见", exact=True).fill("浏览器隔离验收：核对馆方对象来源和 CC0 许可；不确认病害、真值或现场试点。")
                source_review = request(lambda: page.get_by_role("button", name="确认来源与许可", exact=True).click(), "POST", "/provenance/review")
                assert source_review["provenance"]["review_status"] == "verified"
                assert source_review["provenance"]["recorded_by"] != source_review["provenance"]["reviewer_id"]
                readiness = page.request.get(BASE + "/api/v1/data/readiness").json()
                assert readiness["counts"]["verified_real_images"] >= 1
                assert readiness["counts"]["evaluation_ready_images"] == 0
                checks.append("Independent expert source/permission review persists; verified real photograph remains excluded from evaluation without evaluation permission")
                page.get_by_role("button", name="切换身份 / 退出", exact=True).click()
                login("restorer")
                page.goto(BASE + f"/#records/{imported['id']}?tab=images")

                page.get_by_role("button", name="多边形", exact=True).click()
                page.get_by_label("新标注病害类型", exact=True).select_option("裂隙")
                canvas = page.locator("svg[aria-label='原图病害多边形标注画布']")
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                for x, y in [(0.2, 0.2), (0.5, 0.2), (0.5, 0.4), (0.2, 0.4)]:
                    page.mouse.click(box["x"] + box["width"] * x, box["y"] + box["height"] * y)
                page.get_by_role("button", name="闭合区域", exact=True).click()
                page.get_by_role("button", name="绘制裂隙中心线", exact=True).click()
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                for x, y in [(0.25, 0.3), (0.35, 0.31), (0.45, 0.3)]:
                    page.mouse.click(box["x"] + box["width"] * x, box["y"] + box["height"] * y)
                page.get_by_role("button", name="完成中心线", exact=True).click()
                expect(page.get_by_role("button", name="补录 / 修改影像来源", exact=True)).to_be_disabled()
                crack = request(lambda: page.get_by_role("button", name="保存标注", exact=True).click(), "PUT", "/diseases")
                assert len(crack["diseases"][0]["centerline"]) == 3
                assert not crack["diseases"][0]["confirmed"]
                checks.append("Crack area polygon and independently drawn centerline both persist without asserting an expert diagnosis")

                page.get_by_role("button", name="开始 SAM 点选", exact=True).click()
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                page.mouse.click(box["x"] + box["width"] * .3, box["y"] + box["height"] * .3)
                sam_job = request(lambda: page.get_by_role("button", name="生成 SAM 区域候选", exact=True).click(), "POST", "/assist")
                assert sam_job["kind"] == "annotation_assistance"
                expect(page.get_by_text("未配置本地 SAM 预训练权重", exact=True)).to_be_visible(timeout=30000)
                checks.append("SAM foreground prompt uses original image coordinates and real asynchronous API; missing weights produce explicit unavailable state")

                def mock_sam(route):
                    candidate = {"polygon": [[10,10],[100,10],[100,100],[10,100]], "polygons": [[[10,10],[100,10],[100,100],[10,100]]], "holes": [], "confidence": .75, "area_pixels": 8100,
                                 "mask_data_url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aFZkAAAAASUVORK5CYII="}
                    complex_candidate = {**candidate, "holes": [[[20,20],[30,20],[30,30]]], "polygons": candidate["polygons"] * 2}
                    route.fulfill(json={"id":"ui-sam-fixture", "status":"completed", "result":{"status":"ok", "task_id":"ui-sam-fixture", "model_version":"ui-test-fixture-not-real-inference", "image_id":route.request.url.split("/images/")[1].split("/")[0], "source_record_version":route.request.post_data_json["expected_version"], "predictions":[candidate, complex_candidate], "limitations":["Deterministic UI fixture; not model accuracy evidence."]}})
                page.route("**/images/*/assist", mock_sam)
                page.get_by_role("button", name="生成 SAM 区域候选", exact=True).click()
                expect(page.get_by_label("SAM 候选区域", exact=True)).to_be_visible()
                page.get_by_label("SAM 候选区域", exact=True).select_option("1")
                page.get_by_label("人工选择候选病害类别", exact=True).select_option("裂隙")
                expect(page.get_by_role("button", name="采用为人工标注草稿", exact=True)).to_be_disabled()
                page.get_by_label("SAM 候选区域", exact=True).select_option("0")
                page.get_by_label("人工选择候选病害类别", exact=True).select_option("裂隙")
                page.get_by_role("button", name="采用为人工标注草稿", exact=True).click()
                adopted = request(lambda: page.get_by_role("button", name="保存标注", exact=True).click(), "PUT", "/diseases")
                assert len(adopted["diseases"]) == 2
                proposal = next(d for d in adopted["diseases"] if "ui-sam-fixture" in d["evidence"])
                assert proposal["source"] == "manual" and proposal["confidence"] is None and not proposal["confirmed"]
                page.unroute("**/images/*/assist", mock_sam)
                checks.append("Deterministic SAM UI fixture: compound/holey regions cannot be silently flattened; simple candidate adopted as unconfirmed manual label with task/model provenance")

                # Keep a real asynchronous request pending while changing the image.
                # Its late candidate fits both images, so server polygon bounds alone
                # could not prevent accidental cross-image adoption.
                alternate_response = page.request.post(BASE + f"/api/v1/records/{imported['id']}/images", multipart={
                    "file":{"name":"sam-switch-teaching.png", "mimeType":"image/png", "buffer":fixture.read_bytes()},
                    "provenance":json.dumps({"source_type":"synthetic", "source_title":"SAM stale-response browser fixture", "notes":"Original teaching image, not real museum data."})})
                assert alternate_response.ok
                alternate = alternate_response.json()
                page.reload()
                page.get_by_role("button", name="开始 SAM 点选", exact=True).click()
                canvas = page.locator("svg[aria-label='原图病害多边形标注画布']")
                canvas.scroll_into_view_if_needed()
                box = canvas.bounding_box()
                page.mouse.click(box["x"] + box["width"] * .3, box["y"] + box["height"] * .3)
                pending_routes = []
                def hold_sam(route): pending_routes.append(route)
                page.route("**/images/*/assist", hold_sam)
                with page.expect_request("**/images/*/assist"):
                    page.get_by_role("button", name="生成 SAM 区域候选", exact=True).click()
                page.locator(".image-thumb").filter(has_text=alternate["filename"]).click()
                assert pending_routes
                stale_route = pending_routes[0]
                with page.expect_response("**/images/*/assist"):
                    mock_sam(stale_route)
                page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
                expect(page.locator(".sam-result")).to_have_count(0)
                expect(page.get_by_role("button", name="采用为人工标注草稿", exact=True)).to_have_count(0)
                assert page.request.get(BASE + f"/api/v1/records/{imported['id']}").json()["diseases"] == adopted["diseases"]
                page.unroute("**/images/*/assist", hold_sam)
                checks.append("Delayed SAM response after image switch is discarded; no stale mask/adoption control appears and existing annotations remain unchanged")

                for target, heading in [("knowledge", "循证资料"), ("audit", "审计日志"), ("system", "运行状态"), ("data", "数据来源与缺口")]:
                    page.goto(BASE + "/#" + target)
                    expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
                    expect(page.locator(".loading")).to_have_count(0)
                checks.append("Knowledge, audit, and capability pages render real API responses")

                page.set_viewport_size({"width": 390, "height": 844})
                page.goto(BASE + "/#dashboard")
                expect(page.locator(".stat-card")).to_have_count(4)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                screenshot("06-dashboard-mobile")
                page.get_by_role("button", name="展开导航").click()
                expect(page.locator(".sidebar.open")).to_be_visible()
                checks.append("390px responsive dashboard and functional mobile navigation")
                page.goto(BASE + "/#data")
                expect(page.locator(".loading")).to_have_count(0)
                expect(page.get_by_role("heading", name="公开真实壁画参考图库", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                screenshot("13-reference-library-mobile")
                checks.append("390px real reference library and provenance ledger fit the viewport")
                assert not errors, errors
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=8)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
            log.close()
    report = {"passed": True, "checks": checks, "page_errors": errors,
              "screenshots": outputs, "data_scope": "isolated temporary DB; original teaching fixtures and licensed public museum references; explicitly mocked SAM UI responses including delayed-response isolation, not model accuracy evidence"}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
