"""md_to_pdf: Markdown -> PDF.

Backends (auto-selected; `--engine` forces one):
  * xelatex (default when available) — uses the Eisvogel LaTeX template if found
  * typst    (fallback)              — lightweight, fast, no LaTeX needed

Pre-processing: strips Google-Docs-style TOC entries ("[1.](#_heading=1) Title")
which would otherwise produce dangling `#link(label("_heading=N"))` references
that make the typst engine fail with "label does not exist", and rewrites
admonition/callout markers (`> [!NOTE]`, `::: type`) into pandoc-friendly
bold-labeled blockquotes.
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
    sp.add_argument("md", nargs="?", help="输入 .md 文件或目录（目录则批量转换）")
    sp.add_argument("-o", "--output", help="输出 .pdf 路径或输出目录（默认与输入同名 .pdf）")
    sp.add_argument("--engine", choices=("auto", "xelatex", "pdflatex", "typst"), default="auto")
    sp.add_argument("--template", help="可选 LaTeX 模板（xelatex 引擎时；缺省用 pandoc 默认模板，"
                                       "可放 assets/pandoc/eisvogel.tex）")
    sp.add_argument("--keep-md", action="store_true", help="保留预处理后的中间 .md")
    common.add_output_args(sp)


def _preprocess(md_path: Path, workdir: Path) -> Path:
    """Return a preprocessed .md with Google-Docs TOC links and callouts fixed."""
    text = md_path.read_text(encoding="utf-8")
    text = _TOC_LINE.sub("", text)
    text = common.transform_admonitions(text)
    out = workdir / (md_path.stem + "_pre.pdf.md")
    out.write_text(text, encoding="utf-8")
    return out


def _pick_engine(engine: str) -> str:
    """Resolve the PDF engine (explicit or first available)."""
    if engine == "auto":
        if common.which("xelatex") or common.which("pdflatex"):
            return "xelatex"
        if common.which("typst"):
            return "typst"
        raise SystemExit("错误：未找到可用的 PDF 引擎（xelatex/pdflatex/typst）\n"
                         "  安装 MiKTeX（含 xelatex）或 typst：\n"
                         "    winget install MiKTeX.MiKTeX\n"
                         "    winget install Typst.Typst")
    if not common.which(engine):
        raise SystemExit(f"错误：未找到 {engine}。请安装对应引擎。")
    return engine


def _convert_one(project_root, global_cfg, md_path, out_path, args) -> str:
    """Convert one md -> pdf. Returns the resolved engine; raises on failure."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pandoc = common.which_pandoc()
    if not pandoc:
        raise SystemExit("错误：未找到 pandoc（winget install pandoc）")

    engine = _pick_engine(args.engine)
    workdir = Path(project_root) / (global_cfg.get("workdir") or "output/_tmp")
    workdir.mkdir(parents=True, exist_ok=True)
    pre = _preprocess(md_path, workdir)

    cmd = [pandoc, str(pre), "-o", str(out_path), "--pdf-engine=" + engine]
    if engine != "typst":
        tpl = args.template or str(project_root / "assets" / "pandoc" / "eisvogel.tex")
        if Path(tpl).exists():
            cmd += ["--template=" + tpl]
        elif not (args.quiet or args.json):
            print("提示：未找到 Eisvogel 模板，使用 pandoc 默认模板", file=sys.stderr)

    try:
        r = common.run_cmd(cmd, timeout=300)
        if r.returncode != 0:
            raise SystemExit(r.stderr or r.stdout)
    except subprocess.TimeoutExpired:
        raise SystemExit("PDF 生成超时")
    finally:
        if not getattr(args, "keep_md", False) and pre.exists():
            try:
                pre.unlink()
            except OSError:
                pass
    return engine


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    if args.md is None:
        print("错误：未提供输入 .md", file=sys.stderr)
        return 1

    reporter = common.Reporter(args.quiet, args.json)
    inputs = common.expand_inputs(project_root, args.md, (".md",))
    out_as_dir = common.is_dir_output(args.output)
    out_dir = (Path(args.output) if out_as_dir else None) or Path(project_root) / (global_cfg.get("output_dir") or "output")
    if out_as_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    elif len(inputs) > 1:
        print("错误：批量转换（目录/多文件）时 -o 必须是输出目录", file=sys.stderr)
        return 2

    for md_path in inputs:
        if not md_path.exists():
            reporter.fail(md_path, "文件不存在")
            continue
        out_path = (out_dir / (md_path.stem + ".pdf")) if (out_as_dir or not args.output) else Path(args.output)
        try:
            engine = _convert_one(project_root, global_cfg, md_path, out_path, args)
            if not (args.quiet or args.json):
                print(f"已生成: {out_path} ({engine})")
            reporter.ok(md_path, out_path)
        except SystemExit as exc:
            reporter.fail(md_path, exc)
        except Exception as exc:
            reporter.fail(md_path, exc)
    return reporter.finish()
