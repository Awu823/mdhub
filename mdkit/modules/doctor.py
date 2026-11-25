"""doctor: probe the environment and report which backends are usable.

Cheap to run, high value: tells the user what's missing for each subcommand
(pandoc, node, browser, texlive, markitdown) and how to install it.
"""
from __future__ import annotations

import os
from pathlib import Path

from mdkit import common


def add_subparser(sp):
    sp.add_argument("--json", action="store_true", help="以 JSON 输出")


def _node_version() -> str | None:
    p = common.which("node")
    if not p:
        return None
    try:
        r = common.run_cmd([p, "--version"], timeout=10)
        return r.stdout.strip()
    except Exception:
        return "present"


def _pandoc_version() -> str | None:
    p = common.which_pandoc()
    if not p:
        return None
    try:
        r = common.run_cmd([p, "--version"], timeout=10)
        return r.stdout.splitlines()[0] if r.stdout else "pandoc"
    except Exception:
        return "present"


def _xelatex() -> str | None:
    return common.which("xelatex") or common.which("pdflatex") or common.which("typst")


def _browser() -> str | None:
    for b in ("chrome", "google-chrome", "msedge", "firefox"):
        if common.which(b):
            return b
    # Windows fixed install paths (puppeteer/Marp can use these via --browser).
    fixed = [
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Mozilla Firefox/firefox.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ]
    for p in fixed:
        if p.exists():
            return str(p)
    return None


def _markitdown() -> str | None:
    try:
        import markitdown  # noqa: F401
        return getattr(markitdown, "__version__", "present")
    except Exception:
        return None


def _python_pkg(name: str) -> str | None:
    try:
        mod = __import__(name)
        return getattr(mod, "__version__", "present")
    except Exception:
        return None


def check() -> dict:
    return {
        "pandoc": _pandoc_version(),
        "node": _node_version(),
        "browser": _browser(),
        "texlive(xelatex/pdflatex/typst)": _xelatex(),
        "markitdown": _markitdown(),
        "python-docx": _python_pkg("docx"),
        "lxml": _python_pkg("lxml"),
    }


def _status(v):
    return "OK " if v else "MISS"


def run(args) -> int:
    report = check()
    if args.json:
        import json
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    print("mdhub doctor — 环境探测\n")
    for key, val in report.items():
        print(f"  [{_status(val)}] {key:<28} {val if val else '未找到'}")
    print("\n可用子命令:")
    print("  docx/html     需 python-docx + lxml  (+ pandoc 给 docx)")
    print("  to-md         需 markitdown")
    print("  pptx          需 node + 浏览器 (Marp) 或 python-pptx")
    print("  pdf           需 pandoc + xelatex/typst")
    missing = [k for k, v in report.items() if not v]
    if missing:
        print(f"\n缺失：{', '.join(missing)}")
    return 0
