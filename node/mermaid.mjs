#!/usr/bin/env node
/**
 * mdkit Mermaid renderer — render a single Mermaid source file to SVG.
 *
 * Reuses the same jsdom + mermaid setup as node/render.mjs so Mermaid charts
 * rendered here look identical to those in the HTML output.
 *
 * Usage:
 *   node node/mermaid.mjs <input.mmd> [output.svg] [--theme base] [--width 6in]
 *
 * Output SVG can be embedded in docx via pandoc image syntax:
 *   ![](chart.svg){width=6in}
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

// ---- argument parsing ------------------------------------------------------
const argv = process.argv.slice(2);
let input = null;
let output = null;
let theme = "base";
let width = null;

for (let i = 0; i < argv.length; i++) {
  const a = argv[i];
  if (a === "--theme") theme = argv[++i];
  else if (a === "--output" || a === "-o") output = argv[++i];
  else if (a === "--width") width = argv[++i];
  else if (!a.startsWith("-") && input === null) input = a;
  else if (!a.startsWith("-") && output === null) output = a;
}
if (!input) {
  console.error("用法: node mermaid.mjs <input.mmd> [output.svg] [--theme base] [--width 6in]");
  process.exit(1);
}
if (!output) output = input.replace(/\.[^.]+$/, "") + ".svg";

const mermaidSrc = readFileSync(input, "utf8");

// ---- DOM setup for mermaid (mirrors node/render.mjs) -----------------------
import { JSDOM } from "jsdom";
const dom = new JSDOM("<!doctype html><html><body></body></html>", { pretendToBeVisual: true });

globalThis.document = dom.window.document;
globalThis.window = dom.window;
try {
  Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
} catch (e) { /* tolerated */ }

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
globalThis.btoa = (str) => Buffer.from(str, "utf8").toString("base64");
globalThis.atob = (b64) => Buffer.from(b64, "base64").toString("utf8");
dom.window.btoa = globalThis.btoa;
dom.window.atob = globalThis.atob;
dom.window.SVGElement.prototype.getBBox = dom.window.SVGElement.prototype.getBBox ||
  function () { const w = this.getComputedTextLength ? this.getComputedTextLength() : 80; return { x: 0, y: 0, width: w, height: 20 }; };
if (dom.window.SVGTextElement) {
  dom.window.SVGTextElement.prototype.getComputedTextLength =
    dom.window.SVGTextElement.prototype.getComputedTextLength ||
    function () { return (this.textContent || "").length * 8; };
}

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

// ---- render mermaid --------------------------------------------------------
const mermaid = (await import("mermaid")).default;
mermaid.initialize({
  startOnLoad: false,
  theme: theme,
  securityLevel: "loose",
  flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" },
  sequence: { useMaxWidth: false, actorMargin: 50, boxMargin: 10 },
});

try {
  const { svg } = await mermaid.render(`mmd-${Date.now()}`, mermaidSrc);
  // Apply explicit width if requested (pandoc honors {width=...} on images).
  writeFileSync(output, svg, "utf8");
  console.log(`已生成: ${output}`);
} catch (e) {
  console.error(`Mermaid 渲染失败: ${e.message || e}`);
  process.exit(1);
}
