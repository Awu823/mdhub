"""md_to_pdf: Markdown -> PDF.

Backends (auto-selected; `--engine` forces one):
  * xelatex (default when available) — uses the Eisvogel LaTeX template if found
  * typst    (fallback)              — lightweight, fast, no LaTeX needed

Pre-processing: strips Google-Docs-style TOC entries ("[1.](#_heading=1) Title")
which would otherwise produce dangling `#link(label("_heading=N"))` references
that make the typst engine fail with "label does not exist".
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from mdkit import common

# Google-Docs TOC line: [1.](#_heading=1) Title, [3.1](#_heading=4) Title, ...
_TOC_LINE = re.compile(r'(?m)^[ \t]*\[\d+(?:\.\d+)*\.?\]\(#_heading[^\n]*\n?')


def add_subparser(sp):
    sp.add_argument("md", nargs="?", help="输入 .md")
    sp.add_argument("-o", "--output", help="输出 .pdf 路径")
    sp.add_argument("--engine", choices=("auto", "xelatex", "pdflatex", "typst"), default="auto")
    sp.add_argument("--template", help="可选 LaTeX 模板（xelatex 引擎时；缺省用 pandoc 默认模板，"
                                       "可放 assets/pandoc/eisvogel.tex）")
    sp.add_argument("--keep-md", action="store_true", help="保留预处理后的中间 .md")


def _strip_toc(md_path: Path, workdir: Path) -> Path:
    """Return a preprocessed .md with Google-Docs TOC links removed."""
    text = md_path.read_text(encoding="utf-8")
    stripped = _TOC_LINE.sub("", text)
    out = workdir / (md_path.stem + "_pre.pdf.md")
    out.write_text(stripped, encoding="utf-8")
    return out


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    if args.md is None:
        print("错误：未提供输入 .md", file=sys.stderr)
        return 1
    md_path = common.resolve_input(project_root, args.md)
    if not md_path.exists():
        print(f"错误：找不到输入 {md_path}", file=sys.stderr)
        return 1
    if args.output is None:
        out_path = Path(project_root) / (global_cfg.get("output_dir") or "output") / (md_path.stem + ".pdf")
    else:
        out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pandoc = common.which_pandoc()
    if not pandoc:
        print("错误：未找到 pandoc（winget install pandoc）", file=sys.stderr)
        return 1

    # Choose engine: explicit, else first available of xelatex -> typst.
    engine = args.engine
    if engine == "auto":
        if common.which("xelatex") or common.which("pdflatex"):
            engine = "xelatex"
        elif common.which("typst"):
            engine = "typst"
        else:
            print("错误：未找到可用的 PDF 引擎（xelatex/pdflatex/typst）\n"
                  "  安装 MiKTeX（含 xelatex）或 typst：\n"
                  "    winget install MiKTeX.MiKTeX\n"
                  "    winget install Typst.Typst", file=sys.stderr)
            return 1
    if not common.which(engine):
        print(f"错误：未找到 {engine}。请安装对应引擎。", file=sys.stderr)
        return 1

    # Pre-process: strip Google-Docs TOC (typst chokes on dangling _heading links).
    workdir = Path(project_root) / (global_cfg.get("workdir") or "output/_tmp")
    workdir.mkdir(parents=True, exist_ok=True)
    pre = _strip_toc(md_path, workdir)

    cmd = [pandoc, str(pre), "-o", str(out_path), "--pdf-engine=" + engine]
    if engine != "typst":
        tpl = args.template or str(project_root / "assets" / "pandoc" / "eisvogel.tex")
        if Path(tpl).exists():
            cmd += ["--template=" + tpl]
        else:
            print("提示：未找到 Eisvogel 模板，使用 pandoc 默认模板", file=sys.stderr)

    try:
        r = common.run_cmd(cmd, timeout=300)
        if r.returncode != 0:
            print(r.stderr or r.stdout, file=sys.stderr)
            return 1
        print(f"已生成: {out_path} ({engine})")
        return 0
    except subprocess.TimeoutExpired:
        print("PDF 生成超时", file=sys.stderr)
        return 1
    finally:
        if not getattr(args, "keep_md", False) and pre.exists():
            try:
                pre.unlink()
            except OSError:
                pass
