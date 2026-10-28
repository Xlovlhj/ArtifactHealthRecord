"""Version-bound local SAM proposals, kept separate from disease diagnosis."""
from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from .config import settings
from .db import ImageAsset, User, get_db
from .security import current_user, require_role
from .service import assert_version
from .storage import get_path

router = APIRouter(prefix="/api/v1")


class AssistanceInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_version: int = Field(ge=1)
    points: list[tuple[float, float]] = Field(default_factory=list, max_length=100)
    point_labels: list[Literal[0, 1]] | None = Field(default=None, max_length=100)
    box: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def validate_prompts(self):
        if not self.points and self.box is None:
            raise ValueError("请先点击前景/背景点或框选区域")
        if self.point_labels is not None and len(self.point_labels) != len(self.points):
            raise ValueError("点标签与点数量必须一致")
        return self


def assistance_worker(db, job, image_id, prompts, source_version, original_sha, normalized_sha):
    from ai.assistance import assist_annotation
    image = db.get(ImageAsset, image_id)
    if image is None or image.sha256 != original_sha:
        raise ValueError("原始影像记录与提交任务时不一致")
    path = get_path(image.storage_key)
    if hashlib.sha256(path.read_bytes()).hexdigest() != normalized_sha:
        raise ValueError("显示影像内容与提交任务时不一致")
    result = assist_annotation(path, **prompts, model_dir=settings().sam_model_dir or None)
    result.update(image_id=image_id, source_record_version=source_version,
                  source_image_sha256=original_sha, normalized_image_sha256=normalized_sha,
                  prompts=prompts, method="sam_prompt_proposals", task_id=job.id,
                  disease_diagnosis=False, adoption_source="manual",
                  adoption_note="操作者核对所有连通区域及孔洞、选择病害类别；保存为人工标注并引用任务ID。")
    return result


@router.post("/images/{image_id}/assist")
def assist(image_id: str, body: AssistanceInput, background: BackgroundTasks,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    from .main import authorized_image, enqueue
    require_role(user, "surveyor", "restorer", "expert", "admin")
    image, record = authorized_image(db, image_id, user, True)
    assert_version(record, body.expected_version)
    if any(not (0 <= x < image.width and 0 <= y < image.height) for x, y in body.points):
        raise HTTPException(422, "SAM点击坐标超出原图")
    if body.box is not None:
        x0, y0, x1, y1 = body.box
        if not (0 <= x0 < x1 < image.width and 0 <= y0 < y1 < image.height):
            raise HTTPException(422, "SAM矩形必须位于原图内且具有正面积")
    prompts = {"points": [list(point) for point in body.points],
               "point_labels": body.point_labels if body.point_labels is not None else [1] * len(body.points),
               "box": list(body.box) if body.box is not None else None}
    normalized_sha = hashlib.sha256(get_path(image.storage_key).read_bytes()).hexdigest()
    return enqueue(db, user, record, "annotation_assistance", background, assistance_worker,
                   image.id, prompts, record.version, image.sha256, normalized_sha)
