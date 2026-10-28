import json
from functools import lru_cache
from .config import settings


@lru_cache
def redis_client():
    if not settings().redis_url:return None
    import redis
    return redis.Redis.from_url(settings().redis_url,decode_responses=True,socket_timeout=2,socket_connect_timeout=2)


def get_cache(key):
    client=redis_client()
    if client is None:return None
    try:
        raw=client.get("ahr:retrieval:v1:"+key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def set_cache(key,value):
    client=redis_client()
    if client is None:return
    try:client.setex("ahr:retrieval:v1:"+key,900,json.dumps(value,ensure_ascii=False))
    except Exception:pass

