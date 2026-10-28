"""Image-level provenance and explicit-use accounting; never infer permission from visibility."""
from .schemas import ImageProvenance


REAL_SOURCE_TYPES = {"field_capture", "public_dataset", "partner_archive"}
SOURCE_LABELS = {"unknown":"来源待补录", "field_capture":"现场采集", "public_dataset":"公开馆藏/数据集参考影像",
                 "partner_archive":"合作单位档案", "synthetic":"合成教学影像"}


def normalized_provenance(value):
    return {**ImageProvenance().model_dump(), "review_status":"pending", **(value or {})}


def provenance_issues(value):
    p=normalized_provenance(value)
    missing=[]
    if p["source_type"]=="unknown":missing.append("未明确影像来源类别")
    if not p["source_title"].strip():missing.append("缺少具体来源名称")
    if p["source_type"]=="public_dataset" and not p["source_url"].strip():missing.append("公开影像缺少原始对象/数据集链接")
    if not p["license_name"].strip() and not p["permission_evidence"].strip():missing.append("缺少许可证或授权记录")
    if not p["license_url"].strip() and not p["permission_evidence"].strip():missing.append("缺少可追溯的许可依据")
    if not p["allowed_uses"]:missing.append("尚未声明获授权的使用范围")
    if p["source_type"] in {"field_capture","partner_archive"} and not p["rights_holder"].strip():missing.append("缺少影像权利人/合作单位")
    if p["source_type"]=="field_capture":
        if not p["creator"].strip():missing.append("现场影像缺少采集者")
        if not p["captured_at"].strip():missing.append("现场影像缺少采集日期")
    return missing


def permitted(value, purpose, *, real_only=False):
    p=normalized_provenance(value)
    return (p["review_status"]=="verified" and not provenance_issues(p)
            and purpose in p["allowed_uses"]
            and (not real_only or p["source_type"] in REAL_SOURCE_TYPES)
            and (purpose!="evaluation" or p["source_type"] in REAL_SOURCE_TYPES))


def image_source_label(image):
    p=normalized_provenance(image.get("provenance"))
    label=SOURCE_LABELS.get(p["source_type"],"来源待补录")
    return label+{"verified":"；来源资料已复核","rejected":"；来源资料复核未通过"}.get(p["review_status"],"；来源资料待复核")


def teaching_provenance():
    return {**ImageProvenance(source_type="synthetic",source_title="AHR 程序原创教学图",creator="ArtifactHealthRecord / Pillow",
            rights_holder="项目原创教学素材",license_name="项目原创素材",permission_evidence="backend/ahr/seed.py teaching_image 程序生成；不是实拍文物",
            allowed_uses=["internal_display","research","training","redistribution"],site_group="ahr-synthetic-teaching",
            notes="仅工作流演练或合成训练增强；不得用于真实病害测试集、现场调查或修复效果证据。").model_dump(),
            "review_status":"pending","recorded_by":"system:seed","recorded_by_name":"项目初始化程序"}
