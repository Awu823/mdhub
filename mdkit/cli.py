"""Unified CLI router for mdkit.

Usage:
    python -m mdkit <subcommand> ...
    mdhub.bat <subcommand> ...

Subcommands are registered by mdkit.registry and implemented in mdkit/modules/.
This file only wires argparse and dispatches; it knows nothing about internals.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import mdkit.registry as reg


def _project_root() -> Path:
    """Project root = parent of the mdkit package (the mdhub/ dir)."""
    return Path(__file__).resolve().parent.parent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mdhub",
        description="统一 Markdown 转换工具（mdkit）",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s (mdkit) 0.1.0"
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")

    for name in reg.names():
        sp = sub.add_parser(name, help=reg.desc(name))
        module = reg.load(name)
        module.add_subparser(sp)
        sp.set_defaults(_fn=module.run)

    return parser


def main(argv: list[str] | None = None) -> int:
    # UTF-8 stdout so Chinese output does not crash on cp1252 consoles.
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    # Give modules the project root and config (they may need them).
    args._project_root = str(_project_root())
    args._project_root_path = _project_root()
    return args._fn(args)


if __name__ == "__main__":
    sys.exit(main())
