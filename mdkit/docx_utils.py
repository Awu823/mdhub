"""Shared low-level WordprocessingML helpers for docx-producing modules.

Both ``md_to_docx`` (Markdown -> Word) and ``docx_sanitize`` (template
regeneration) manipulate raw OOXML; the helpers here are the parts they share.
``python-docx``/``lxml`` are optional at runtime — the callers keep their own
lazy import + deps check and must not call these helpers before confirming those
deps are present (this module only guards its own imports so that simply
importing it never crashes the CLI).
"""
from __future__ import annotations

try:
    from docx.oxml import OxmlElement  # noqa: F401  (re-exported for callers)
    from docx.oxml.ns import qn
except ImportError:  # pragma: no cover - callers check deps before use
    qn = None

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def wq(t: str) -> str:
    """Return a fully-qualified WordprocessingML tag name."""
    return "{%s}%s" % (W, t)


def set_cell_text(cell, text: str) -> None:
    """Replace a table cell's body with a single run of ``text``.

    Keeps the first paragraph (and its ``pPr``), drops the rest, then writes one
    run. ``xml:space="preserve"`` is set so leading/trailing spaces survive.
    """
    tc = cell._tc
    ps = tc.findall(qn("w:p"))
    for p in ps[1:]:
        tc.remove(p)
    p0 = ps[0]
    ppr = p0.find(qn("w:pPr"))
    for child in list(p0):
        if child is not ppr:
            p0.remove(child)
    r = p0.makeelement(qn("w:r"), {})
    t = p0.makeelement(qn("w:t"), {})
    t.text = text
    t.set(qn("xml:space"), "preserve")
    r.append(t)
    (ppr.addnext(r) if ppr is not None else p0.insert(0, r))


def pstyle_val(el) -> str | None:
    """Return the ``w:pStyle`` val of a ``<w:p>`` element, or ``None``."""
    ppr = el.find(qn("w:pPr"))
    st = ppr.find(qn("w:pStyle")) if ppr is not None else None
    return st.get(qn("w:val")) if st is not None else None


def is_heading(el) -> bool:
    """True if ``el`` is a Heading1/2/3 paragraph element."""
    return pstyle_val(el) in ("Heading1", "Heading2", "Heading3")
