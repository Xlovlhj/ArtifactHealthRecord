"""Traceable Chinese PDF reports and coordinate-preserving disease-map previews.

The six-class definition package supplies paper-millimetre symbol geometry.
Exported maps still require professional review and are not certified drawings.
PDF record exports contain original-image indexes; the archive ZIP carries the
image files. Generated simulations are deliberately excluded from this report.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
from html import escape
from typing import Any

from PIL import Image as PILImage, ImageOps
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from .catalog import DISEASES, PLAN_SECTIONS, symbol_package
from .knowledge import load_sources

FONT = "STSong-Light"
if FONT not in pdfmetrics.getRegisteredFontNames():
    pdfmetrics.registerFont(UnicodeCIDFont(FONT))

PALETTE = {row["type"]: row["color"] for row in DISEASES}
MAP_NOTICE = "按 GB/T 30237-2025 六类图示资料包绘制；线宽与间距以纸面毫米计。颜色辅助区分病害，虚线提示待确认。定义资料已核对，输出仍需专业审查；不是认证证明。"
AREA_NOTICE = "每个区域独立统计；不同区域或不同病害可能重叠，面积不可直接相加作为总受损面积。"
APPROVAL_NOTICE = "本文件为辅助记录或方案草稿。软件内部审核不等同法定签章、工程审批或施工许可。"
BODY = ParagraphStyle("AHRBody", fontName=FONT, fontSize=10, leading=16, wordWrap="CJK", spaceAfter=6)
TITLE = ParagraphStyle("AHRTitle", parent=BODY, fontSize=20, leading=28, textColor=colors.HexColor("#173d3b"), spaceAfter=12)
HEADING = ParagraphStyle("AHRHeading", parent=BODY, fontSize=13, leading=20, textColor=colors.HexColor("#173d3b"), spaceBefore=12, spaceAfter=6, keepWithNext=True)
SMALL = ParagraphStyle("AHRSmall", parent=BODY, fontSize=8, leading=12, textColor=colors.HexColor("#4f5d62"))
NOTICE = ParagraphStyle("AHRNotice", parent=BODY, fontSize=9, leading=14, borderColor=colors.HexColor("#cab981"), borderWidth=.5, borderPadding=6, backColor=colors.HexColor("#faf6e9"), spaceAfter=12)


def _text(value: Any) -> str:
    if value is None or value == "":
        return "未填写"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    value = str(value).replace("²", "^2").replace("·", " / ")
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)


def _safe(value: Any) -> str:
    return escape(_text(value), quote=True)


def _paras(value: Any, style=BODY) -> list:
    # Chunking prevents a single unbounded user field from creating an enormous
    # flowable; Paragraph itself paginates each chunk at Chinese word boundaries.
    value = _text(value)
    parts = []
    for line in value.splitlines() or [value]:
        for start in range(0, max(1, len(line)), 1200):
            parts.append(Paragraph(_safe(line[start:start + 1200]) if line else "&#160;", style))
    return parts


def _field(story: list, label: str, value: Any):
    story.extend(_paras(f"{label}：{_text(value)}"))


def _heading(story: list, title: str):
    story.append(Paragraph(_safe(title), HEADING))


def _finite(value: Any, default=None):
    try:
        value = float(value)
        return value if math.isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _number(value: Any, suffix="") -> str:
    number = _finite(value)
    return "未测算" if number is None else f"{number:,.3f}".rstrip("0").rstrip(".") + suffix


def _png(image: dict, data: bytes) -> tuple[bytes, int, int]:
    if image.get("image_type") in {"simulation", "generated"} or image.get("is_simulation"):
        raise ValueError("模拟影像不能作为正式病害图底图导出")
    with PILImage.open(io.BytesIO(data)) as original:
        if original.width * original.height > 40_000_000:
            raise ValueError("导出影像超过4000万像素限制")
        raster = ImageOps.exif_transpose(original).convert("RGB")
        width, height = raster.size
        if image.get("width") is not None and int(image["width"]) != width:
            raise ValueError("影像宽度与记录不一致，不能保持标注坐标")
        if image.get("height") is not None and int(image["height"]) != height:
            raise ValueError("影像高度与记录不一致，不能保持标注坐标")
        output = io.BytesIO()
        raster.save(output, format="PNG")
        return output.getvalue(), width, height


def _diseases(record: dict, image: dict | None = None) -> list[dict]:
    items = record.get("diseases", []) or []
    if image is not None:
        items = [row for row in items if str(row.get("image_id")) == str(image.get("id"))]
    return items


def _points(points: Any, width: int, height: int, minimum=3) -> list[tuple[float, float]]:
    if not isinstance(points, (list, tuple)) or len(points) < minimum:
        raise ValueError("标注顶点数量不足")
    result = []
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("标注坐标格式无效")
        x, y = _finite(point[0]), _finite(point[1])
        if x is None or y is None or not 0 <= x <= width or not 0 <= y <= height:
            raise ValueError("标注包含非有限值或超出原图范围的坐标")
        result.append((x, y))
    return result


def _area_description(row: dict) -> str:
    text = "像素面积 " + _number(row.get("area_px", row.get("area_pixels")), " px²")
    text += "；物理面积 " + _number(row.get("area_cm2"), " cm²")
    ratio = _finite(row.get("area_ratio"))
    if ratio is not None:
        text += "；占本影像 " + _number(ratio * 100, "%")
    return text


def _svg_lines(value: str, width=48) -> list[str]:
    # The SVG viewBox is scaled from an arbitrary source image; split text by
    # approximate visual columns rather than letting it overflow the image.
    lines, current, size = [], "", 0
    for character in _text(value):
        units = 1 if ord(character) < 128 else 2
        if current and size + units > width:
            lines.append(current)
            current, size = "", 0
        current += character
        size += units
    if current:
        lines.append(current)
    return lines or [""]


def disease_svg(record: dict, image: dict, image_bytes: bytes) -> str:
    from .symbols import symbol_geometry
    from .provenance import image_source_label
    png, width, height = _png(image, image_bytes)
    rows = _diseases(record, image)
    for row in rows:
        _points(row.get("polygon", []), width, height)
        if row.get("centerline"):_points(row["centerline"],width,height,minimum=2)
    # ViewBox units are physical paper millimetres, never source pixels.
    canvas_width, margin, header = 190., 6., 30.
    factor = min((canvas_width-2*margin)/width,145/height)
    image_width, image_height = width*factor, height*factor
    geometries=[symbol_geometry(row,factor) for row in rows]
    footer=[]
    for index,(row,geometry) in enumerate(zip(rows,geometries),1):
        label=f"{index}. {row.get('type')} / {'人工已确认' if row.get('confirmed') else '待确认'} / {_area_description(row)}"
        footer.extend(_svg_lines(label,100))
        footer.extend(geometry["warnings"])
    if not rows:footer.append("此影像尚无已保存标注。")
    for notice in (MAP_NOTICE,AREA_NOTICE,"按声明纸面尺寸打印；缩放打印会改变符号毫米尺寸。物理病害面积另依赖标尺。"):
        footer.extend(_svg_lines(notice,100))
    total=header+image_height+10+5*len(footer)
    package=symbol_package()
    metadata={"symbol_package":package["package_id"],"definition_source":package["source_url"],
              "units":"paper_mm","rendering_certified":False,"warnings":[w for g in geometries for w in g["warnings"]]}
    xml=[f'<svg xmlns="http://www.w3.org/2000/svg" width="190mm" height="{total:.4f}mm" viewBox="0 0 190 {total:.4f}">',
         '<title>文物病历 · 壁画病害图</title>',f'<metadata>{escape(json.dumps(metadata,ensure_ascii=False))}</metadata>',
         '<rect width="100%" height="100%" fill="#faf9f4"/>',
         '<g font-family="Noto Sans CJK SC,Microsoft YaHei,sans-serif" fill="#173d3b">',
         '<text x="6" y="9" font-size="5">文物病历 · 壁画病害图</text>']
    name=record.get("artifact",{}).get("name",record.get("name","未命名"))
    for index,line in enumerate(_svg_lines(f"{name}｜病历 {record.get('id')}｜版本 {record.get('version')}",100)[:2]):
        xml.append(f'<text x="6" y="{16+index*4}" font-size="3.1">{_safe(line)}</text>')
    xml.append(f'<text x="6" y="26" font-size="2.8">{_safe(image_source_label(image))} · 原图 {width} × {height} px</text>')
    xml.append(f'<g transform="translate({margin},{header})">')
    encoded=base64.b64encode(png).decode("ascii")
    xml.append(f'<image width="{image_width:.6f}" height="{image_height:.6f}" href="data:image/png;base64,{encoded}"/>')
    for index,(row,geometry) in enumerate(zip(rows,geometries),1):
        points=" ".join(f"{x:.6f},{y:.6f}" for x,y in geometry["polygon"])
        colour=PALETTE.get(row.get("type"),"#657774")
        xml.append(f'<defs><clipPath id="region-{index}"><polygon points="{points}"/></clipPath></defs>')
        xml.append(f'<polygon points="{points}" fill="{colour}" fill-opacity="0.10" stroke="none"/>')
        dash='' if row.get("confirmed") else ' stroke-dasharray="1.2 0.8"'
        if geometry["outline"]:
            xml.append(f'<polygon points="{points}" fill="none" stroke="#111" stroke-width="{geometry["stroke_width_mm"]}"{dash}/>')
        clip=f' clip-path="url(#region-{index})"' if geometry["clip"] else ''
        xml.append(f'<g data-symbol="{geometry["symbol_key"]}" stroke="#111" fill="none" stroke-width="{geometry["stroke_width_mm"]}"{clip}>')
        for path in geometry["paths"]:
            pairs=" ".join(f"{x:.6f},{y:.6f}" for x,y in path)
            xml.append(f'<polyline points="{pairs}"/>')
        xml.append('</g>')
        x,y=geometry["polygon"][0]
        xml.append(f'<text x="{x:.4f}" y="{max(3.,y):.4f}" font-size="3.3" fill="white" stroke="#173d3b" stroke-width="0.15" paint-order="stroke">{index}</text>')
    calibration=image.get("calibration") or {}
    if calibration.get("points"):
        points=_points(calibration["points"],width,height,minimum=2)
        if len(points)!=2:raise ValueError("尺度标定必须恰有两个端点")
        (x1,y1),(x2,y2)=points
        xml.append(f'<line x1="{x1*factor:.5f}" y1="{y1*factor:.5f}" x2="{x2*factor:.5f}" y2="{y2*factor:.5f}" stroke="#00b7d4" stroke-width="0.6"/>')
        xml.append(f'<text x="{x1*factor:.5f}" y="{max(3,y1*factor-1):.5f}" font-size="3.3" fill="#005369">{_safe(_number(calibration.get("length_cm")," cm"))}</text>')
    xml.append('</g>')
    for index,line in enumerate(footer):
        xml.append(f'<text x="6" y="{header+image_height+7+5*index:.4f}" font-size="2.8">{_safe(line)}</text>')
    xml.extend(['</g>','</svg>'])
    return "\n".join(xml)


def _build(story: list, title: str, record: dict) -> bytes:
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=44, bottomMargin=44,
                            title=_text(title), author="Artifact Health Record", pageCompression=1)

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont(FONT, 8)
        canvas.setFillColor(colors.HexColor("#526260"))
        label = "教学演示 / " if record.get("is_demo") else ""
        canvas.drawString(42, 25, label + "文物病历 / 内部辅助记录 / 不代替法定审批")
        canvas.drawRightString(A4[0]-42, 25, f"第 {document.page} 页")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def _cover(story: list, title: str, record: dict):
    story.append(Paragraph(_safe(title), TITLE))
    if record.get("is_demo"):
        story.append(Paragraph("教学演示病历；逐张影像真实性与来源见来源索引，不计入真实试点或修复成效。", NOTICE))
    if record.get("artifact",{}).get("record_kind")=="public_reference":
        story.append(Paragraph("公开馆藏参考记录；影像是真实馆藏照片，本记录不是本项目现场调查、修复病例或病害测试集。",NOTICE))
    story.append(Paragraph(_safe(APPROVAL_NOTICE), NOTICE))
    _field(story, "对象", record.get("artifact", {}).get("name", record.get("name")))
    _field(story, "病历编号／版本／状态", f"{_text(record.get('id'))} / {_text(record.get('version'))} / {_text(record.get('status'))}")


def _references(story: list, ids: list[str], evidence=None):
    _heading(story, "引用与来源")
    catalog = {str(row["id"]): row for row in [*load_sources(),*(evidence or [])]}
    if not ids:
        story.extend(_paras("本次导出未提供引用ID；证据不足，待补充。"))
    for id in dict.fromkeys(str(value) for value in ids):
        source = catalog.get(id)
        if not source:
            story.extend(_paras(f"[{id}] 未在本地资料库找到来源，不能视为有效引用。"))
            continue
        story.extend(_paras(f"[{id}] {source.get('title')}｜{source.get('publisher')}｜{source.get('standard', '')} {source.get('clause', '')}", SMALL))
        story.extend(_paras(source.get("source_url"), SMALL))
        story.extend(_paras("核验：" + str(source.get("verification_note", "未提供")), SMALL))


def _plan_contents(story: list, plan: dict):
    _field(story, "方案编号／版本／状态", f"{_text(plan.get('id'))} / {_text(plan.get('version'))} / {_text(plan.get('status'))}")
    _field(story, "绑定病历版本", plan.get("record_version"))
    _field(story, "生成方式／模型版本", f"{_text(plan.get('provider'))} / {_text(plan.get('model_version'))}")
    _field(story, "编制者／审核者／审核时间", f"{_text(plan.get('author'))} / {_text(plan.get('reviewer'))} / {_text(plan.get('signed_at'))}")
    sections = plan.get("sections") or {}
    ids = list(plan.get("citations") or [])
    for item in PLAN_SECTIONS:
        section = sections.get(item["key"]) or {}
        _heading(story, f"{item['key']} {item['title']}")
        story.extend(_paras(section.get("content", "证据不足，待编制人员补充。")))
        if section.get("uncertainty"):
            _field(story, "待确认项", section["uncertainty"])
        refs = section.get("citations") or []
        _field(story, "本节引用", "；".join(str(x) for x in refs) if refs else "无，需补充")
        ids.extend(refs)
        for index,measure in enumerate(section.get("measures",[]),1):
            _field(story,f"工序{index} · {measure['id']}",measure["name"])
            _field(story,"类型／前置工序",f"{measure['category']} / {', '.join(measure.get('prerequisites',[])) or '无'}")
            _field(story,"材料类别／风险／待确认",f"{measure.get('material_category','')} / {measure.get('risk','')} / {measure.get('uncertainty','')}")
            _field(story,"工序依据","；".join(measure.get("citations",[])))
            ids.extend(measure.get("citations",[]))
        for budget in section.get("budget_items",[]):
            _field(story,"预算分项",f"{budget['item']}：{budget['quantity']} {budget.get('unit','')} × {budget.get('unit_price')} 元，录入合计 {budget.get('total')} 元；依据：{budget.get('source','未填写')}")
    checks = plan.get("checks") or []
    if isinstance(checks, dict):
        checks = checks.get("items", [])
    if checks:
        _heading(story, "规则核对记录")
        for check in checks:
            story.extend(_paras(f"{check.get('rule_id', '')}｜{check.get('result', '')}｜{check.get('message', '')}"))
            if check.get("basis"):
                story.extend(_paras("依据：" + str(check["basis"]), SMALL))
    _references(story, ids,plan.get("evidence_snapshot",[]))


def plan_pdf(record: dict, plan: dict) -> bytes:
    record = plan.get("record_snapshot") or record
    story = []
    _cover(story, "壁画保护修复方案 · 辅助草稿", record)
    _plan_contents(story, plan)
    return _build(story, "文物病历保护修复方案", record)


def record_pdf(record: dict) -> bytes:
    story = []
    _cover(story, "文物病历 · 调查与保护档案", record)
    _heading(story, "基本信息与调查")
    artifact = record.get("artifact") or {}
    fields = {"type":"壁画类型", "era":"时代", "region":"地域", "location":"保存地点", "area_m2":"登记面积（m²）",
              "support_type":"支撑体", "ground_type":"地仗", "pigment_type":"颜料"}
    for key, label in fields.items():
        _field(story, label, artifact.get(key))
    survey = record.get("survey") or {}
    for key, label in {"date":"调查日期", "weather":"天气", "light":"照明", "equipment":"设备", "humidity":"记录相对湿度（%）", "water_leak":"是否记录渗水"}.items():
        _field(story, label, survey.get(key))
    _field(story, "主要观察", record.get("chief_complaint"))
    _field(story, "历史记录", record.get("history"))
    _heading(story, "诊断假设与待确认事项")
    diagnosis = record.get("diagnosis") or {}
    for key, label in {"hypothesis":"诊断假设", "evidence":"证据", "uncertainty":"不确定性"}.items():
        _field(story, label, diagnosis.get(key))
    clinical=record.get("clinical_data") or {}
    for key,label in [("previous_treatments","既往处置"),("examinations","检查检测"),("differential_diagnoses","鉴别诊断"),("material_tests","材料与现场试验"),("followups","随访与监测"),("risk","人工风险分级")]:
        _heading(story,label)
        rows=clinical.get(key,[])
        if isinstance(rows,dict):rows=[rows]
        if not rows:story.extend(_paras("尚未录入，不能作为已完成检查或处置。"))
        for row in rows:_field(story,"记录",row)
    _heading(story,"档案构成与缺项")
    for section in record.get("archive_completeness",[]):
        _field(story,section["key"]+" "+section["title"],f"{section['status']} / {section['count']} 项；录入不等于专业验收")
    for entry in record.get("archive_entries",[]):
        _heading(story,f"{entry['section']} · {entry['title']}")
        _field(story,"日期／记录人",f"{entry.get('date','')} / {entry.get('author','')}")
        story.extend(_paras(entry.get("text","")))
        _field(story,"附件／SHA256",f"{entry.get('filename') or '无'} / {entry.get('sha256') or '无'}")
    _heading(story, "病害标注清单")
    story.append(Paragraph(_safe(MAP_NOTICE + " " + AREA_NOTICE), NOTICE))
    for index, row in enumerate(_diseases(record), 1):
        _heading(story, f"{index}. {_text(row.get('type'))} · 影像 {_text(row.get('image_id'))}")
        _field(story, "状态／严重程度", f"{'人工已确认' if row.get('confirmed') else '待确认'} / {_text(row.get('severity'))}")
        _field(story, "面积", _area_description(row))
        _field(story, "影像观察依据", row.get("evidence"))
        _field(story, "现场核验依据", row.get("field_evidence"))
        _field(story, "来源／模型置信度", f"{_text(row.get('source'))} / {_text(row.get('confidence'))}")
        _field(story, "标准映射", row.get("standard_code"))
    _heading(story, "原始资料影像索引")
    story.extend(_paras("图像本体见归档ZIP中的原始资料文件。模拟图和其结果未纳入本PDF的正式影像索引。"))
    for image in record.get("images", []) or []:
        if image.get("image_type") not in {"original", "followup", "document"}:
            continue
        _field(story, "影像", f"{_text(image.get('id'))}｜{_text(image.get('filename'))}｜{_text(image.get('image_type'))}｜{_text(image.get('width'))}×{_text(image.get('height'))} px")
        from .provenance import image_source_label
        _field(story,"来源分类",image_source_label(image))
        _field(story,"逐图来源与许可",image.get("provenance",{}))
        _field(story, "尺度记录", image.get("calibration"))
        if image.get("sha256"):
            _field(story, "SHA-256", image["sha256"])
    _heading(story, "方案版本索引")
    for plan in record.get("plans", []) or []:
        _field(story, "方案", f"{_text(plan.get('id'))}｜版本 {_text(plan.get('version'))}｜{_text(plan.get('status'))}｜绑定病历版本 {_text(plan.get('record_version'))}")
    _heading(story, "会诊与内部审核记录")
    for item in record.get("consultations", []) or []:
        _field(story, "会诊", {key: item.get(key) for key in ("id", "created_at", "author", "reviewer", "decision", "comment", "plan_id") if key in item})
    _heading(story, "审计记录")
    for item in record.get("audit", []) or []:
        _field(story, "操作", item)
    _references(story, list(diagnosis.get("evidence", [])) if isinstance(diagnosis.get("evidence"), list) else [])
    return _build(story, "文物病历调查与保护档案", record)


class _MapDrawing(Flowable):
    def __init__(self, png: bytes, width: int, height: int, rows: list[dict], calibration: dict):
        Flowable.__init__(self)
        self.source_width, self.source_height = width, height
        self.factor = min((A4[0]-84)/width, 410/height)
        self.width, self.height = width*self.factor, height*self.factor
        self.png, self.rows, self.calibration = png, rows, calibration
        self.polygons = [_points(row.get("polygon", []), width, height) for row in rows]

    def draw(self):
        c = self.canv
        c.saveState()
        c.drawImage(ImageReader(io.BytesIO(self.png)), 0, 0, self.width, self.height)
        from .symbols import symbol_geometry
        pt_per_mm=72/25.4
        for index,(row,points) in enumerate(zip(self.rows,self.polygons),1):
            colour=colors.HexColor(PALETTE.get(row.get("type"),"#657774"))
            geometry=symbol_geometry(row,self.factor/pt_per_mm)
            path=c.beginPath()
            path.moveTo(points[0][0]*self.factor,self.height-points[0][1]*self.factor)
            for x,y in points[1:]:path.lineTo(x*self.factor,self.height-y*self.factor)
            path.close()
            c.saveState()
            c.setFillColor(colour);c.setFillAlpha(.10)
            c.drawPath(path,stroke=0,fill=1)
            c.restoreState()
            c.setStrokeColor(colors.HexColor("#111111"))
            c.setLineWidth(geometry["stroke_width_mm"]*pt_per_mm)
            c.setDash([] if row.get("confirmed") else [1.2*pt_per_mm,.8*pt_per_mm])
            if geometry["outline"]:c.drawPath(path,stroke=1,fill=0)
            c.saveState()
            c.setDash([])
            if geometry["clip"]:c.clipPath(path,stroke=0,fill=0)
            for points_mm in geometry["paths"]:
                mark=c.beginPath()
                mark.moveTo(points_mm[0][0]*pt_per_mm,self.height-points_mm[0][1]*pt_per_mm)
                for x,y in points_mm[1:]:mark.lineTo(x*pt_per_mm,self.height-y*pt_per_mm)
                c.drawPath(mark,stroke=1,fill=0)
            c.restoreState()
            c.setFont(FONT,9)
            label_x=min(self.width-15,points[0][0]*self.factor)
            label_y=min(self.height-12,max(2,self.height-points[0][1]*self.factor))
            label_width=pdfmetrics.stringWidth(str(index),FONT,9)+6
            c.setFillColor(colors.HexColor("#173d3b"))
            c.rect(label_x-2,label_y-2,label_width,13,stroke=0,fill=1)
            c.setFillColor(colors.white)
            c.drawString(label_x+1,label_y,str(index))
        if self.calibration.get("points"):
            points = _points(self.calibration["points"], self.source_width, self.source_height, minimum=2)
            if len(points) != 2:
                raise ValueError("尺度标定必须恰有两个端点")
            (x1,y1), (x2,y2) = points
            c.setStrokeColor(colors.HexColor("#00b7d4"))
            c.setFillColor(colors.HexColor("#005369"))
            c.setDash([])
            c.setLineWidth(2)
            c.line(x1*self.factor, self.height-y1*self.factor, x2*self.factor, self.height-y2*self.factor)
            c.setFont(FONT, 10)
            c.drawString(x1*self.factor, max(2,self.height-y1*self.factor+4), _number(self.calibration.get("length_cm"), " cm"))
        c.restoreState()


def map_pdf(record: dict, image: dict, image_bytes: bytes) -> bytes:
    png, width, height = _png(image, image_bytes)
    rows = _diseases(record, image)
    story = []
    _cover(story, "病害标注示意图", record)
    story.append(Paragraph(_safe(MAP_NOTICE), NOTICE))
    _field(story, "影像编号／文件／原图尺寸", f"{_text(image.get('id'))} / {_text(image.get('filename'))} / {width}×{height} px")
    drawing=_MapDrawing(png,width,height,rows,image.get("calibration") or {})
    story.append(drawing)
    from .symbols import symbol_geometry
    for row in rows:
        for warning in symbol_geometry(row,drawing.factor*25.4/72)["warnings"]:
            story.append(Paragraph(_safe(warning),NOTICE))
    story.append(Spacer(1, 10))
    story.extend(_paras("实线：人工已确认；虚线：待确认。蓝色线段：登记尺度。物理面积依赖局部平面标定，不能自动校正透视或曲面。", SMALL))
    story.extend(_paras(AREA_NOTICE, SMALL))
    _heading(story, "图例与面积")
    if not rows:
        story.extend(_paras("此影像尚无已保存标注。"))
    for index, row in enumerate(rows, 1):
        colour = PALETTE.get(row.get("type"), "#657774")
        story.append(Paragraph(f'<font color="{colour}">■</font> {_safe(str(index)+". "+str(row.get("type", "未分类")))}', BODY))
        story.extend(_paras(_area_description(row), SMALL))
        _field(story, "影像／现场证据", f"{_text(row.get('evidence'))} / {_text(row.get('field_evidence'))}")
    from .provenance import image_source_label
    _field(story,"影像来源",image_source_label(image))
    _field(story,"图示资料包",symbol_package()["package_id"])
    _field(story, "尺度标定", image.get("calibration"))
    return _build(story, "文物病历病害标注示意图", record)
