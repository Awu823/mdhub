"""to-md: convert arbitrary files to Markdown (reverse direction).

Source: markItDown/file2md.py (kept behaviour 1:1, wrapped as a module).
Depends on `markitdown` (heavy); imported lazily so its absence only affects
this subcommand.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from mdkit import common


def add_subparser(sp):
    sp.add_argument("input", nargs="?", help="输入文件路径或 URL（留空读 stdin）")
    sp.add_argument("-o", "--output", help="输出 Markdown 文件路径（留空写 stdout）")
    sp.add_argument("--config", default=None, help="JSON 配置（可选）")


def _import_markitdown():
    try:
        from markitdown import MarkItDown
        from markitdown._stream_info import StreamInfo
        return MarkItDown, StreamInfo
    except ImportError as exc:  # pragma: no cover
        print(
            "错误：未安装 markitdown。请先运行：\n"
            "    pip install 'markitdown[all]'\n",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


def convert_file(input_path: str | Path, output_path: str | Path | None = None) -> str:
    MarkItDown, _ = _import_markitdown()
    md = MarkItDown(enable_builtins=True)
    result = md.convert(str(input_path))
    text = result.text_content

    if output_path is not None:
        out = Path(output_path)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"已写入: {out}", file=sys.stderr)
    return text


def convert_stream() -> str:
    MarkItDown, StreamInfo = _import_markitdown()
    data = sys.stdin.buffer.read()

    extension, mimetype = ".txt", "text/plain"
    try:
        import magika

        detected = magika.Magika().identify_bytes(data).output
        label = getattr(detected, "label", None)
        if label:
            mimetype = detected.mime_type or mimetype
            extension = "." + label.split("/")[-1].lstrip(".")
    except Exception:
        pass

    md = MarkItDown(enable_builtins=True)
    result = md.convert_stream(io.BytesIO(data), stream_info=StreamInfo(extension=extension, mimetype=mimetype))
    text = result.text_content
    print(text)
    return text


def run(args) -> int:
    if args.input is None:
        convert_stream()
        return 0

    project_root = Path(args._project_root)
    src = common.resolve_input(project_root, args.input)
    if not src.exists() and not str(src).startswith(("http://", "https://")):
        print(f"错误：找不到文件 {src}", file=sys.stderr)
        return 1

    if args.output is None:
        text = convert_file(src, None)
        print(text)
    else:
        out = Path(args.output)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        convert_file(src, out)
    return 0
