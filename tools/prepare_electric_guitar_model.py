"""List or download a verified UVR model whose advertised target is Guitar."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def guitar_models(separator) -> list[dict]:
    rows = []
    for architecture, models in separator.list_supported_model_files().items():
        for friendly_name, info in models.items():
            stems = [str(value) for value in info.get("stems", [])]
            target = str(info.get("target_stem") or "")
            searchable = " ".join([friendly_name, target, *stems]).casefold()
            if "guitar" not in searchable:
                continue
            is_dedicated_electric = "electric guitar" in searchable or "e.guitar" in searchable
            rows.append({
                "architecture": architecture,
                "friendly_name": friendly_name,
                "filename": info.get("filename"),
                "target_stem": target,
                "stems": stems,
                "scores": info.get("scores", {}),
                "dedicated_electric": is_dedicated_electric,
            })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--list-only", action="store_true")
    args = parser.parse_args()
    try:
        from audio_separator.separator import Separator
    except ImportError as exc:
        raise SystemExit("缺少 audio-separator，请先安装 requirements-server.txt") from exc
    model_dir = Path(args.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    separator = Separator(model_file_dir=str(model_dir), info_only=True)
    models = guitar_models(separator)
    print(json.dumps(models, ensure_ascii=False, indent=2))
    if args.list_only:
        return 0
    if not args.model:
        raise SystemExit(
            "未自动选择模型。请从上面的官方列表确认一个真正以 Guitar 为目标的二轨模型，"
            "然后重新执行并添加 --model 文件名。htdemucs_6s 只能产生合并 Guitar，不能冒充独立电吉他。"
        )
    match = next((item for item in models if item["filename"] == args.model), None)
    if not match:
        raise SystemExit(f"官方模型目录没有把 {args.model} 标记为 Guitar 模型，拒绝下载")
    if not match.get("dedicated_electric"):
        raise SystemExit(
            f"{args.model} 只标记为合并 Guitar，不能证明它能把木吉他与电吉他分开，拒绝启用。"
            "请只使用官方信息明确标注 Electric Guitar/E.Guitar 的模型。"
        )
    separator.load_model(model_filename=args.model)
    marker = model_dir / "electric-guitar-model.json"
    marker.write_text(json.dumps(match, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"模型已下载并记录：{marker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
