"""Inspect/download the licensed MuralDH release, never scrape museum imagery."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

DATASET = "https://datadryad.org/api/v2/datasets/doi%3A10.5061%2Fdryad.bnzs7h4jd"
LANDING = "https://datadryad.org/dataset/doi:10.5061/dryad.bnzs7h4jd"
PINNED = {"version": 306952, "file_id": 3347581, "name": "MuralDH.zip", "size": 7738652652,
          "sha256": "e4afa5f06a68eff62481c8c52dc8d2d9e1c271dd7e145e022a4ee66a55d413de"}


def fetch_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "AHR/1.0 (research dataset provenance)"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)


def verify_archive(path):
    digest = hashlib.sha256()
    length = 0
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
            length += len(chunk)
    result = {"size": length, "sha256": digest.hexdigest()}
    if length != PINNED["size"] or result["sha256"] != PINNED["sha256"]:
        raise ValueError("数据包尺寸或 SHA256 与已核实的 Dryad 版本不一致；不可按该版本使用")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/external/muraldh")
    parser.add_argument("--download", action="store_true", help="下载完整 7.74GB 包；默认只核查元数据")
    parser.add_argument("--local-archive", help="核验用户从官方平台合法下载的数据包，不复制7.74GB文件")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report = {"source": LANDING, "paper": "https://doi.org/10.1038/s41597-024-03785-0",
              "provider": "中国矿业大学研究团队 / Dryad", "license": "CC0-1.0",
              "pinned_release": PINNED, "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "status": "metadata_only", "six_class_compatible": False,
              "notes": ["原数据病害类别不能自动等同于本项目六类，须核对标签并由专家映射/重标。",
                        "先核实原壁画/洞窟分组，再进行预训练；不按图片随机划分。",
                        "未取得的原图、标注、模型效果绝不以合成数据替代。",
                        "数据CC0不等于GitHub代码已获许可，本项目未复制其代码。"]}
    try:
        metadata = fetch_json(DATASET)
        files = fetch_json("https://datadryad.org/api/v2/versions/306952/files")
        report["remote"] = {"title": metadata.get("title"), "license": metadata.get("license"),
                            "publicationDate": metadata.get("publicationDate"), "files": files.get("_embedded", {})}
        if "CC0" not in str(metadata.get("license", "")):
            raise ValueError("远端许可发生变化，需要重新核实")
        candidates = files["_embedded"]["stash:files"]
        archive = next(row for row in candidates if row["path"] == PINNED["name"])
        if archive["digest"] != PINNED["sha256"] or archive["size"] != PINNED["size"]:
            raise ValueError("远端文件版本与固定版本不一致")
        if args.download:
            if shutil.disk_usage(output).free < PINNED["size"] + 1024**3:
                raise ValueError("磁盘剩余空间不足数据包大小加1GiB余量")
            request = urllib.request.Request("https://datadryad.org/downloads/file_stream/3347581",
                                             headers={"User-Agent": "AHR/1.0"})
            partial = output / "MuralDH.zip.part"
            with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as stream:
                downloaded = 0
                for chunk in iter(lambda: response.read(1024*1024), b""):
                    downloaded += len(chunk)
                    if downloaded > PINNED["size"]:
                        raise ValueError("下载内容超过预期文件长度，已停止")
                    stream.write(chunk)
            report["archive_verification"] = verify_archive(partial)
            partial.replace(output / "MuralDH.zip")
            report["status"] = "downloaded_verified_not_prepared"
    except (urllib.error.URLError, KeyError, ValueError, OSError) as exc:
        report["status"] = "network_or_access_blocked"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["next_step"] = "从官方页面完成必要登录/下载后，使用 --local-archive 核验；不绕过访问控制。"
    if args.local_archive:
        report["archive_verification"] = verify_archive(args.local_archive)
        report["local_archive"] = str(Path(args.local_archive).resolve())
        report["status"] = "local_archive_verified_not_prepared"
    (output / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "report": str(output / "provenance.json"),
                      "next_step": report.get("next_step")}, ensure_ascii=False))
    if report["status"] == "network_or_access_blocked":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
