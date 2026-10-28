#!/usr/bin/env python3
"""Prepare a reviewable deployment bundle; optional local/container execution."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile

ROOT=Path(__file__).resolve().parent


def release_files(root=ROOT, include_frontend_build=True):
    """Select a reproducible public delivery without runtime or private datasets.

    The same selection is used for tar releases and the clean Git handoff.
    Public images belong in data/public with an auditable source manifest.
    """
    root=Path(root).resolve()
    directories={"backend","frontend","ai","scripts","tests","docs","deploy",".github"}
    excluded={".conda",".git","node_modules",".npm-cache","__pycache__",".pytest_cache","runtime"}
    if not include_frontend_build:
        excluded.add("dist")
    for path in sorted(root.rglob("*")):
        rel=path.relative_to(root)
        if set(rel.parts)&excluded:
            continue
        if path.is_symlink():
            raise ValueError(f"发布文件不能是符号链接: {rel}")
        if not path.is_file():
            continue
        if len(rel.parts)>1 and rel.parts[0] not in directories:
            if rel.parts[0]!="data" or len(rel.parts)<3 or rel.parts[1] not in {"knowledge","rules","public","templates"}:
                continue
        if path.name.startswith(".env") and path.name!=".env.example":
            continue
        if path.suffix.lower() in {".pyc",".db",".sqlite",".sqlite3",".pt",".pth",".safetensors",".pem",".key"}:
            continue
        yield path


def package():
    out=ROOT/"runtime/releases";out.mkdir(parents=True,exist_ok=True)
    target=out/"artifact-health-record-v1.0.tar.gz"
    files=list(release_files())
    with tarfile.open(target,"w:gz") as archive:
        for path in files:
            rel=path.relative_to(ROOT)
            archive.add(path,arcname=str(Path("ArtifactHealthRecord")/rel),recursive=False)
    manifest={"bundle":str(target),"bytes":target.stat().st_size,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"excludes":"secrets, runtime records, conda, node_modules, non-public datasets, model weights",
              "files":[{"path":str(path.relative_to(ROOT)),"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]}
    target.with_suffix(".manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(json.dumps({key:value for key,value in manifest.items() if key!="files"}|{"file_count":len(files)},ensure_ascii=False,indent=2))


def main():
    p=argparse.ArgumentParser(description="文物病历部署准备（不自动购买云资源）")
    p.add_argument("action",choices=["plan","package","up","down","status"])
    args=p.parse_args()
    if args.action=="plan":
        print(json.dumps({"deployment":"已有ECS或本机容器；公网前置HTTPS反向代理", "application":"FastAPI + React构建产物，conda环境", "database":"PostgreSQL 16；云端配置RDS连接", "redis":"相似病例检索缓存，失败回退直接检索", "obs":"私有桶影像存储；本地可用文件存储", "llm":"需配置兼容接口和显式数据发送授权", "model":"需独立提供真实数据训练并验证的六类权重", "commands":["python3 run.py doctor","python3 deploy.py package","python3 deploy.py up"], "external_actions_performed":False},ensure_ascii=False,indent=2))
    elif args.action=="package":package()
    else:
        action={"up":["up","-d","--build"],"down":["down"],"status":["ps"]}[args.action]
        subprocess.run(["docker","compose","--env-file",str(ROOT/".env"),"-f",str(ROOT/"deploy/compose.yml"),*action],cwd=ROOT,check=True)


if __name__=="__main__":main()

