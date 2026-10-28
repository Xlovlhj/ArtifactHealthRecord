"""本地图像检索，候选清单使用 [{id,path,material,region,diseases,...}]。"""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.retrieval import search_images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True)
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--backend", choices=["dinov2", "clip", "chinese_clip"], default="dinov2")
    parser.add_argument("--filters", default="{}", help="JSON结构过滤；不混合未经验证的评分权重")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    source = Path(args.candidates)
    rows = json.loads(source.read_text(encoding="utf-8"))
    for row in rows:
        if row.get("path") or row.get("image_path"):
            row["path"] = str((source.parent / (row.get("path") or row["image_path"])).resolve())
    print(json.dumps(search_images(args.query, rows, args.model_dir, args.backend, json.loads(args.filters), args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
