"""md_to_multi: export to several formats in one go.

Composes the other modules (no new conversion logic):
  docx -> md_to_docx.run
  html -> md_to_html.run
  pdf  -> md_to_pdf.run
  pptx -> md_to_pptx.run
"""
from __future__ import annotations

import sys
from pathlib import Path

from mdkit import common
import mdkit.modules.md_to_docx as docx_mod
import mdkit.modules.md_to_html as html_mod
import mdkit.modules.md_to_pdf as pdf_mod
import mdkit.modules.md_to_pptx as pptx_mod

FORMATS = ("docx", "html", "pdf", "pptx")
_DISPATCH = {"docx": docx_mod, "html": html_mod, "pdf": pdf_mod, "pptx": pptx_mod}


def add_subparser(sp):
    sp.add_argument("md", nargs="?", help="输入 .md")
    sp.add_argument("--to", required=True, help="逗号分隔的格式列表（docx,html,pdf,pptx）")
    sp.add_argument("-o", "--output", help="输出目录（默认 output/）")
    sp.add_argument("-t", "--theme", default="midnight", help="HTML 主题")
    common.add_output_args(sp)


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    if args.md is None:
        print("错误：未提供输入 .md", file=sys.stderr)
        return 1
    md_path = str(common.resolve_input(project_root, args.md))

    wanted = [f.strip() for f in args.to.split(",") if f.strip()]
    unknown = [f for f in wanted if f not in FORMATS]
    if unknown:
        print(f"错误：未知格式 {unknown}（可选：{', '.join(FORMATS)}）", file=sys.stderr)
        return 1

    if args.output:
        out_dir = Path(args.output)
    else:
        out_dir = project_root / (global_cfg.get("output_dir") or "output")
    out_dir.mkdir(parents=True, exist_ok=True)

    ok, fail = [], []
    for fmt in wanted:
        mod = _DISPATCH[fmt]
        # Build a complete synthetic args namespace so each module's run()
        # finds every attribute it reads.
        sub = common.make_subargs(
            project_root,
            md=args.md,
            output=str(out_dir / (Path(md_path).stem + "." + fmt)),
            theme=args.theme,
        )
        try:
            rc = mod.run(sub)
            (ok if rc == 0 else fail).append(fmt)
        except SystemExit as e:
            fail.append(fmt)
            if not (args.quiet or args.json):
                print(f"[{fmt}] 失败：{e}", file=sys.stderr)

    if args.json:
        import json as _json
        print(_json.dumps({"ok": not fail, "formats": wanted,
                           "ok_formats": ok, "failed_formats": fail,
                           "output_dir": str(out_dir)}, ensure_ascii=False))
    elif not args.quiet:
        print(f"\n完成：{ok} 失败：{fail or '无'}")
    return 0 if not fail else 1
