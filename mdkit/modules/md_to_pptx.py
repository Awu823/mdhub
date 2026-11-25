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
    sp.add_argument("md", nargs="?", help="输入 .md（幻灯片用 --- 分页）")
    sp.add_argument("-o", "--output", help="输出 .pptx 路径")
    sp.add_argument("--backend", choices=("auto", "marp", "md2pptx"), default="auto")
    sp.add_argument("--browser", choices=("auto", "chrome", "edge", "firefox"),
                    default="chrome", help="Marp 使用的浏览器（仅 --backend marp）")
    sp.add_argument("--browser-timeout", type=int, default=90,
                    help="Marp 浏览器操作超时秒数（仅 --backend marp）")


def _md2pptx_src(project_root: Path) -> Path | None:
    """Locate the bundled md2pptx script (self-contained, no external project)."""
    cand = project_root / "assets" / "md2pptx" / "md2pptx"
    return cand if cand.exists() else None


def _marp(md_path: str, out_path: str, browser: str, timeout: int) -> int:
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
            print(f"Marp 已生成: {out_path}")
            return 0
        print((r.stderr or r.stdout or "").strip(), file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("Marp 超时（浏览器启动/渲染失败）", file=sys.stderr)
        return 1


def _md2pptx(project_root: Path, md_path: str, out_path: str) -> int:
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
        print(f"md2pptx 已生成: {out_path}")
        return 0
    except subprocess.TimeoutExpired:
        print("md2pptx 超时", file=sys.stderr)
        return 1


def run(args) -> int:
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    if args.md is None:
        print("错误：未提供输入 .md", file=sys.stderr)
        return 1
    md_path = str(common.resolve_input(project_root, args.md))
    if not Path(md_path).exists():
        print(f"错误：找不到输入 {md_path}", file=sys.stderr)
        return 1
    if args.output is None:
        out_path = str(Path(project_root) / (global_cfg.get("output_dir") or "output") /
                        (Path(md_path).stem + ".pptx"))
    else:
        out_path = args.output

    backend = args.backend
    if backend == "auto":
        if _md2pptx_src(project_root):
            backend = "md2pptx"          # reliable default
        elif common.which("npx"):
            backend = "marp"
        else:
            print("错误：无可用 pptx 后端（缺 md2pptx 与 npx）", file=sys.stderr)
            return 2

    if backend == "md2pptx":
        rc = _md2pptx(project_root, md_path, out_path)
        if rc == 0:
            return 0
        # fall back to marp
        print("\n回退到 Marp ...", file=sys.stderr)
        return _marp(md_path, out_path, args.browser, args.browser_timeout)
    # marp primary
    rc = _marp(md_path, out_path, args.browser, args.browser_timeout)
    if rc == 0:
        return 0
    print("\n回退到 md2pptx ...", file=sys.stderr)
    return _md2pptx(project_root, md_path, out_path)
