#!/usr/bin/env node
/**
 * mdkit Node renderer — Markdown -> standalone HTML.
 *
 * Mirrors md2html/index.html logic (marked + highlight.js + mermaid + 7 themes),
 * but headless: reads a .md file, renders to a single self-contained .html that
 * you can open by double-clicking (no JS runtime needed; CSS inlined, Mermaid
 * pre-rendered to inline SVG).
 *
 * Usage:
 *   node node/render.mjs <input.md> [output.html] [--theme midnight] [--no-mermaid]
 *
 * Vendor libs come from assets/html/vendor (marked/min, mermaid/min,
 * highlight/min, abap/min). If those are missing, falls back to installed
 * node_modules (run `npm i` in node/).
 */
import { readFileSync, writeFileSync, existsSync, copyFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const HTML_DIR = resolve(ROOT, "assets", "html");

// ---- argument parsing ------------------------------------------------------
const argv = process.argv.slice(2);
let input = null;
let output = null;
let theme = "midnight";
let mermaidOn = true;

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--theme") theme = argv[++i];
  else if (a === "--no-mermaid") mermaidOn = false;
  else if (a === "-o" || a === "--output") output = argv[++i];
  else if (!a.startsWith("-")) {
    if (input === null) input = a;
    else output = a;
  }
}
if (!input) {
  console.error("用法: node render.mjs <input.md> [output.html] [--theme T] [--no-mermaid]");
  process.exit(1);
}
if (!existsSync(input)) {
  console.error(`找不到输入: ${input}`);
  process.exit(1);
}
if (!output) output = input.replace(/\.[^.]+$/, "") + ".html";

// ---- load vendor libs (prefer assets/html/vendor) -------------------------
function loadLib(name, fallbackImport) {
  const vendored = resolve(HTML_DIR, "vendor", name + ".min.js");
  if (existsSync(vendored)) {
    const src = readFileSync(vendored, "utf8");
    const fn = new Function("module", "exports", "window", "globalThis", "require", "module.exports = (function(){" + src + "}).call(this, module, module.exports, window, globalThis, require); return module.exports;");
    const mod = { exports: {} };
    const sandboxWindow = {};
    const sandboxGlobal = globalThis;
    const sandboxRequire = (m) => require(m);
    fn(mod, mod.exports, sandboxWindow, sandboxGlobal, sandboxRequire);
    return mod.exports;
  }
  return fallbackImport();
}

// ---- CSS -------------------------------------------------------------------
function readCss(file) {
  const p = resolve(HTML_DIR, "css", file);
  return existsSync(p) ? readFileSync(p, "utf8") : "";
}
const appCss = readCss("app.css");
const themesCss = readCss("themes.css");

// ---- render Markdown -------------------------------------------------------
const mdText = readFileSync(input, "utf8");

// Use marked from node_modules (vendor is browser-targeted CJS/UMD).
const { Marked } = await import("marked");
const hljsModule = await import("highlight.js");
const hljs = hljsModule.default || hljsModule;

// optional ABAP language registration (vendor/abap.min.js exposes window.abap / hljs.registerLanguage)
try {
  const abapPath = resolve(HTML_DIR, "vendor", "abap.min.js");
  if (existsSync(abapPath)) {
    const src = readFileSync(abapPath, "utf8");
    new Function("window", "module", "exports", src)({}, { exports: {} }, {});
    // If it registered via global hljs, nothing more needed; otherwise no-op.
  }
} catch (e) { /* ABAP highlight is best-effort */ }

const escapeHtml = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const renderer = {
  code({ text, lang }) {
    const escaped = escapeHtml(text);
    if (lang === "mermaid") {
      return `<div class="mermaid">${escaped}</div>`;
    }
    const langLabel = lang || "text";
    const langClass = lang ? `language-${lang}` : "language-text";
    return `<div class="code-block">
            <div class="code-header"><span>${langLabel.toUpperCase()}</span></div>
            <pre><code class="${langClass}">${escaped}</code></pre>
          </div>`;
  },
  heading({ text, depth }) {
    const slug = text.replace(/<[^>]+>/g, "").trim()
      .toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g, "-").replace(/^-|-$/g, "");
    let cls = "";
    if (depth === 2) {
      if (/🔴|P0/i.test(text)) cls = " priority-p0";
      else if (/🟠|P1/i.test(text)) cls = " priority-p1";
      else if (/🟡|P2/i.test(text)) cls = " priority-p2";
      else if (/🟢|P3/i.test(text)) cls = " priority-p3";
    }
    return `<h${depth} id="${slug}" class="${cls.trim()}">${text}</h${depth}>`;
  },
};

const marked = new Marked({ gfm: true, breaks: false, renderer });
let html = marked.parse(mdText);

// ---- highlight non-mermaid code blocks ------------------------------------
// Extract code block HTML, highlight with hljs, re-inject.
const codeRe = /<div class="code-block">[\s\S]*?<\/div>/g;
const codeBlocks = html.match(codeRe) || [];
for (const block of codeBlocks) {
  const m = block.match(/<code class="([^"]*)">([\s\S]*?)<\/code>/);
  if (!m) continue;
  const cls = m[1] || "";
  const code = m[2].replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
  const lang = cls.replace("language-", "") || "text";
  try {
    const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value;
    const newBlock = block.replace(m[0], `<code class="${cls}">${highlighted}</code>`);
    html = html.replace(block, newBlock);
  } catch (e) { /* keep raw */ }
}

// ---- Mermaid rendering (pre-render to inline SVG) --------------------------
let mermaidSvgs = [];
if (mermaidOn) {
  const jsdom = await import("jsdom");
  const { JSDOM } = jsdom;
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { pretendToBeVisual: true });

  // Set up ALL DOM globals BEFORE importing mermaid, because mermaid's bundle
  // captures DOMPurify / CSSStyleSheet / document / window references at
  // module load time. Setting them afterwards is too late.
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  try {
    Object.defineProperty(globalThis, "navigator", {
      value: dom.window.navigator, configurable: true,
    });
  } catch (e) { /* tolerated */ }

  // CSSStyleSheet polyfill (d3-css in mermaid needs it; jsdom lacks it).
  const CSSStyleSheetPolyfill = class CSSStyleSheet {
    constructor() { this.cssRules = []; }
    insertRule(rule, index) {
      const r = { cssText: rule, style: {} };
      if (index == null) this.cssRules.push(r);
      else this.cssRules.splice(index, 0, r);
      return this.cssRules.length - 1;
    }
    deleteRule(index) { this.cssRules.splice(index, 1); }
    get cssText() { return this.cssRules.map((r) => r.cssText).join("\n"); }
  };
  dom.window.CSSStyleSheet = CSSStyleSheetPolyfill;
  globalThis.CSSStyleSheet = CSSStyleSheetPolyfill;
  globalThis.getComputedStyle = dom.window.getComputedStyle.bind(dom.window);

// Node's global btoa/atob (from node:buffer) throw InvalidCharacterError on
// non-Latin-1 input. Mermaid's flowchart edge painter calls btoa() on edge
// labels that contain CJK text. Provide a UTF-8-safe implementation.
globalThis.btoa = (str) => Buffer.from(str, "utf8").toString("base64");
globalThis.atob = (b64) => Buffer.from(b64, "base64").toString("utf8");
dom.window.btoa = globalThis.btoa;
dom.window.atob = globalThis.atob;

  // DOMPurify: mermaid bundles its own copy but resolves `DOMPurify` from
  // module scope (= Node global) at load time. Provide it first.
  try {
    const domPurifyPkg = await import("dompurify");
    const dp = domPurifyPkg.default || domPurifyPkg;
    const domPurifyGlobal = (typeof dp === "function") ? dp(dom.window) : dp;
    globalThis.DOMPurify = domPurifyGlobal;
    dom.window.DOMPurify = domPurifyGlobal;
  } catch (e) {
    const noop = { sanitize: (s) => String(s), isSupported: true };
    globalThis.DOMPurify = noop;
    dom.window.DOMPurify = noop;
  }

  // SVG geometry stubs (jsdom has none; mermaid measures text widths).
  dom.window.SVGElement.prototype.getBBox = dom.window.SVGElement.prototype.getBBox ||
    function () {
      const w = this.getComputedTextLength ? this.getComputedTextLength() : 80;
      return { x: 0, y: 0, width: w, height: 20 };
    };
  if (dom.window.SVGTextElement) {
    dom.window.SVGTextElement.prototype.getComputedTextLength =
      dom.window.SVGTextElement.prototype.getComputedTextLength ||
      function () { return (this.textContent || "").length * 8; };
  }

  // NOW import mermaid (its bundle sees all the globals above).
  const mermaid = (await import("mermaid")).default;
  mermaid.initialize({
    startOnLoad: false,
    theme: "base",
    securityLevel: "loose",
    flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" },
    sequence: { useMaxWidth: false, actorMargin: 50, boxMargin: 10 },
  });


  const mermaidDivs = [...html.matchAll(/<div class="mermaid">([\s\S]*?)<\/div>/g)];
  for (let i = 0; i < mermaidDivs.length; i++) {
    const escapedInner = mermaidDivs[i][1];
    const raw = escapedInner
      .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
    try {
      const result = await mermaid.render(`mmd-${Date.now()}-${i}`, raw);
      const svgStr = typeof result === "string" ? result : result.svg || "";
      if (svgStr) {
        mermaidSvgs.push({ raw, svg: svgStr });
        // Replace the EXACT div that's in the HTML (escaped inner), not a
        // re-built one — the source content in `html` is HTML-escaped.
        const divHtml = `<div class="mermaid">${escapedInner}</div>`;
        html = html.replace(divHtml, `<div class="mermaid mermaid-rendered">${svgStr}</div>`);
      } else {
        throw new Error("mermaid.render returned empty result");
      }
    } catch (e) {
      const divHtml = `<div class="mermaid">${escapedInner}</div>`;
      const fallback = `<div class="mermaid mermaid-error"><strong>Mermaid 渲染失败:</strong><pre>${escapeHtml(String(e.message || e))}</pre></div>`;
      html = html.replace(divHtml, fallback);
      if (process.env.MDKIT_DEBUG) console.error("mermaid block", i, "raw=", raw.slice(0, 120), "err=", e.message || e);
    }
  }
}

// ---- wrap into standalone document ----------------------------------------
const h1 = html.match(/<h1[^>]*>(.*?)<\/h1>/i);
const title = h1 ? h1[1].replace(/<[^>]+>/g, "").trim() : "report";

const doc = `<!doctype html>
<html lang="zh-CN" data-theme="${theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@300;400;500;600;700;800&family=Noto+Sans+SC:wght@300;400;500;600;700;800;900&family=Noto+Serif+SC:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
/* app.css */
${appCss}

/* themes.css */
${themesCss}

/* standalone export overrides */
body { overflow: auto; }
.app { display: block; height: auto; }
.canvas { overflow: visible; padding: 24px; }
.report-page { max-width: 860px; margin: 0 auto; }
.mermaid-rendered svg { width: 100%; height: auto; }
</style>
</head>
<body>
<div class="app">
<div class="canvas">
<div class="report-page">
<div id="report-content">
${html}
</div>
</div>
</div>
</div>
</body>
</html>`;

writeFileSync(output, doc, "utf8");
console.log(`已生成: ${output}`);
console.log(`主题: ${theme} | Mermaid 块: ${mermaidSvgs.length}`);
