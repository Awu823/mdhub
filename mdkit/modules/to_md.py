"""to-md: convert arbitrary files/URLs to Markdown (reverse direction).

Source: markItDown/file2md.py (kept behaviour 1:1, wrapped as a module).
Depends on `markitdown` (heavy); imported lazily so its absence only affects
this subcommand. Accepts local files, directories (batch), and http(s) URLs.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

from mdkit import common


def add_subparser(sp):
    sp.add_argument("input", nargs="?",
                    help="输入文件、目录（批量）或 URL（留空读 stdin）")
    sp.add_argument("-o", "--output", help="输出 Markdown 文件路径/目录（留空写 stdout）")
    sp.add_argument("--insecure", action="store_true",
                    help="抓取 URL 时跳过 SSL 证书校验（自签名/证书链异常的站点）")
    common.add_output_args(sp)


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


def convert_file(input_path: str | Path, requests_session=None) -> str:
    """Convert a local file (or URL) to Markdown and return the text.

    ``requests_session`` lets callers supply a pre-configured session (e.g. with
    ``verify=False`` for self-signed-certificate sites).
    """
    import requests  # import here so the lazy path stays optional

    MarkItDown, _ = _import_markitdown()
    md = MarkItDown(enable_builtins=True, requests_session=requests_session)
    src = str(input_path)
    if src.startswith(("http://", "https://")):
        result = md.convert_url(src)
    else:
        result = md.convert(src)
    return result.text_content


def _url_session(insecure: bool):
    """Build a requests session, optionally skipping SSL certificate verification."""
    import warnings

    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    if insecure:
        warnings.simplefilter("ignore")  # suppress InsecureRequestWarning
        s.verify = False
    return s


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
    reporter = common.Reporter(args.quiet, args.json)
    given = args.input

    session = _url_session(args.insecure) if given.startswith(("http://", "https://")) else None

    # URL: convert directly (no directory expansion).
    if given.startswith(("http://", "https://")):
        try:
            text = convert_file(given, requests_session=session)
            if args.output:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                reporter.ok(given, out)
            elif args.json:
                reporter.ok(given, content=text)
            else:
                print(text)  # stdout carries the payload (quiet does not hide it)
                reporter.results.append({"file": given, "ok": True})
        except Exception as exc:
            reporter.fail(given, exc)
        return reporter.finish()

    inputs = common.expand_inputs(project_root, given, ())  # empty exts = all files
    if not inputs:
        reporter.fail(given, "未找到可转换的文件")
        return reporter.finish()
    out_as_dir = common.is_dir_output(args.output)
    out_dir = Path(args.output) if out_as_dir else None
    if out_as_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    elif len(inputs) > 1:
        print("错误：批量转换（目录/多文件）时 -o 必须是输出目录", file=sys.stderr)
        return 2

    for src in inputs:
        try:
            text = convert_file(src)
            if args.output is None:
                if args.json:
                    reporter.ok(src, content=text)
                else:
                    print(text)  # stdout carries the payload
                    reporter.results.append({"file": str(src), "ok": True})
            else:
                out = (out_dir / (src.stem + ".md")) if out_as_dir else Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                reporter.ok(src, out)
        except SystemExit as exc:
            reporter.fail(src, exc)
        except Exception as exc:
            reporter.fail(src, exc)
    return reporter.finish()
