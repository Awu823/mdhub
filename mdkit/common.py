"""Shared helpers: config loading, path resolution, UTF-8 console.

Imported by modules so each module can resolve input/output/template paths
relative to the mdhub project root instead of the cwd.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

CONFIG_NAME = "mkit.json"


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
    """Resolve an input path: absolute, cwd-relative, or under data/input/."""
    cfg = load_config(project_root)
    input_dir = cfg.get("input_dir") or "data/input"
    p = Path(given)
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
    )
    for k, v in overrides.items():
        setattr(ns, k, v)
    ns._project_root = str(project_root)
    ns._project_root_path = project_root
    return ns
