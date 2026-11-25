"""Module registry: subcommand name -> (module attribute that builds parser, call fn).

Each module exposes a uniform contract:
    def add_subparser(sp):  # register arguments on the subparser
    def run(args) -> int     # execute, return exit code

Keeping this table here means cli.py only dispatches and stays module-agnostic.
"""
from __future__ import annotations

# Import modules lazily inside add_subparser/run so a broken optional module
# (e.g. missing markitdown) cannot take down the whole CLI.
_MODULES = {
    "to-md": ("mdkit.modules.to_md", "任意文件 → Markdown（逆向）"),
    "docx": ("mdkit.modules.md_to_docx", "Markdown → 企业模板 .docx"),
    "sanitize": ("mdkit.modules.docx_sanitize", "Word 模板脱敏维护"),
    "html": ("mdkit.modules.md_to_html", "Markdown → 独立 HTML（Node 渲染）"),
    "pptx": ("mdkit.modules.md_to_pptx", "Markdown → PPT（Marp 优先）"),
    "pdf": ("mdkit.modules.md_to_pdf", "Markdown → PDF（Eisvogel/typst）"),
    "multi": ("mdkit.modules.md_to_multi", "一次导出多种格式"),
    "pipe": ("mdkit.modules.pipeline", "链式组合转换"),
    "doctor": ("mdkit.modules.doctor", "环境探测"),
}


def names() -> list[str]:
    return list(_MODULES)


def desc(name: str) -> str:
    return _MODULES.get(name, ("", "未知"))[1]


def load(name: str):
    """Return the module object for a subcommand (lazy import)."""
    import importlib

    modpath, _ = _MODULES[name]
    return importlib.import_module(modpath)
