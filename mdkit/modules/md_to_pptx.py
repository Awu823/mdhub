"""md_to_pptx: Markdown -> PowerPoint.

Backends:
  * md2pptx (default) — python-pptx based (bundled in assets/md2pptx). Pure Python,
    no browser needed. Reliable everywhere.
  * marp    (--backend marp) — `npx @marp-team/marp-cli --pptx --browser chrome`.
    Best fidelity for slide decks, but needs node + a browser and can be
    flaky on some machines (puppeteer launch timeouts).

Auto: md2pptx if its source + python-pptx are present, else marp.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from mdkit import common


def add_subparser(sp):
    sp.add_argument("md", nargs="?", help="输入 .md（幻灯片用 --- 分页）或目录（批量）")
    sp.add_argument("-o", "--output", help="输出 .pptx 路径或输出目录（默认与输入同名 .pptx）")
    sp.add_argument("--backend", choices=("auto", "marp", "md2pptx"), default="auto")
    sp.add_argument("--browser", choices=("auto", "chrome", "edge", "firefox"),
                    default="chrome", help="Marp 使用的浏览器（仅 --backend marp）")
    sp.add_argument("--browser-timeout", type=int, default=90,
                    help="Marp 浏览器操作超时秒数（仅 --backend marp）")
    common.add_output_args(sp)


def _md2pptx_src(project_root: Path) -> Path | None:
    """Locate the bundled md2pptx script (self-contained, no external project)."""
    cand = project_root / "assets" / "md2pptx" / "md2pptx"
    return cand if cand.exists() else None


def _marp(md_path: str, out_path: str, browser: str, timeout: int, quiet: bool = False) -> int:
    npx = common.which("npx")
    if not npx:
        print("错误：未找到 npx（需要 Node 安装 Marp）", file=sys.stderr)
        return 2
    cmd = [npx, "--yes", "@marp-team/marp-cli@latest", md_path,
           "--pptx", "-o", out_path,
           "--browser", browser, "--browser-timeout", str(timeout)]
    try:
        r = common.run_cmd(cmd, timeout=timeout + 60)
        if r.returncode == 0 and Path(out_path).exists():
            if not quiet:
                print(f"Marp 已生成: {out_path}")
            return 0
        print((r.stderr or r.stdout or "").strip(), file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("Marp 超时（浏览器启动/渲染失败）", file=sys.stderr)
        return 1


def _md2pptx(project_root: Path, md_path: str, out_path: str, quiet: bool = False) -> int:
    script = _md2pptx_src(project_root)
    if not script:
        print("错误：未找到内置 md2pptx 脚本（assets/md2pptx）", file=sys.stderr)
        return 2
    try:
        import pptx  # noqa: F401
    except ImportError:
        print("错误：未安装 python-pptx。请 pip install python-pptx", file=sys.stderr)
        return 2
    py = common.which("python") or "python"
    try:
        r = common.run_cmd([py, str(script), md_path, out_path], timeout=120)
        if r.returncode != 0 or not Path(out_path).exists():
            print((r.stderr or r.stdout or "").strip(), file=sys.stderr)
            return 1
        if not quiet:
            print(f"md2pptx 已生成: {out_path}")
        return 0
    except subprocess.TimeoutExpired:
        print("md2pptx 超时", file=sys.stderr)
        return 1


def _convert_one(project_root: Path, md_path: str, out_path: str, args) -> None:
    """Convert one md -> pptx (with backend fallback). Raises on failure."""
    quiet = args.quiet or args.json
    backend = args.backend
    if backend == "auto":
        if _md2pptx_src(project_root):
            backend = "md2pptx"          # reliable default
        elif common.which("npx"):
            backend = "marp"
        else:
            raise SystemExit("错误：无可用 pptx 后端（缺 md2pptx 与 npx）")

    if backend == "md2pptx":
        rc = _md2pptx(project_root, md_path, out_path, quiet)
        if rc == 0:
            return
        if not quiet:
            print("\n回退到 Marp ...", file=sys.stderr)
        if _marp(md_path, out_path, args.browser, args.browser_timeout, quiet) != 0:
            raise SystemExit("md2pptx 与 Marp 均失败")
        return

    rc = _marp(md_path, out_path, args.browser, args.browser_timeout, quiet)
    if rc == 0:
        return
    if not quiet:
        print("\n回退到 md2pptx ...", file=sys.stderr)
    if _md2pptx(project_root, md_path, out_path, quiet) != 0:
        raise SystemExit("Marp 与 md2pptx 均失败")


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
        out_path = (out_dir / (md_path.stem + ".pptx")) if (out_as_dir or not args.output) else args.output
        try:
            _convert_one(project_root, str(md_path), str(out_path), args)
            reporter.ok(md_path, out_path)
        except SystemExit as exc:
            reporter.fail(md_path, exc)
        except Exception as exc:
            reporter.fail(md_path, exc)
    return reporter.finish()
