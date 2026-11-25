"""docx_sanitize: regenerate a clean template from an example-filled one.

Source: md2doc/sanitize_template.py (kept 1:1). Neutralizes cover value cells,
sample body content, and docProps free-text/timestamps while preserving the
template skeleton (cover labels, TOC, header/footer, styles, numbering, MSIP label).
"""
from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

try:
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    _DEPS_OK = True
except ImportError:  # pragma: no cover - checked lazily in run()
    _DEPS_OK = False

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

PLACEHOLDER = "[Content to be completed]"
COVER_NAME = "[Document Name]"
COVER_ASSOC = "[Associated Documents]"
HIST_VERSION = "1.0"
HIST_CHANGES = "[Version notes]"


def add_subparser(sp):
    sp.add_argument("src", help="源模板 .docx（含示例内容）")
    sp.add_argument("-o", "--output", help="输出脱敏模板（默认 src 同目录 _sanitized.docx）")


def wq(t):
    return '{%s}%s' % (W, t)


def set_cell_text(cell, text):
    tc = cell._tc
    ps = tc.findall(qn('w:p'))
    for p in ps[1:]:
        tc.remove(p)
    p0 = ps[0]
    ppr = p0.find(qn('w:pPr'))
    for child in list(p0):
        if child is not ppr:
            p0.remove(child)
    r = p0.makeelement(qn('w:r'), {})
    t = p0.makeelement(qn('w:t'), {})
    t.text = text
    t.set(qn('xml:space'), 'preserve')
    r.append(t)
    (ppr.addnext(r) if ppr is not None else p0.insert(0, r))


def make_placeholder_para():
    p = OxmlElement('w:p')
    pPr = OxmlElement('w:pPr')
    ind = OxmlElement('w:ind')
    ind.set(qn('w:left'), '0'); ind.set(qn('w:firstLine'), '0')
    pPr.append(ind)
    sp = OxmlElement('w:spacing')
    sp.set(qn('w:before'), '0'); sp.set(qn('w:after'), '120')
    sp.set(qn('w:line'), '240'); pPr.append(sp)
    jc = OxmlElement('w:jc'); jc.set(qn('w:val'), 'left')
    pPr.append(jc)
    p.append(pPr)
    r = OxmlElement('w:r')
    t = OxmlElement('w:t')
    t.text = PLACEHOLDER
    t.set(qn('xml:space'), 'preserve')
    r.append(t)
    p.append(r)
    return p


def is_heading(ch):
    ppr = ch.find(qn('w:pPr'))
    st = ppr.find(qn('w:pStyle')) if ppr is not None else None
    if st is None:
        return False
    return st.get(qn('w:val')) in ('Heading1', 'Heading2', 'Heading3')


def desensitize_cover(doc):
    info = doc.tables[0]
    set_cell_text(info.rows[0].cells[1], COVER_NAME)
    set_cell_text(info.rows[3].cells[1], COVER_ASSOC)
    set_cell_text(info.rows[1].cells[1], PLACEHOLDER)
    set_cell_text(info.rows[2].cells[1], PLACEHOLDER)
    hist = doc.tables[1]
    set_cell_text(hist.rows[2].cells[0], HIST_VERSION)
    set_cell_text(hist.rows[2].cells[1], HIST_CHANGES)
    body = doc.element.body
    for p in body.iter(qn('w:p')):
        txt = ''.join(t.text or '' for t in p.iter(qn('w:t'))).strip()
        if 'Document approval' in txt or 'Solution Manager' in txt:
            for t in p.iter(qn('w:t')):
                t.text = ''
            break


def desensitize_body(doc):
    body = doc.element.body
    children = list(body)
    first_h1 = None
    for i, ch in enumerate(children):
        if ch.tag == qn('w:p') and is_heading(ch):
            st = ch.find(qn('w:pPr')).find(qn('w:pStyle'))
            if st.get(qn('w:val')) == 'Heading1':
                first_h1 = i
                break
    if first_h1 is None:
        return []
    sectPr = body.find(qn('w:sectPr'))
    to_remove, headings = [], []
    for ch in children[first_h1:]:
        if ch is sectPr:
            continue
        if ch.tag == qn('w:p') and is_heading(ch):
            headings.append(ch)
        else:
            to_remove.append(ch)
    for ch in to_remove:
        body.remove(ch)
    for h in headings:
        if h.getnext() is not sectPr and h.getnext() is not None and not is_heading(h.getnext()):
            continue
        h.addnext(make_placeholder_para())
    return headings


def clean_metadata(path):
    data = {}
    zin = zipfile.ZipFile(path)
    for item in zin.infolist():
        data[item.filename] = zin.read(item.filename)
    zin.close()
    if 'docProps/core.xml' in data:
        s = data['docProps/core.xml'].decode('utf-8')
        for tag in ('title', 'creator', 'lastModifiedBy', 'description', 'subject', 'keywords', 'category'):
            s = re.sub(r'<dc:%s>[^<]*</dc:%s>' % (tag, tag), '<dc:%s></dc:%s>' % (tag, tag), s)
            s = re.sub(r'<cp:%s>[^<]*</cp:%s>' % (tag, tag), '<cp:%s></cp:%s>' % (tag, tag), s)
        s = re.sub(r'<dcterms:created[^>]*>[^<]*</dcterms:created>', '', s)
        s = re.sub(r'<dcterms:modified[^>]*>[^<]*</dcterms:modified>', '', s)
        s = re.sub(r'<cp:revision>[^<]*</cp:revision>', '', s)
        s = re.sub(r'<cp:revision[^>]*/>', '', s)
        data['docProps/core.xml'] = s.encode('utf-8')
    if 'docProps/custom.xml' in data:
        s = data['docProps/custom.xml'].decode('utf-8')
        m = re.match(r"(<\?xml[^>]*?>\s*)(<Properties[^>]*>)(.*)", s, re.DOTALL)
        if m:
            prefix = "MSIP_Label_a0819fa7-4367-4500-ba88-dd630d977609_"
            keep = ("Enabled", "Method", "Name", "SiteId", "ActionId", "ContentBits", "Tag")
            head, props_open, rest = m.group(1), m.group(2), m.group(3)
            props = re.findall(r'<property[^>]*name="([^"]*)"[^>]*>(.*?)</property>', rest, re.DOTALL)
            out = []
            for name, body in props:
                if name.startswith(prefix) and name[len(prefix):] in keep:
                    out.append('<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" name="%s">%s</property>' % (name, body))
                else:
                    out.append('<property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" name="%s"><vt:lpwstr></vt:lpwstr></property>' % name)
            s = head + props_open + ''.join(out) + '</Properties>'
            data['docProps/custom.xml'] = s.encode('utf-8')
    tmp = path + '.tmp'
    zout = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
    for name, blob in data.items():
        zout.writestr(name, blob)
    zout.close()
    shutil.move(tmp, path)


def run(args) -> int:
    if not _DEPS_OK:
        print("错误：缺少 python-docx。请先 pip install -r requirements.txt", file=__import__('sys').stderr)
        return 1
    src = Path(args.src)
    if not src.exists():
        src = Path(args._project_root) / src
    if not src.exists():
        print(f"错误：找不到源模板 {args.src}", file=__import__('sys').stderr)
        return 1
    out = Path(args.output) if args.output else src.with_name(src.stem + '_sanitized.docx')
    out.parent.mkdir(parents=True, exist_ok=True)

    d = docx.Document(str(src))
    desensitize_cover(d)
    heads = desensitize_body(d)
    d.save(str(out))
    clean_metadata(str(out))
    print('saved', out, '| headings kept:', len(heads))
    return 0
