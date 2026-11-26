"""md_to_docx: Markdown -> corporate Word .docx.

Source: md2doc/src/md2docx.py (post-processing logic preserved 1:1).
Changes vs. the original:
  * Paths are injected (workdir, template, output) instead of a hardcoded ROOT.
  * Config comes from config/mkit.json + CLI flags (CLI wins).
Everything else (cover filling, body injection, table/heading/list/body
post-processing, style + numbering injection) is unchanged.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from mdkit import common
from mdkit.docx_utils import pstyle_val, set_cell_text, wq

try:
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from lxml import etree
    _DEPS_OK = True
except ImportError:  # pragma: no cover - checked lazily in run()
    _DEPS_OK = False

USABLE_WIDTH = 9639
HEADING_NUM_ID = 5

PPR_ORDER = ['pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr',
             'widowControl', 'numPr', 'suppressLineNumbers', 'pBdr', 'shd', 'tabs',
             'suppressAutoHyphens', 'kinsoku', 'wordWrap', 'overflowPunct',
             'topLinePunct', 'autoSpaceDE', 'autoSpaceDN', 'bidi', 'adjustRightInd',
             'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents',
             'suppressOverlap', 'jc', 'textDirection', 'textAlignment',
             'textboxTightWrap', 'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr']
TCPR_ORDER = ['cnfStyle', 'tcW', 'gridSpan', 'hMerge', 'vMerge', 'tcBorders', 'shd',
              'noWrap', 'tcMar', 'textDirection', 'tcFitText', 'vAlign', 'hideMark',
              'headers', 'cellIns', 'cellDel', 'cellMerge', 'tcPrChange']
TBLPR_ORDER = ['tblStyle', 'tblpPr', 'tblOverlap', 'bidiVisual', 'tblStyleRowBandSize',
               'tblStyleColBandSize', 'tblW', 'jc', 'tblCellSpacing', 'tblInd',
               'tblBorders', 'shd', 'tblLayout', 'tblCellMar', 'tblLook',
               'tblCaption', 'tblDescription']

EXTRA_STYLES = (
    '<w:style w:type="paragraph" w:styleId="BlockText">'
    '<w:name w:val="Block Text"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>'
    '<w:qFormat/>'
    '<w:pPr><w:spacing w:before="100" w:after="100"/>'
    '<w:ind w:firstLine="0" w:left="480" w:right="480"/></w:pPr></w:style>'
    '<w:style w:type="character" w:customStyle="1" w:styleId="VerbatimChar">'
    '<w:name w:val="Verbatim Char"/>'
    '<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>'
    '<w:sz w:val="22"/></w:rPr></w:style>'
)


def add_subparser(sp):
    sp.add_argument("md", nargs="?", help="输入 .md 文件")
    basic = sp.add_argument_group("基础")
    basic.add_argument("-t", "--template", help="企业模板 .docx")
    basic.add_argument("-o", "--output", help="输出 .docx 路径")
    basic.add_argument("--config", help="JSON 配置文件（可覆盖 mkit.json）")
    basic.add_argument("--keep-temp", action="store_true", help="保留中间产物")
    basic.add_argument("--workdir", help="中间产物目录（默认 output/_tmp）")
    cover = sp.add_argument_group("封面/正文定制（多数有自动检测，可选）")
    cover.add_argument("--body-start", type=int, help="正文起始行号（0 基）")
    cover.add_argument("--doc-name", help="封面 Document Name")
    cover.add_argument("--doc-assoc", help="封面 Associated Documents")
    cover.add_argument("--doc-type", help="封面 Document Type 值")
    cover.add_argument("--doc-loc", help="封面 Document Location 值")
    cover.add_argument("--history", help="封面 History 值")
    cover.add_argument("--cover-name", help="Document Name 单元格 T,R,C")
    cover.add_argument("--cover-assoc", help="Associated Docs 单元格 T,R,C")
    cover.add_argument("--cover-type", help="Document Type 单元格 T,R,C")
    cover.add_argument("--cover-loc", help="Document Location 单元格 T,R,C")
    cover.add_argument("--cover-hist", help="History 单元格 T,R,C")
    render = sp.add_argument_group("图表与代码渲染")
    render.add_argument("--mermaid", choices=("auto", "on", "off"), default="auto",
                        help="Mermaid 图：auto(有 node 时自动渲染为 SVG 嵌入) / on(强制) / off(保留代码块)")
    render.add_argument("--syntax-highlighting", default="default",
                        help="代码块语法高亮（pandoc --syntax-highlighting：default/none/idiomatic 或样式名，如 pygments/tango/espresso/zenburn/kate/monochrome/breezedark/haddock）")
    common.add_output_args(sp)


def _cell(triple):
    if triple is None:
        return None
    if isinstance(triple, (list, tuple)):
        return tuple(int(x) for x in triple)
    return tuple(int(x) for x in str(triple).split(","))


def _unescape(s):
    return s.replace("\\_", "_").replace("\\-", "-").replace("\\.", ".") \
            .replace("\\ ", " ").replace("\\*", "*").replace("\\`", "`")


def _is_in_md_toc(ln):
    return bool(re.match(r'^\s*\[\d+(?:\.\d+)?\]\.\(#_heading', ln))


def detect_body_start(lines):
    cover_labels = ('document information', 'table of contents')
    for i, ln in enumerate(lines):
        if not ln.lstrip().startswith('# '):
            continue
        label = ln.strip().lstrip('#').strip().lower()
        if label in cover_labels:
            continue
        return i
    return None


def skip_cover_preamble(lines, body_start):
    i = body_start
    while i > 0:
        prev = lines[i - 1]
        if (prev.strip() == ''
                or prev.lstrip().startswith('|')
                or prev.lstrip().startswith('# ')
                or _is_in_md_toc(prev)):
            i -= 1
        else:
            break
    while i < len(lines) and lines[i].strip() == '':
        i += 1
    return i


def detect_cover_meta(lines):
    doc_name = doc_assoc = doc_type = doc_loc = history = None
    for ln in lines:
        m = re.search(r'\|\s*\*\*Document Name\*\*\s*\|\s*(.*?)\s*\|', ln)
        if m:
            doc_name = _unescape(m.group(1))
        m = re.search(r'\|\s*\*\*Associated Documents\*\*\s*\|\s*(.*?)\s*\|', ln)
        if m:
            doc_assoc = _unescape(m.group(1))
        m = re.search(r'\|\s*\*\*Document Type\*\*\s*\|\s*(.*?)\s*\|', ln)
        if m:
            doc_type = _unescape(m.group(1))
        m = re.search(r'\|\s*\*\*Document Location\*\*\s*\|\s*(.*?)\s*\|', ln)
        if m:
            doc_loc = _unescape(m.group(1))
        m = re.search(r'\|\s*\*\*Changes\*\*\s*\|\s*(.*?)\s*\|', ln)
        if not m:
            m = re.search(r'^\|\s*([0-9][^|]*)\s*\|\s*([^|]+)\s*\|', ln)
        if m and not m.group(1).strip().lower().startswith('version'):
            history = _unescape(m.group(2))
    return doc_name, doc_assoc, doc_type, doc_loc, history


def insert_child(parent, el, order):
    tag = etree.QName(el).localname
    idx = order.index(tag)
    for child in parent:
        ctag = etree.QName(child).localname
        if ctag in order and order.index(ctag) > idx:
            child.addprevious(el)
            return
    parent.append(el)


def insert_ppr(pPr, el):
    insert_child(pPr, el, PPR_ORDER)


def insert_tcpr(tcPr, el):
    insert_child(tcPr, el, TCPR_ORDER)


def insert_tblpr(tblPr, el):
    insert_child(tblPr, el, TBLPR_ORDER)


def char_w(ch):
    if ch.isspace():
        return 0.5
    if ch in 'ilI.,:;|\'"()[]{}`|':
        return 0.5
    if ch in 'MW@%&wm':
        return 1.25
    if ch.isupper() or ch.isdigit():
        return 1.05
    return 0.9


def est_width(text):
    return sum(char_w(c) for c in text)


def distribute(weights, usable, min_w, max_w):
    n = len(weights)
    widths = [usable * w / sum(weights) for w in weights]
    for _ in range(20):
        free = [i for i in range(n) if min_w < widths[i] < max_w]
        clamped = sum(widths[i] for i in range(n) if i not in free)
        target = usable - clamped
        cur = sum(widths[i] for i in free)
        if cur <= 0:
            break
        changed = False
        for i in free:
            new = widths[i] * target / cur
            if new < min_w or new > max_w:
                widths[i] = min(max_w, max(min_w, new))
                changed = True
            else:
                widths[i] = new
        if not changed:
            break
    widths = [int(round(w)) for w in widths]
    widths[-1] += usable - sum(widths)
    return widths


def compute_col_widths(tbl, usable=USABLE_WIDTH, min_w=520, max_w=None):
    ncols = len(tbl.columns)
    max_w = max_w or int(usable * 0.55)
    weights = []
    for ci in range(ncols):
        m = 0
        for row in tbl.rows:
            cells = row.cells
            if ci < len(cells):
                m = max(m, est_width(cells[ci].text.strip()))
        weights.append(m + 12)
    return distribute(weights, usable, min_w, max_w)


def fix_table(tbl):
    tblPr = tbl._tbl.tblPr
    if tblPr is None:
        return
    st = tblPr.find(qn('w:tblStyle'))
    if st is None or st.get(qn('w:val')) != 'Table':
        return

    for b in tblPr.findall(qn('w:tblBorders')):
        tblPr.remove(b)
    borders = OxmlElement('w:tblBorders')
    for edge in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        e = OxmlElement('w:' + edge)
        e.set(qn('w:val'), 'single'); e.set(qn('w:sz'), '4')
        e.set(qn('w:space'), '0'); e.set(qn('w:color'), 'auto')
        borders.append(e)
    insert_tblpr(tblPr, borders)

    for cm in tblPr.findall(qn('w:tblCellMar')):
        tblPr.remove(cm)
    mar = OxmlElement('w:tblCellMar')
    for side, val in (('top', '0'), ('left', '115'), ('bottom', '0'), ('right', '115')):
        s = OxmlElement('w:' + side); s.set(qn('w:w'), val); s.set(qn('w:type'), 'dxa')
        mar.append(s)
    insert_tblpr(tblPr, mar)

    widths = compute_col_widths(tbl)
    grid = tbl._tbl.find(qn('w:tblGrid'))
    for gc, w in zip(grid.findall(qn('w:gridCol')), widths):
        gc.set(qn('w:w'), str(w))
    for tw in tblPr.findall(qn('w:tblW')):
        tblPr.remove(tw)
    tw = OxmlElement('w:tblW'); tw.set(qn('w:type'), 'dxa')
    tw.set(qn('w:w'), str(sum(widths)))
    insert_tblpr(tblPr, tw)
    for tl in tblPr.findall(qn('w:tblLayout')):
        tblPr.remove(tl)
    tl = OxmlElement('w:tblLayout'); tl.set(qn('w:type'), 'fixed')
    insert_tblpr(tblPr, tl)

    if tbl.rows:
        tr0 = tbl.rows[0]._tr
        trPr = tr0.find(qn('w:trPr'))
        if trPr is None:
            trPr = OxmlElement('w:trPr'); tr0.insert(0, trPr)
        if trPr.find(qn('w:tblHeader')) is None:
            trPr.append(OxmlElement('w:tblHeader'))
        for c in tbl.rows[0].cells:
            tcPr = c._tc.find(qn('w:tcPr'))
            if tcPr is None:
                tcPr = OxmlElement('w:tcPr'); c._tc.insert(0, tcPr)
            for sh in tcPr.findall(qn('w:shd')):
                tcPr.remove(sh)
            shd = OxmlElement('w:shd')
            shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto')
            shd.set(qn('w:fill'), 'D9D9D9')
            insert_tcpr(tcPr, shd)
            for v in tcPr.findall(qn('w:vAlign')):
                tcPr.remove(v)
            va = OxmlElement('w:vAlign'); va.set(qn('w:val'), 'center')
            insert_tcpr(tcPr, va)
            for p in c.paragraphs:
                pPr = p._p.get_or_add_pPr()
                for j in pPr.findall(qn('w:jc')):
                    pPr.remove(j)
                jc = OxmlElement('w:jc'); jc.set(qn('w:val'), 'center')
                insert_ppr(pPr, jc)


def fix_tables(doc):
    for t in doc.tables:
        fix_table(t)


def build_numfmt(nx_bytes):
    root = etree.fromstring(nx_bytes)
    abstracts = {}
    for ab in root.findall(wq('abstractNum')):
        aid = ab.get(wq('abstractNumId'))
        fmts = {}
        for lvl in ab.findall(wq('lvl')):
            nf = lvl.find(wq('numFmt'))
            fmts[lvl.get(wq('ilvl'))] = nf.get(wq('val')) if nf is not None else None
        abstracts[aid] = fmts
    nummap = {}
    for num in root.findall(wq('num')):
        ref = num.find(wq('abstractNumId'))
        nummap[num.get(wq('numId'))] = ref.get(wq('val')) if ref is not None else None
    return {nid: abstracts.get(aid, {}) for nid, aid in nummap.items()}


def fix_lists(doc, numfmt):
    for p in doc.paragraphs:
        pPr = p._p.find(qn('w:pPr'))
        numPr = pPr.find(qn('w:numPr')) if pPr is not None else None
        if numPr is None:
            continue
        nid_el = numPr.find(qn('w:numId'))
        if nid_el is None:
            continue
        nid = nid_el.get(qn('w:val'))
        if nid is None or not nid.isdigit() or int(nid) < 1000:
            continue
        ilvl_el = numPr.find(qn('w:ilvl'))
        ilvl = ilvl_el.get(qn('w:val')) if ilvl_el is not None else '0'
        fmt = numfmt.get(nid, {}).get(ilvl) or numfmt.get(nid, {}).get('0')
        nid_el.set(qn('w:val'), '4' if fmt == 'bullet' else '1')
        if ilvl_el is None:
            ilvl_el = OxmlElement('w:ilvl')
            numPr.insert(0, ilvl_el)
        ilvl_el.set(qn('w:val'), ilvl)
        sp = pPr.find(qn('w:spacing'))
        if sp is None:
            sp = OxmlElement('w:spacing')
            insert_ppr(pPr, sp)
        sp.set(qn('w:before'), '0'); sp.set(qn('w:after'), '0')
        sp.set(qn('w:line'), '240'); sp.set(qn('w:lineRule'), 'auto')


def _render_mermaid_blocks(text: str, workdir: Path, project_root: Path, quiet: bool = False) -> str:
    """Replace ```mermaid ... ``` blocks with image references.

    Each Mermaid block is rendered to SVG via node/mermaid.mjs. When the system
    has ``rsvg-convert`` (needed by pandoc to embed SVG into docx), the SVG is
    converted to PNG and referenced as an image; otherwise the source block is
    left as-is so conversion never hard-fails, with a hint printed to stderr.
    """
    import re, uuid
    pattern = re.compile(r'```mermaid\n([\s\S]*?)\n```', re.MULTILINE)

    def repl(m):
        src = m.group(1)
        mmd_path = workdir / f"_mermaid_{uuid.uuid4().hex[:8]}.mmd"
        svg_path = mmd_path.with_suffix(".svg")
        mmd_path.write_text(src, encoding="utf-8")
        node = common.which("node")
        if not node or not (project_root / "node" / "mermaid.mjs").exists():
            if not quiet:
                print("警告：不可用 Mermaid 渲染环境，保留代码块", file=sys.stderr)
            return m.group(0)
        try:
            r = common.run_cmd([
                node, str(project_root / "node" / "mermaid.mjs"),
                str(mmd_path), str(svg_path), "--theme", "base", "--width", "6in",
            ], timeout=120)
            if r.returncode != 0 or not svg_path.exists():
                if not quiet:
                    print("警告：Mermaid 渲染失败，保留代码块", file=sys.stderr)
                return m.group(0)
            # pandoc needs rsvg-convert to embed SVG into docx; fall back to PNG.
            rsvg = common.which("rsvg-convert")
            if rsvg:
                png_path = svg_path.with_suffix(".png")
                r = common.run_cmd([rsvg, str(svg_path), "-o", str(png_path)], timeout=60)
                if r.returncode == 0 and png_path.exists():
                    return f"![mermaid]({png_path.name}){{width=6in}}"
                if not quiet:
                    print("警告：rsvg-convert 转 PNG 失败，保留代码块", file=sys.stderr)
            else:
                if not quiet:
                    print("提示：未找到 rsvg-convert，Mermaid 源码将以代码块形式保留（winget 安装 librsvg 可嵌入图片）", file=sys.stderr)
            return m.group(0)
        except Exception as exc:
            if not quiet:
                print(f"警告：Mermaid 渲染异常：{exc}，保留代码块", file=sys.stderr)
            return m.group(0)

    return pattern.sub(repl, text)


def fix_body_indent(doc, left=0, first_line=0, line=240, before=0, after=120):
    paras = doc.paragraphs
    start = None
    for i, p in enumerate(paras):
        if p.style.name == 'Heading 1':
            start = i
            break
    if start is None:
        return
    for p in paras[start:]:
        if pstyle_val(p._p) == 'BlockText':
            continue
        pPr = p._p.find(qn('w:pPr'))
        num = pPr.find(qn('w:numPr')) if pPr is not None else None
        if p.style.name == 'normal' and num is None and p.text.strip():
            pPr = p._p.get_or_add_pPr()
            ind = pPr.find(qn('w:ind'))
            if ind is None:
                ind = OxmlElement('w:ind')
                insert_ppr(pPr, ind)
            ind.set(qn('w:left'), str(left))
            ind.set(qn('w:firstLine'), str(first_line))
            if ind.get(qn('w:hanging')) is not None:
                del ind.attrib[qn('w:hanging')]
            sp = pPr.find(qn('w:spacing'))
            if sp is None:
                sp = OxmlElement('w:spacing')
                insert_ppr(pPr, sp)
            sp.set(qn('w:before'), str(before))
            sp.set(qn('w:after'), str(after))
            sp.set(qn('w:line'), str(line))
            sp.set(qn('w:lineRule'), 'auto')
            jc = pPr.find(qn('w:jc'))
            if jc is None:
                jc = OxmlElement('w:jc')
                insert_ppr(pPr, jc)
            jc.set(qn('w:val'), 'left')


def fix_section_labels(doc, before=180, after=60):
    paras = doc.paragraphs
    start = None
    for i, p in enumerate(paras):
        if p.style.name == 'Heading 1':
            start = i
            break
    if start is None:
        return
    for p in paras[start:]:
        if pstyle_val(p._p) == 'BlockText':
            continue
        pPr = p._p.find(qn('w:pPr'))
        num = pPr.find(qn('w:numPr')) if pPr is not None else None
        if p.style.name != 'normal' or num is not None:
            continue
        runs = [r for r in p.runs if r.text.strip()]
        if not runs or not all(r.bold for r in runs):
            continue
        txt = p.text.strip()
        if not txt or txt.endswith('.'):
            continue
        pPr = p._p.get_or_add_pPr()
        sp = pPr.find(qn('w:spacing'))
        if sp is None:
            sp = OxmlElement('w:spacing')
            insert_ppr(pPr, sp)
        sp.set(qn('w:before'), str(before))
        sp.set(qn('w:after'), str(after))


def add_heading_numbering(doc):
    for lvl, name in ((0, 'Heading 1'), (1, 'Heading 2'), (2, 'Heading 3')):
        style = doc.styles[name]
        pPr = style.element.get_or_add_pPr()
        for np in pPr.findall(qn('w:numPr')):
            pPr.remove(np)
        numPr = OxmlElement('w:numPr')
        ilvl = OxmlElement('w:ilvl'); ilvl.set(qn('w:val'), str(lvl))
        numId = OxmlElement('w:numId'); numId.set(qn('w:val'), str(HEADING_NUM_ID))
        numPr.append(ilvl); numPr.append(numId)
        insert_ppr(pPr, numPr)
        ind = pPr.find(qn('w:ind'))
        if ind is None:
            ind = OxmlElement('w:ind')
            insert_ppr(pPr, ind)
        ind.set(qn('w:left'), '210')
        ind.set(qn('w:hanging'), '210')


def inject_styles(path):
    zin = zipfile.ZipFile(path)
    sx = zin.read('word/styles.xml').decode('utf-8')
    zin.close()
    if '<w:styleId="BlockText"' in sx or '<w:styleId="VerbatimChar"' in sx:
        return
    sx = sx.replace('</w:styles>', EXTRA_STYLES + '</w:styles>')
    tmp = path + '.tmp'
    zin = zipfile.ZipFile(path)
    zout = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == 'word/styles.xml':
            data = sx.encode('utf-8')
        zout.writestr(item, data)
    zin.close(); zout.close()
    shutil.move(tmp, path)


def inject_numbering(path):
    abstract = (
        '<w:abstractNum w:abstractNumId="%d">'
        '<w:multiLevelType w:val="hybridMultilevel"/>'
        '<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
        '<w:lvlText w:val="%%1."/><w:lvlJc w:val="left"/>'
        '<w:pPr><w:ind w:left="210" w:hanging="210"/></w:pPr></w:lvl>'
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
        '<w:lvlText w:val="%%1.%%2."/><w:lvlJc w:val="left"/>'
        '<w:pPr><w:ind w:left="210" w:hanging="210"/></w:pPr></w:lvl>'
        '<w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
        '<w:lvlText w:val="%%1.%%2.%%3."/><w:lvlJc w:val="left"/>'
        '<w:pPr><w:ind w:left="210" w:hanging="210"/></w:pPr></w:lvl>'
        '</w:abstractNum>'
    ) % HEADING_NUM_ID
    num = ('<w:num w:numId="%d"><w:abstractNumId w:val="%d"/></w:num>'
           % (HEADING_NUM_ID, HEADING_NUM_ID))
    tmp = path + '.tmp'
    zin = zipfile.ZipFile(path)
    zout = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == 'word/numbering.xml':
            s = data.decode('utf-8')
            if '<w:num ' in s:
                s = s.replace('<w:num ', abstract + '<w:num ', 1)
            else:
                s = s.replace('</w:numbering>', abstract + '</w:numbering>')
            s = s.replace('</w:numbering>', num + '</w:numbering>')
            data = s.encode('utf-8')
        zout.writestr(item, data)
    zin.close(); zout.close()
    shutil.move(tmp, path)


def _set_cover(doc, triple, text):
    if not triple:
        return
    ti, ri, ci = triple
    try:
        set_cell_text(doc.tables[ti].rows[ri].cells[ci], text)
    except IndexError:
        print('warning: cover cell %s out of range' % (triple,), file=sys.stderr)


def _resolve_template(project_root, given):
    # candidate locations, in order: explicit path -> root-level templates/
    candidates = []
    if given:
        candidates.append(Path(given))
        candidates.append(project_root / "templates" / given)
        # bare filename (no dir) -> also try default template
        if "/" not in given and "\\" not in given:
            candidates.append(project_root / "templates" / "template.docx")
    else:
        candidates.append(project_root / "templates" / "template.docx")
    for c in candidates:
        if c.exists():
            return c
    tried = ", ".join(str(c) for c in candidates) if candidates else "(none)"
    raise SystemExit(f"错误：template not found。已尝试：{tried}")


def build_config(args, project_root, global_cfg):
    cfg = dict(global_cfg.get("docx", {}))
    # defaults
    cfg.setdefault('body_start', None)
    for k in ('doc_name', 'doc_assoc', 'doc_type', 'doc_loc', 'history'):
        cfg.setdefault(k, None)
    cfg.setdefault('cover_name', (0, 0, 1))
    cfg.setdefault('cover_assoc', (0, 3, 1))
    cfg.setdefault('cover_type', (0, 1, 1))
    cfg.setdefault('cover_loc', (0, 2, 1))
    cfg.setdefault('cover_hist', (1, 2, 1))

    # user JSON config (explicit --config) overrides global
    if args.config:
        with open(args.config, encoding='utf-8') as fh:
            data = json.load(fh)
        for k in ('body_start', 'doc_name', 'doc_assoc', 'doc_type', 'doc_loc', 'history', 'template'):
            if k in data:
                cfg[k] = data[k]
        for k in ('cover_name', 'cover_assoc', 'cover_type', 'cover_loc', 'cover_hist'):
            if k in data:
                cfg[k] = _cell(data[k])
        if data.get('md'):
            args.md = data.get('md') or args.md
        if data.get('output'):
            args.output = data.get('output') or args.output

    # CLI wins
    if args.body_start is not None:
        cfg['body_start'] = args.body_start
    if args.doc_name is not None:
        cfg['doc_name'] = args.doc_name
    if args.doc_assoc is not None:
        cfg['doc_assoc'] = args.doc_assoc
    if args.doc_type is not None:
        cfg['doc_type'] = args.doc_type
    if args.doc_loc is not None:
        cfg['doc_loc'] = args.doc_loc
    if args.history is not None:
        cfg['history'] = args.history
    if args.cover_name:
        cfg['cover_name'] = _cell(args.cover_name)
    if args.cover_assoc:
        cfg['cover_assoc'] = _cell(args.cover_assoc)
    if args.cover_type:
        cfg['cover_type'] = _cell(args.cover_type)
    if args.cover_loc:
        cfg['cover_loc'] = _cell(args.cover_loc)
    if args.cover_hist:
        cfg['cover_hist'] = _cell(args.cover_hist)

    if not args.md and 'md' not in cfg:
        raise SystemExit('错误：未提供输入 .md 文件（位置参数或 --config）')
    cfg['md'] = args.md
    cfg['template'] = args.template or cfg.get('template')
    cfg['output'] = args.output or cfg.get('output')
    return cfg


def run(args) -> int:
    if not _DEPS_OK:
        print("错误：缺少 python-docx / lxml。请先运行 pip install -r requirements.txt", file=sys.stderr)
        return 1
    project_root = Path(args._project_root)
    global_cfg = common.load_config(project_root)
    cfg = build_config(args, project_root, global_cfg)

    # resolve input (basename under input/ or given path) BEFORE cover-meta
    # detection so detection reads the file it will actually convert.
    md_path = common.resolve_input(project_root, cfg['md'])
    cfg['md'] = str(md_path)
    # resolve template
    tpl = _resolve_template(project_root, cfg.get('template'))
    cfg['template'] = str(tpl)
    # resolve output
    if cfg.get('output'):
        out = Path(cfg['output'])
        if not out.is_absolute():
            out = project_root / out
        out.parent.mkdir(parents=True, exist_ok=True)
        cfg['output'] = str(out)
    else:
        out_dir = project_root / (global_cfg.get('output_dir') or 'output')
        out_dir.mkdir(parents=True, exist_ok=True)
        cfg['output'] = str(out_dir / (md_path.stem + '.docx'))

    # Auto-detect cover metadata that was not supplied / configured.
    lines = open(cfg['md'], encoding='utf-8').read().splitlines()
    doc_name, doc_assoc, doc_type, doc_loc, history = detect_cover_meta(lines)
    cfg['doc_name'] = cfg.get('doc_name') or doc_name
    cfg['doc_assoc'] = cfg.get('doc_assoc') or doc_assoc
    cfg['doc_type'] = cfg.get('doc_type') or doc_type
    cfg['doc_loc'] = cfg.get('doc_loc') or doc_loc
    cfg['history'] = cfg.get('history') or history

    # workdir for intermediates
    workdir = Path(args.workdir) if args.workdir else (project_root / (global_cfg.get('workdir') or 'output/_tmp'))
    workdir.mkdir(parents=True, exist_ok=True)
    body_md = workdir / '_body.md'
    content = workdir / '_content.docx'

    # 1. prepare body
    lines = open(cfg['md'], encoding='utf-8').read().splitlines(keepends=True)
    body_start = cfg.get('body_start')
    if body_start is None:
        body_start = detect_body_start(lines)
        if body_start is None:
            raise SystemExit('错误：无法自动检测正文起始行；请用 --body-start 指定')
        body_start = skip_cover_preamble(lines, body_start)
    body = lines[body_start:]
    out_lines = []
    for i, ln in enumerate(body):
        if i > 0 and ln.lstrip().startswith('* ') and out_lines[-1].strip() \
                and not out_lines[-1].lstrip().startswith(('* ', '- ')):
            prev = out_lines[-1].strip()
            if not prev.startswith(('#', '|', '>')) and not re.match(r'^\d+[.)]\s', prev):
                out_lines.append('\n')
        out_lines.append(ln)
    body_text = common.transform_admonitions(''.join(out_lines))
    # Mermaid 图：预渲染为 SVG 并改写为 pandoc 图片语法，嵌入 docx。
    quiet = args.quiet or args.json
    if args.mermaid != "off":
        body_text = _render_mermaid_blocks(body_text, workdir, project_root, quiet=quiet)
    body_md.write_text(body_text, encoding='utf-8')
    if not quiet:
        print(f'body start line: {body_start} | body md lines: {len(out_lines)}')

    # 2. pandoc
    pandoc = common.which_pandoc()
    if not pandoc:
        print("错误：未找到 pandoc（winget install pandoc）", file=sys.stderr)
        return 1
    pandoc_cmd = [pandoc, str(body_md), '-f', 'markdown', '-t', 'docx',
                  '--reference-doc=' + cfg['template'], '-o', str(content),
                  '--syntax-highlighting=' + args.syntax_highlighting]
    # 相对图片路径（Mermaid SVG）相对于 workdir 解析。
    subprocess.run(pandoc_cmd, check=True, cwd=str(workdir))
    if not quiet:
        print(f'pandoc done -> {content}')

    # 3. merge
    out = cfg['output']
    shutil.copyfile(cfg['template'], out)
    inject_styles(out)
    d = docx.Document(out)
    _set_cover(d, cfg['cover_name'], cfg['doc_name'])
    _set_cover(d, cfg['cover_assoc'], cfg['doc_assoc'])
    _set_cover(d, cfg.get('cover_type'), cfg.get('doc_type'))
    _set_cover(d, cfg.get('cover_loc'), cfg.get('doc_loc'))
    _set_cover(d, cfg['cover_hist'], cfg['history'])

    body_el = d.element.body
    sectPr = body_el.find(qn('w:sectPr'))
    start = None
    for i, ch in enumerate(list(body_el)):
        if ch.tag == qn('w:p') and pstyle_val(ch) == 'Heading1':
            start = i
            break
    assert start is not None, 'first Heading1 not found in template'
    for ch in list(body_el)[start:]:
        if ch is not sectPr:
            body_el.remove(ch)

    z = zipfile.ZipFile(str(content))
    cx = etree.fromstring(z.read('word/document.xml'))
    numfmt = build_numfmt(z.read('word/numbering.xml'))
    z.close()
    for ch in list(cx.find(wq('body'))):
        if ch.tag != wq('sectPr'):
            sectPr.addprevious(copy.deepcopy(ch))

    fix_tables(d)
    fix_lists(d, numfmt)
    fix_body_indent(d)
    fix_section_labels(d)
    add_heading_numbering(d)
    d.save(out)
    inject_numbering(out)
    if not quiet:
        print('saved:', out)

    if not args.keep_temp:
        for f in (body_md, content):
            if f.exists():
                f.unlink()
        # 也清理 Mermaid 临时产物（SVG 已被 pandoc 嵌入 docx）。
        for f in workdir.glob("_mermaid_*"):
            try:
                f.unlink()
            except OSError:
                pass
        if not quiet:
            print('cleaned temp files')
    if args.json:
        import json as _json
        print(_json.dumps({"ok": True, "results": [{"file": str(md_path), "ok": True,
                                                    "output": out}]}, ensure_ascii=False))
    return 0
