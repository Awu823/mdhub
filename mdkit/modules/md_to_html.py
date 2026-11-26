"""md_to_html: Markdown -> standalone HTML (Mermaid + highlight + themes).

Delegates the actual rendering to the Node module (node/render.mjs), which
reuses assets/html/vendor (marked/mermaid/highlight/abap) and assets/html/css.
This keeps the browser preview (assets/html/index.html) and the CLI sharing
the same CSS/vendor.

If Node or its deps are missing, falls back to a stdlib 'basic' renderer
(markdown -> plain HTML, Mermaid left as source blocks, no highlight).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from mdkit import common

THEMES = ("midnight", "parchment", "academic", "apple", "terminal", "slate", "formal")


def add_subparser(sp):
    sp.add_argument("md", nargs="?", help="输入 .md 文件或目录（目录则批量转换）")
    sp.add_argument("-o", "--output", help="输出 .html 路径或输出目录（默认与输入同名 .html）")
    sp.add_argument("-t", "--theme", default="midnight", choices=THEMES, help="主题（默认 midnight）")
    sp.add_argument("--no-mermaid", action="store_true", help="跳过 Mermaid 预渲染")
    sp.add_argument("--basic", action="store_true", help="强制用纯标准库基础渲染（不依赖 Node）")
    common.add_output_args(sp)


def _node_render(md_path: str, out_path: str, theme: str, no_mermaid: bool, project_root: Path, quiet: bool = False) -> int:
    node = shutil.which("node")
    if not node:
        print("警告：未找到 node，回退到基础渲染", file=sys.stderr)
        return _basic_render(md_path, out_path, theme, quiet)
    render = project_root / "node" / "render.mjs"
    if not render.exists():
        print("警告：缺少 node/render.mjs，回退到基础渲染", file=sys.stderr)
        return _basic_render(md_path, out_path, theme, quiet)
    cmd = [node, str(render), md_path, out_path, "--theme", theme]
    if no_mermaid:
        cmd.append("--no-mermaid")
    log = Path(out_path).with_suffix(".node.log")
    try:
        with open(log, "w", encoding="utf-8") as lf:
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=120)
        if r.returncode != 0:
            print(f"Node 渲染失败（详见 {log.name}），回退到基础渲染", file=sys.stderr)
            return _basic_render(md_path, out_path, theme, quiet)
        return 0
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        print(f"Node 渲染异常：{exc}，回退到基础渲染", file=sys.stderr)
        return _basic_render(md_path, out_path, theme, quiet)
    finally:
        if log.exists() and Path(out_path).exists():
            try:
                log.unlink()
            except OSError:
                pass


def _basic_render(md_path: str, out_path: str, theme: str, quiet: bool = False) -> int:
    """Last-resort renderer: markdown -> plain HTML.

    Tries python-markdown if installed; otherwise falls back to a minimal
    stdlib conversion (no Mermaid/highlight) so the command never hard-fails.
    """
    text = Path(md_path).read_text(encoding="utf-8")
    try:
        import markdown as md
        html_body = md.markdown(text, extensions=["tables", "fenced_code"])
    except ImportError:
        import html as _html
        import re as _re
        out_lines, in_code, code_buf = [], False, []
        for line in text.splitlines():
            if line.startswith("```"):
                if in_code:
                    out_lines.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
                    code_buf, in_code = [], False
                else:
                    in_code = True
                continue
            if in_code:
                code_buf.append(line)
                continue
            m = _re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                lvl = len(m.group(1))
                out_lines.append(f"<h{lvl}>{_html.escape(m.group(2))}</h{lvl}>")
            elif line.strip() == "":
                out_lines.append("")
            else:
                out_lines.append("<p>" + _html.escape(line) + "</p>")
        if in_code:
            out_lines.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
        html_body = "\n".join(out_lines)
    css_dir = Path(__file__).resolve().parent.parent.parent / "assets" / "html" / "css"
    app_css = (css_dir / "app.css").read_text(encoding="utf-8") if (css_dir / "app.css").exists() else ""
    themes_css = (css_dir / "themes.css").read_text(encoding="utf-8") if (css_dir / "themes.css").exists() else ""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"""<!doctype html>
<html lang="zh-CN" data-theme="{theme}">
<head><meta charset="utf-8"><title>report</title>
<style>{app_css}\n{themes_css}</style>
</head>
<body><div class="report-page"><div id="report-content">{html_body}</div></div></body>
</html>""",
        encoding="utf-8",
    )
    if not quiet:
        print(f"已生成（基础渲染）: {out}")
    return 0


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    if args.md is None:
        args.md = global_cfg.get("html", {}).get("md")
    if args.md is None:
        print("错误：未提供输入 .md 文件", file=sys.stderr)
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
        out_path = str(out_dir / (md_path.stem + ".html")) if out_as_dir or not args.output else args.output
        try:
            if args.basic:
                _basic_render(str(md_path), out_path, args.theme, quiet=args.quiet or args.json)
            else:
                _node_render(str(md_path), out_path, args.theme, args.no_mermaid, project_root, quiet=args.quiet or args.json)
            reporter.ok(md_path, out_path)
        except Exception as exc:
            reporter.fail(md_path, exc)
    return reporter.finish()
