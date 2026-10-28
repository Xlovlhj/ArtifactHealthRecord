"""图像采集预处理：python scripts/preprocess_images.py --help"""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.preprocessing import preprocess_images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+")
    parser.add_argument("--output", required=True, help="新的空输出目录")
    parser.add_argument("--options", help="JSON 配置；色卡坐标基于 EXIF 方向规范化后的原图")
    args = parser.parse_args()
    options = json.loads(Path(args.options).read_text(encoding="utf-8")) if args.options else {}
    print(json.dumps(preprocess_images(args.images, args.output, options), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
