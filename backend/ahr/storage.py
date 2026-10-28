from pathlib import Path
import os
import tempfile
from urllib.parse import urlparse
from .config import settings


def local_path(key):
    base = (settings().runtime / "files").resolve()
    path = (base / key).resolve()
    if not path.is_relative_to(base):
        raise ValueError("非法存储路径")
    return path


def obs_client():
    from obs import ObsClient
    cfg = settings()
    if not (cfg.obs_endpoint and cfg.obs_bucket and cfg.obs_access_key and cfg.obs_secret_key):
        raise ValueError("OBS配置不完整")
    endpoint=urlparse(cfg.obs_endpoint)
    if endpoint.scheme!="https" or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError("OBS endpoint必须为HTTPS服务地址")
    return ObsClient(access_key_id=cfg.obs_access_key, secret_access_key=cfg.obs_secret_key,
                     server=cfg.obs_endpoint, region=cfg.obs_region, ssl_verify=True,
                     timeout=30, max_retry_count=2, trust_env=False)


def check_response(response):
    if response.status is None or not 200<=response.status<300:
        raise OSError(f"OBS操作失败，HTTP状态{response.status}")


def atomic_write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".ahr-",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as stream:stream.write(data)
        os.replace(temp,path)
    finally:
        Path(temp).unlink(missing_ok=True)


def put(key, data, content_type="application/octet-stream"):
    path = local_path(key)
    if settings().storage == "obs":
        from obs import PutObjectHeader
        client=obs_client()
        try:
            check_response(client.putContent(settings().obs_bucket,key,content=data,
                           headers=PutObjectHeader(contentType=content_type,acl="private")))
        finally:client.close()
    atomic_write(path,data)
    return key


def get_path(key):
    path = local_path(key)
    if not path.exists() and settings().storage == "obs":
        path.parent.mkdir(parents=True, exist_ok=True)
        fd,temp=tempfile.mkstemp(prefix=".ahr-",dir=path.parent)
        os.close(fd)
        client=None
        try:
            client=obs_client()
            response=client.getObject(settings().obs_bucket,key,downloadPath=temp)
            if response.status==404:raise FileNotFoundError(key)
            check_response(response)
            os.replace(temp,path)
        finally:
            if client is not None:client.close()
            Path(temp).unlink(missing_ok=True)
    if not path.exists(): raise FileNotFoundError(key)
    return path

