"""E2–E6空采集表/真实观察统计：--init E4 --output ...，或 --input ... --output ...。"""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.evaluation import evaluate_study, study_template, inter_rater_dice


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init", choices=["E2", "E3", "E4", "E5", "E6"])
    group.add_argument("--input", help="已采集的实验JSON；不会自动填造专家分数")
    group.add_argument("--inter-rater", nargs="+", metavar="RATER=MASK_PNG")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.init:
        result = study_template(args.init)
    elif args.inter_rater:
        import numpy as np
        from PIL import Image
        masks = {}
        for item in args.inter_rater:
            name, path = item.split("=", 1)
            if name in masks:
                parser.error("标注者不能重复")
            with Image.open(path) as source:
                masks[name] = np.asarray(source).copy()
        result = inter_rater_dice(masks)
    else:
        result = evaluate_study(json.loads(Path(args.input).read_text(encoding="utf-8")))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "status": result.get("status", "written")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
