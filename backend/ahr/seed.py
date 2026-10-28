"""Original procedural teaching fixtures. Never represent these as surveyed artifacts."""
import hashlib
import io
import json
import math
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from .config import settings
from .db import *
from .security import hash_password
from .service import audit
from .storage import put
from .knowledge import load_sources
from .provenance import teaching_provenance


def teaching_image(index=0):
    im=Image.new("RGB",(1100,760),(219,201,168));d=ImageDraw.Draw(im)
    for x in range(0,1100,4):
        color=tuple(max(0,min(255,c+int(5*math.sin(x*.17)))) for c in (219,201,168))
        d.line((x,0,x,760),fill=color,width=2)
    d.rectangle((40,40,1060,720),outline="#875c43",width=14)
    d.rectangle((70,70,1030,690),outline="#b17c54",width=3)
    for x in range(100,1000,140):
        d.arc((x-20,70,x+100,190),180,360,fill="#7e362d",width=8)
        d.ellipse((x+20,116,x+50,146),fill="#447b78")
    # Geometric composition, not a replica of any protected mural image.
    d.ellipse((390,160,710,480),fill="#a85a3d",outline="#78503c",width=5)
    d.ellipse((420,190,680,450),fill="#d5ad6e",outline="#765e42",width=4)
    for j in range(12):
        angle=2*math.pi*j/12
        x,y=550+105*math.cos(angle),320+105*math.sin(angle)
        d.ellipse((x-24,y-24,x+24,y+24),fill="#467b75",outline="#314f4a",width=2)
    d.rectangle((180,530,920,610),fill="#ab674d")
    for x in range(195,900,45):d.polygon([(x,590),(x+20,540),(x+40,590)],fill="#e1bf7f")
    crack=[[270,210],[280,270],[266,332],[290,400],[277,468],[288,510]]
    d.line([tuple(p) for p in crack],fill="#483a30",width=8)
    loss=[[730,250],[828,236],[870,285],[837,350],[752,338],[710,300]]
    d.polygon(loss,fill="#b8a58d",outline="#715e49",width=3)
    d.rectangle((0,705,1100,760),fill="#f2eadb")
    font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font=ImageFont.truetype(font_path,18) if __import__('pathlib').Path(font_path).exists() else ImageFont.load_default()
    d.text((25,720),f"AHR TEACHING FIXTURE {index+1} | SYNTHETIC | NOT A REAL CULTURAL RELIC",fill="#743c32",font=font)
    buf=io.BytesIO();im.save(buf,format="PNG")
    return buf.getvalue(),loss


def initialize():
    cfg=settings()
    if cfg.env=="production" and cfg.demo_mode:
        raise RuntimeError("生产模式不能启用演示数据/默认账号，请设置AHR_DEMO_MODE=false")
    with SessionLocal() as db:
        if not db.scalar(select(User.id).limit(1)):
            password=cfg.bootstrap_password or ("ahr-demo-2026" if cfg.demo_mode else "")
            if not password or (not cfg.demo_mode and len(password)<12):
                raise RuntimeError("首次初始化非演示环境需设置至少12位AHR_BOOTSTRAP_PASSWORD")
            roles=[("surveyor","调查员"),("restorer","修复师"),("expert","会诊专家"),("manager","管理者"),("admin","系统管理员")] if cfg.demo_mode else [("admin","系统管理员")]
            for username,name in roles:
                db.add(User(username=username,name=("演示·" if cfg.demo_mode else "")+name,role=username,password_hash=hash_password(password),org="甘肃壁画保护演示组" if cfg.demo_mode else "本机构"))
            db.commit()
            if cfg.demo_mode:
                path=cfg.runtime/"demo-access.json"
                path.write_text(json.dumps({"mode":"local_demo","password":password,"users":[r[0] for r in roles]},ensure_ascii=False,indent=2))
                path.chmod(0o600)
        for source in load_sources():
            if source.get("kind")=="case" and not db.get(CaseReference,source["id"]):
                db.add(CaseReference(id=source["id"],source=source["source_url"],data=source))
        db.commit()
        # Add source metadata to old teaching fixtures without overwriting real uploads.
        for image in db.scalars(select(ImageAsset).where(ImageAsset.id.like("IMG-DEMO-%"))):
            if not image.provenance:
                image.provenance={**teaching_provenance(),"image_sha256":image.sha256}
        db.commit()
        if not cfg.demo_mode or db.scalar(select(Record.id).limit(1)):return
        user=db.scalar(select(User).where(User.username=="restorer"))
        for index,name in enumerate(["敦煌风格教学样板 · 局部病害记录","甘肃壁画教学样板 · 复查演练","石窟壁画教学样板 · 待调查"]):
            a=Artifact(id=f"ART-DEMO-{index+1:03}",org=user.org,is_demo=True,data={"name":name,"type":"石窟寺壁画","era":"教学图，无真实年代","region":"甘肃","location":"虚构教学场景，无真实文物位置","area_m2":None,"support_type":"教学样板","ground_type":"未检测","pigment_type":"程序绘制色彩，非真实颜料"})
            db.add(a);db.flush()
            s=Survey(artifact_id=a.id,data={"date":"2026-10-28","weather":"演示","light":"程序绘制","equipment":"Pillow教学图生成器","humidity":None,"water_leak":False})
            db.add(s);db.flush()
            r=Record(id=f"AHR-DEMO-{index+1:03}",artifact_id=a.id,survey_id=s.id,chief_complaint="演示影像标注、尺度计算及会诊工作流；不代表真实文物调查。",history="此图由项目程序原创绘制，无真实保护项目、专家或疗效记录。",diagnosis={"hypothesis":"教学样板中的模拟缺失与线状标记，供操作演练。","evidence":["项目原创教学图"],"uncertainty":"不能据此评估真实病害识别性能。"})
            db.add(r);db.flush()
            data,loss=teaching_image(index)
            key=f"images/{r.id}/demo.png";put(key,data,"image/png")
            put(f"raw/{r.id}/IMG-DEMO-{index+1:03}.original",data)
            image=ImageAsset(id=f"IMG-DEMO-{index+1:03}",artifact_id=a.id,record_id=r.id,filename="原创教学图.png",storage_key=key,sha256=hashlib.sha256(data).hexdigest(),width=1100,height=760,image_type="original",quality={},calibration={"points":[[100,650],[300,650]],"length_cm":20,"length_px":200,"cm_per_pixel":0.1,"assumption":"仅教学比例，非现场实测"})
            image.provenance={**teaching_provenance(),"image_sha256":image.sha256}
            db.add(image);db.flush()
            if index<2:
                from .geometry import validate_polygon
                polygon,area=validate_polygon(loss,1100,760)
                db.add(Disease(record_id=r.id,image_id=image.id,type="颜料层脱落",polygon=polygon,area_px=area,area_cm2=area*.01,area_ratio=area/(1100*760),severity="待确认",confidence=None,evidence="程序绘制的缺失色块，预置人工教学标注，非AI识别。",source="manual",confirmed=False))
            audit(db,user,"seed_teaching_fixture","record",r.id,r.id,after={"is_demo":True,"origin":"程序原创教学图；无真实诊断含义"})
        db.commit()

