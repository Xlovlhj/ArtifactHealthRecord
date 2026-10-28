"""Traceable local evidence retrieval; optional provider embeddings, explicit lexical fallback."""
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
import httpx
from .config import ROOT, settings


def load_sources():
    result = []
    for path in sorted((ROOT / "data/knowledge").glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        rows = value if isinstance(value, list) else value.get("items", value.get("sources", []))
        for row in rows:
            if isinstance(row, dict) and all(k in row for k in ("id", "title", "text", "source_url")):
                result.append(row)
    return list({r["id"]: r for r in result}.values())


def tokens(text):
    text = re.sub(r"\s+", "", text.lower())
    return re.findall(r"[a-z0-9]+", text) + [text[i:i+2] for i in range(len(text)-1)]


def search(query="", kind="", disease="", region="", limit=50):
    rows = load_sources()
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if disease:
        rows = [r for r in rows if disease in r.get("diseases", []) or disease in r["text"]]
    if region:
        rows = [r for r in rows if region in r.get("region", "") or region in r["text"]]
    return rank_rows(query,rows,limit)


def rank_rows(query,rows,limit=50,include_zero=False):
    if not query:
        return [{**r, "score": None, "match_reasons": []} for r in rows[:limit]]
    docs = [tokens(r["title"] + r["text"] + " ".join(r.get("tags", []))) for r in rows]
    avg = sum(map(len, docs)) / max(1, len(docs))
    query_tokens = set(tokens(query))
    freq = Counter(t for doc in docs for t in set(doc))
    scores = []
    for row, doc in zip(rows, docs):
        counts = Counter(doc)
        score = sum(math.log(1 + (len(rows)-freq[t]+0.5)/(freq[t]+0.5)) * counts[t] * 2.5 / (counts[t]+1.5*(0.25+0.75*len(doc)/max(avg,1))) for t in query_tokens if counts[t])
        scores.append({**row, "score": round(score, 4), "match_reasons": ["公开资料文本匹配；分数为排序分，非临床相似概率"]})
    return sorted((r for r in scores if include_zero or r["score"] > 0), key=lambda r: r["score"], reverse=True)[:limit]


def optional_vector_search(query, candidates):
    cfg = settings()
    if not (cfg.embedding_model and cfg.llm_base_url and cfg.llm_api_key):
        return candidates, "BM25 中文双字检索（离线基线）"
    texts = [query] + [r["title"] + "\n" + r["text"] for r in candidates]
    cache_key = hashlib.sha256(json.dumps([cfg.embedding_model, texts], ensure_ascii=False).encode()).hexdigest()
    cache_path = cfg.runtime / "embedding-cache" / f"{cache_key}.json"
    try:
        if cache_path.exists():
            vectors = json.loads(cache_path.read_text())
        else:
            with httpx.Client(timeout=25, trust_env=False) as client:
                response = client.post(cfg.llm_base_url.rstrip("/") + "/embeddings", headers={"Authorization": f"Bearer {cfg.llm_api_key}"}, json={"model": cfg.embedding_model, "input": texts})
                response.raise_for_status()
                data = sorted(response.json()["data"], key=lambda d: d["index"])
                vectors = [d["embedding"] for d in data]
                if len(vectors) != len(texts):
                    raise ValueError("embedding count mismatch")
                cache_path.parent.mkdir(exist_ok=True)
                cache_path.write_text(json.dumps(vectors))
        q = vectors[0]
        for row, vec in zip(candidates, vectors[1:]):
            den = math.sqrt(sum(x*x for x in q)*sum(x*x for x in vec))
            row["score"] = round(sum(a*b for a,b in zip(q,vec))/den, 5) if den else 0
            row["match_reasons"] = ["结构化候选筛选 + 向量余弦重排", "模型：" + cfg.embedding_model, "相关性分值尚未经专家标定"]
        return sorted(candidates, key=lambda r: r["score"], reverse=True), f"embedding:{cfg.embedding_model}"
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return candidates, "BM25 中文双字检索（embedding 服务失败后回退）"


def similar(record):
    from .cache import get_cache,set_cache
    diseases = {d["type"] for d in record.get("diseases", [])}
    artifact = record["artifact"]
    query = " ".join([artifact.get("region", ""), artifact.get("ground_type", ""), *diseases, record.get("chief_complaint", "")])
    cache_key=hashlib.sha256(json.dumps([query,load_sources(),settings().embedding_model,settings().allow_external_models],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    cached=get_cache(cache_key)
    if cached is not None:return {**cached,"cache_hit":True}
    results = search(query, kind="case", limit=30)
    # Prefer same region and disease using a transparent lexicographic ordering, not invented medical weights.
    results.sort(key=lambda r: (bool(diseases & set(r.get("diseases", []))), artifact.get("region", "") in r.get("region", ""), r["score"]), reverse=True)
    method = "BM25 + 病害/地域优先排序；公开案例摘要，非完整修复病历库"
    if settings().allow_external_models:
        results, vector_method = optional_vector_search(query, results)
        method += "; " + vector_method
    output={"items":results[:8],"method":method,"cache_hit":False}
    set_cache(cache_key,output)
    return output

