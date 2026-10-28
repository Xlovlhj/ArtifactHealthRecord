#!/usr/bin/env python3
"""Single Python entry point; conda manages Python and Node. No shell launchers."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
PREFIX=ROOT/".conda"


def call(args,**kwargs):
    return subprocess.run([str(a) for a in args],check=True,**kwargs)


def environment():
    env=dict(os.environ)
    env["PATH"]=str(PREFIX/"bin")+os.pathsep+env.get("PATH","")
    env["PYTHONPATH"]=str(ROOT)+os.pathsep+env.get("PYTHONPATH","")
    return env


def setup(with_ai=False):
    conda=shutil.which("conda")
    if not conda:
        raise SystemExit("未找到conda。先安装Miniconda并让conda可用，再执行 python3 run.py setup。")
    if not (PREFIX/"conda-meta").is_dir():
        call([conda,"env","create","--prefix",PREFIX,"--file",ROOT/"environment.yml"],cwd=ROOT)
    else:
        call([PREFIX/"bin/python","-m","pip","install","-r",ROOT/"requirements.txt"],cwd=ROOT)
    if with_ai:
        call([PREFIX/"bin/python","-m","pip","install","-r",ROOT/"requirements-ai.txt"],cwd=ROOT)
    call([PREFIX/"bin/python","-m","pip","check"],cwd=ROOT)
    build()


def build():
    env=environment()
    npm=shutil.which("npm",path=env["PATH"])
    if not npm:raise SystemExit("当前conda环境缺少Node，请先运行 python3 run.py setup。")
    command="ci" if (ROOT/"frontend/package-lock.json").exists() else "install"
    call([npm,command,"--no-audit","--no-fund"],cwd=ROOT/"frontend",env=env)
    call([npm,"run","build"],cwd=ROOT/"frontend",env=env)


def doctor():
    from backend.ahr.config import settings
    cfg=settings()
    modules={name:bool(importlib.util.find_spec(name)) for name in ["fastapi","sqlalchemy","PIL","cv2","reportlab","torch","torchvision","segmentation_models_pytorch","transformers","obs"]}
    symbol_package=json.loads((ROOT/"data/knowledge/symbol_package_gbt30237_2025.json").read_text())
    def configured_directory(value):
        return {"configured":bool(value),"directory_present":bool(value and Path(value).is_dir()),
                "inference_verified":False}
    result={"python":sys.executable,"python_version":sys.version.split()[0],
            "conda_prefix":str(PREFIX),"conda_managed":(Path(sys.prefix)/"conda-meta").exists(),
            "dependencies":modules,"frontend_built":(ROOT/"frontend/dist/index.html").exists(),
            "database_backend":"PostgreSQL" if cfg.db_url.startswith("postgres") else "SQLite local",
            "llm_configured":bool(cfg.llm_base_url and cfg.llm_model and cfg.llm_api_key),
            "external_model_data_authorized":cfg.allow_external_models,
            "segmentation_checkpoint_present":bool(cfg.segmentation_checkpoint and Path(cfg.segmentation_checkpoint).is_file()),
            "sam":configured_directory(cfg.sam_model_dir),
            "visual_retrieval":{**configured_directory(cfg.retrieval_model_dir),"backend":cfg.retrieval_backend},
            "obs_configured":bool(cfg.obs_endpoint and cfg.obs_bucket and cfg.obs_access_key and cfg.obs_secret_key),
            "redis_configured":bool(cfg.redis_url),"demo_mode":cfg.demo_mode,
            "standard_symbol_source_verified":symbol_package.get("verified",False),
            "standard_rendering_certified":symbol_package.get("rendering_certified",False),
            "limitations":["文件与配置存在不等于真实推理、云端连接或专业验收通过",
                           "真实六类准确率需授权标注与独立测试；工程合成训练不计入",
                           "完整修复病例与机构试点尚待接入；公开参考图不等于现场病例",
                           "六类图符数据已记录来源核验；成图排版需专业验收"]}
    print(json.dumps(result,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description="文物病历：conda环境、启动、构建与验证")
    sub=parser.add_subparsers(dest="command")
    p=sub.add_parser("setup");p.add_argument("--with-ai",action="store_true")
    sub.add_parser("build")
    p=sub.add_parser("serve");p.add_argument("--host");p.add_argument("--port",type=int);p.add_argument("--reload",action="store_true")
    sub.add_parser("doctor")
    sub.add_parser("test")
    sub.add_parser("init")
    sub.add_parser("verify", help="离线检查交付文件、数据来源、公开样例哈希和环境完整性")
    p=sub.add_parser("script", help="使用项目Conda解释器执行scripts中的Python工具")
    p.add_argument("name")
    p.add_argument("arguments", nargs=argparse.REMAINDER)
    args=parser.parse_args();command=args.command or "serve"
    if command=="setup":setup(args.with_ai);return
    local_python=PREFIX/"bin/python"
    if local_python.exists() and Path(sys.prefix).resolve()!=PREFIX.resolve():
        os.execve(str(local_python),[str(local_python),str(Path(__file__).resolve()),*sys.argv[1:]],environment())
    os.chdir(ROOT)
    if command=="build":build()
    elif command=="doctor":doctor()
    elif command=="test":call([sys.executable,"-m","pytest","tests","-q"],env=environment())
    elif command=="verify":call([sys.executable,ROOT/"scripts/verify_delivery.py"],env=environment())
    elif command=="script":
        name=args.name if args.name.endswith(".py") else args.name+".py"
        path=(ROOT/"scripts"/name).resolve()
        if path.parent!=ROOT/"scripts" or not path.is_file():
            raise SystemExit("请指定scripts目录中实际存在的Python工具文件名。")
        call([sys.executable,path,*args.arguments],env=environment())
    elif command=="init":
        from backend.ahr.migrations import migrate
        from backend.ahr.seed import initialize
        migrate();initialize();print("数据库初始化及版本迁移完成。演示账号见 runtime/demo-access.json。")
    else:
        from backend.ahr.config import settings
        import uvicorn
        cfg=settings()
        host=getattr(args,"host",None) or cfg.host;port=getattr(args,"port",None) or cfg.port
        print(f"文物病历：http://{host}:{port}")
        if cfg.demo_mode:print("本地演示身份：surveyor / restorer / expert / manager / admin；首次密码见 runtime/demo-access.json。")
        uvicorn.run("backend.ahr.main:app",host=host,port=port,reload=getattr(args,"reload",False),log_level="info")


if __name__=="__main__":main()

