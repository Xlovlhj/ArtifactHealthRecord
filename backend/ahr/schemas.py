from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from urllib.parse import urlsplit


class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid",allow_inf_nan=False)


class ImageProvenance(StrictModel):
    """Uploader declarations. Review identities and status are server controlled."""
    source_type:Literal["unknown","field_capture","public_dataset","partner_archive","synthetic"]="unknown"
    source_title:str=Field(default="",max_length=1000)
    source_url:str=Field(default="",max_length=3000)
    creator:str=Field(default="",max_length=1000)
    license_name:str=Field(default="",max_length=1000)
    license_url:str=Field(default="",max_length=3000)
    rights_holder:str=Field(default="",max_length=1000)
    permission_evidence:str=Field(default="",max_length=5000)
    allowed_uses:list[Literal["internal_display","research","training","evaluation","redistribution"]]=Field(default_factory=list,max_length=5)
    captured_at:str=Field(default="",max_length=100)
    site_group:str=Field(default="",max_length=300)
    notes:str=Field(default="",max_length=5000)

    @field_validator("source_url","license_url")
    @classmethod
    def safe_http_url(cls,value):
        if value and (urlsplit(value).scheme not in {"http","https"} or not urlsplit(value).hostname):
            raise ValueError("来源与许可链接须为完整 HTTP/HTTPS 地址")
        return value

    @model_validator(mode="after")
    def reject_synthetic_evaluation(self):
        if self.source_type=="synthetic" and "evaluation" in self.allowed_uses:
            raise ValueError("合成教学影像不得声明为真实病害评测数据")
        self.allowed_uses=list(dict.fromkeys(self.allowed_uses))
        return self


class PreviousTreatment(StrictModel):
    date:str=""
    method:str=Field(default="",max_length=3000)
    materials:str=""
    operator:str=""
    outcome:str=""
    source:str=""


class Examination(StrictModel):
    date:str=""
    method:str=""
    location:str=""
    result:str=Field(default="",max_length=5000)
    unit:str=""
    source:str=""
    uncertainty:str=""


class Differential(StrictModel):
    hypothesis:str=""
    supporting_evidence:str=""
    opposing_evidence:str=""
    needed_checks:str=""


class Followup(StrictModel):
    date:str=""
    observer:str=""
    findings:str=""
    action:str=""
    next_date:str=""


class Risk(StrictModel):
    level:Literal["unassessed","low","medium","high","urgent"]="unassessed"
    reason:str=Field(default="",max_length=4000)
    assessed_by:str=""
    assessed_at:str=""


class ClinicalData(StrictModel):
    previous_treatments:list[PreviousTreatment]=Field(default_factory=list,max_length=100)
    examinations:list[Examination]=Field(default_factory=list,max_length=100)
    differential_diagnoses:list[Differential]=Field(default_factory=list,max_length=50)
    followups:list[Followup]=Field(default_factory=list,max_length=100)
    risk:Risk=Field(default_factory=Risk)
    material_tests:list["MaterialTest"]=Field(default_factory=list,max_length=100)


class MaterialTest(StrictModel):
    date:str=""
    material_category:str=""
    scope:Literal["flaking_adhesive_test","flaking_site_trial"]
    method:str=Field(default="",max_length=5000)
    values:dict[str,float|None]=Field(default_factory=dict)
    source:str=Field(default="",max_length=3000)


ClinicalData.model_rebuild()


class Measure(StrictModel):
    id:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=2000)
    category:Literal["environment","investigation","trial","body","monitoring"]
    prerequisites:list[str]=Field(default_factory=list,max_length=50)
    material_category:str=""
    citations:list[str]=Field(default_factory=list,max_length=30)
    risk:str=""
    uncertainty:str=""


class BudgetItem(StrictModel):
    item:str=Field(min_length=1,max_length=300)
    quantity:float=Field(ge=0)
    unit:str=""
    unit_price:float|None=Field(default=None,ge=0)
    total:float|None=Field(default=None,ge=0)
    source:str=""
