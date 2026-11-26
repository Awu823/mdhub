"""pipeline: chain conversions.

E.g. `mdhub pipe in.docx --to md,docx`:
  1. to-md      in.docx -> _pipe/in.md
  2. md-to-docx _pipe/in.md -> output/in.docx
Intermediate artifacts live under output/_pipe/.
"""
from __future__ import annotations

import sys
from pathlib import Path

from mdkit import common
import mdkit.modules.to_md as tomd_mod
import mdkit.modules.md_to_docx as docx_mod
import mdkit.modules.md_to_html as html_mod
import mdkit.modules.md_to_pdf as pdf_mod
import mdkit.modules.md_to_pptx as pptx_mod

# Map a target format -> (module, input extension accepted)
_TARGETS = {
    "md": (tomd_mod, ".md"),
    "docx": (docx_mod, ".docx"),
    "html": (html_mod, ".html"),
    "pdf": (pdf_mod, ".pdf"),
    "pptx": (pptx_mod, ".pptx"),
}


def add_subparser(sp):
    sp.add_argument("input", help="起始输入（可为任意格式）")
    sp.add_argument("--to", required=True,
                    help="目标格式链，逗号分隔（如 md,docx 或 html,pdf）")
    sp.add_argument("--keep", action="store_true", help="保留中间产物")
    common.add_output_args(sp)


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    out_dir = project_root / (global_cfg.get("output_dir") or "output")
    pipe_dir = out_dir / "_pipe"
    pipe_dir.mkdir(parents=True, exist_ok=True)

    current = Path(args.input)
    if not current.is_absolute():
        current = common.resolve_input(project_root, args.input)
    if not current.exists():
        print(f"错误：找不到输入 {current}", file=sys.stderr)
        return 1

    chain = [f.strip() for f in args.to.split(",") if f.strip()]
    unknown = [f for f in chain if f not in _TARGETS]
    if unknown:
        print(f"错误：未知目标 {unknown}（可选：{', '.join(_TARGETS)}）", file=sys.stderr)
        return 1

    prev = current
    for i, target in enumerate(chain):
        mod, ext = _TARGETS[target]
        # output for this step
        if i == len(chain) - 1:
            out_path = out_dir / (current.stem + ext)
        else:
            out_path = pipe_dir / (f"{current.stem}_step{i}{ext}")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        sub = common.make_subargs(
            project_root,
            md=str(prev),
            input=str(prev),
            output=str(out_path),
            theme="midnight",
        )
        try:
            rc = mod.run(sub)
        except SystemExit as e:
            if not (args.quiet or args.json):
                print(f"[step {i+1} -> {target}] 失败：{e}", file=sys.stderr)
            return 1
        if rc != 0:
            if not (args.quiet or args.json):
                print(f"[step {i+1} -> {target}] 失败（rc={rc}）", file=sys.stderr)
            return 1
        if not (args.quiet or args.json):
            print(f"step {i+1}: {prev.name} -> {target}  完成")
        prev = out_path

    if not args.keep:
        for f in pipe_dir.iterdir():
            f.unlink()
    if args.json:
        import json as _json
        print(_json.dumps({"ok": True, "chain": chain,
                           "output": str(prev)}, ensure_ascii=False))
    elif not args.quiet:
        print(f"\n最终产物: {prev}")
    return 0
