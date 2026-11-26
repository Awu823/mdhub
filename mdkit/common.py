"""Shared helpers: config loading, path resolution, UTF-8 console.

Imported by modules so each module can resolve input/output/template paths
relative to the mdhub project root instead of the cwd.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CONFIG_NAME = "mkit.json"

# Admonition/callout markers, per picoloom/markdownFly conventions:
#   > [!NOTE] title        (Obsidian-style blockquote alert)
#   > [!WARNING] title
#   ::: note  ...  :::      (Pandoc-style fenced div)
ADMONITION_TYPES = {
    "note": ("note", "提示", "⚠"),
    "tip": ("tip", "提示", "💡"),
    "important": ("important", "重要", "⭐"),
    "warning": ("warning", "警告", "⚠"),
    "caution": ("caution", "注意", "⚠"),
    "danger": ("danger", "危险", "⛔"),
    "info": ("info", "信息", "ℹ"),
    "success": ("success", "成功", "✅"),
}


def full_path_env(extra: dict | None = None) -> dict:
    """Return a subprocess env whose PATH includes the *registry* user+system PATH.

    A shell opened *before* a new tool was installed (e.g. typst via winget)
    holds a stale PATH snapshot. Merging the live registry PATH into the child
    env lets pandoc find --pdf-engine=typst even in that stale shell.
    """
    env = os.environ.copy()
    paths = [env.get("PATH", "")]
    try:
        import winreg  # Windows only; no-op elsewhere

        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as k:
                    v, _ = winreg.QueryValueEx(k, "Path")
                    paths.append(v)
            except OSError:
                pass
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                v, _ = winreg.QueryValueEx(k, "Path")
                paths.append(v)
        except OSError:
            pass
    except ImportError:
        pass
    env["PATH"] = os.pathsep.join(p for p in paths if p)
    if extra:
        env.update(extra)
    return env


def which(cmd: str) -> str | None:
    """shutil.which with stale-shell tolerance (searches the live registry PATH)."""
    p = shutil.which(cmd)
    if p:
        return p
    return shutil.which(cmd, path=full_path_env().get("PATH", ""))


def which_pandoc() -> str | None:
    """Locate pandoc: PATH, then the default Windows install path."""
    p = which("pandoc")
    if p:
        return p
    cand = Path.home() / "AppData/Local/Pandoc/pandoc.exe"
    return str(cand) if cand.exists() else None


def run_cmd(cmd: list, timeout: int = 300):
    """Run a subprocess with UTF-8 output and the full (registry) PATH."""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace", env=full_path_env())


def load_config(project_root: Path) -> dict:
    """Load config/mkit.json; return {} if absent (bare defaults win)."""
    p = Path(project_root) / "config" / CONFIG_NAME
    if p.exists():
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def resolve_input(project_root: Path, given: str) -> Path:
    """Resolve an input path: absolute, caller-cwd-relative, or under data/input/.

    When invoked via bin/mdhub.bat the batch cd's to the project root, so a bare
    relative path would otherwise be interpreted against the project root instead
    of the directory the user actually ran from. bin/mdhub.bat preserves the
    caller's original cwd in MDHUB_CALLER_CWD; prefer it for a natural feel.
    """
    cfg = load_config(project_root)
    input_dir = cfg.get("input_dir") or "data/input"
    p = Path(given)
    caller = os.environ.get("MDHUB_CALLER_CWD")
    if caller:
        c = Path(caller) / given
        if c.exists():
            return c
    if p.exists():
        return p
    cand = Path(project_root) / input_dir / given
    if cand.exists():
        return cand
    if not p.suffix:
        cand2 = Path(project_root) / input_dir / (given + ".md")
        if cand2.exists():
            return cand2
    return p  # let caller decide / error


def make_subargs(project_root, *, md=None, output=None, input_path=None, **overrides):
    """Build a complete argparse.Namespace that every module's run() expects.

    Used by `multi` and `pipe` which compose modules and therefore must supply
    every attribute each run() reads, even if a subcommand would normally
    default it. CLI-only flags are given safe defaults here.
    """
    import argparse

    ns = argparse.Namespace(
        md=md,
        input=input_path,
        output=output,
        template=None,
        config=None,
        body_start=None,
        doc_name=None,
        doc_assoc=None,
        doc_type=None,
        doc_loc=None,
        history=None,
        cover_name=None,
        cover_assoc=None,
        cover_type=None,
        cover_loc=None,
        cover_hist=None,
        keep_temp=False,
        keep_md=False,
        workdir=None,
        theme="midnight",
        no_mermaid=False,
        basic=False,
        backend="auto",
        engine="auto",
        to=None,
        keep=False,
        json=False,
        # Composed modules (multi/pipe) run sub-modules quietly; the caller
        # owns the progress/summary output.
        quiet=True,
        # docx rendering
        mermaid="auto",
        syntax_highlighting="default",
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    ns._project_root = str(project_root)
    return ns


def add_output_args(sp):
    """Attach the cross-cutting --json / --quiet flags shared by subcommands."""
    sp.add_argument("--json", action="store_true", help="以 JSON 输出机器可读结果")
    sp.add_argument("--quiet", action="store_true", help="只输出错误（静默成功项）")


def is_dir_output(output) -> bool:
    """True if an ``-o`` value should be treated as an output directory.

    A value ending in a path separator, an existing directory, or one with no
    file extension is treated as a directory; anything else is a file path.
    """
    if not output:
        return False
    s = str(output)
    if s.endswith(("/", "\\")):
        return True
    p = Path(output)
    if p.exists() and p.is_dir():
        return True
    return p.suffix == ""


def expand_inputs(project_root: Path, given: str, exts=(".md",)) -> list[Path]:
    """Expand an input spec into a list of files.

    A directory globs its matching files (sorted); a single path is returned
    as-is. Non-absolute paths resolve via :func:`resolve_input`.
    """
    raw = Path(given)
    resolved = resolve_input(project_root, given) if not raw.is_absolute() else raw
    if resolved.is_dir():
        return sorted(f for f in resolved.iterdir()
                      if f.is_file() and (not exts or f.suffix.lower() in exts))
    return [resolved]


class Reporter:
    """Collect per-file results and emit human or JSON output.

    ``quiet`` suppresses per-item OK lines (errors always print to stderr).
    ``json_out`` prints a single JSON object on stdout at :meth:`finish`.
    ``finish`` returns the process exit code (0 iff every result is OK).
    """

    def __init__(self, quiet: bool = False, json_out: bool = False):
        self.quiet = quiet
        self.json_out = json_out
        self.results: list[dict] = []

    def ok(self, name, output=None, **extra):
        rec = {"file": str(name), "ok": True, "output": str(output) if output else None}
        rec.update(extra)
        self.results.append(rec)
        if not (self.quiet or self.json_out):
            line = f"OK  {rec['file']}"
            if rec["output"]:
                line += f" -> {rec['output']}"
            print(line)

    def fail(self, name, error, **extra):
        rec = {"file": str(name), "ok": False, "error": str(error)}
        rec.update(extra)
        self.results.append(rec)
        print(f"ERR {rec['file']}: {error}", file=sys.stderr)

    @property
    def all_ok(self) -> bool:
        return all(r["ok"] for r in self.results)

    def finish(self) -> int:
        if self.json_out:
            print(json.dumps({"ok": self.all_ok, "results": self.results},
                             ensure_ascii=False))
        return 0 if self.all_ok else 1


def transform_admonitions(text: str) -> str:
    """Rewrite callout markers into pandoc-friendly bold-labeled blockquotes.

    Used by the docx/pdf backends (pandoc), which cannot style ``> [!NOTE]``
    without custom reference styles. Each callout becomes a blockquote whose
    first line is a bold label, so it renders as an indented, labelled note.

    HTML keeps the native ``[!TYPE]`` syntax (rendered by node/render.mjs).
    """
    out: list[str] = []
    in_block = False  # inside a pandoc `::: type` fence
    block_quote = False  # inside a `> [!TYPE]` blockquote
    for line in text.splitlines():
        if in_block:
            if line.strip() == ":::":
                out.append("")  # close fence
                in_block = False
            else:
                out.append(("> " + line) if line.strip() else ">")
            continue
        m = re.match(r"^:::\s*(\w+)\s*(.*)$", line)
        if m:
            kind = m.group(1).lower()
            title = m.group(2).strip() or ADMONITION_TYPES.get(kind, (kind, kind, "•"))[1]
            out.append(f"> **{title}**")
            in_block = True
            continue

        bm = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", line)
        if bm:
            if block_quote:
                out.append("")  # terminate previous blockquote
            kind = bm.group(1).lower()
            title = bm.group(2).strip() or ADMONITION_TYPES.get(kind, (kind, kind, "•"))[1]
            out.append(f"> **{title}**")
            block_quote = True
            continue
        if block_quote:
            if line.strip():
                out.append(("> " + line.lstrip()) if not line.lstrip().startswith(">") else line)
            else:
                out.append("")
                block_quote = False
            continue
        out.append(line)
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")
