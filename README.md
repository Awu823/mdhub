# mdhub — 统一 Markdown 转换工具（mdkit）

一个统一的 Markdown/文档转换 CLI，内置多种转换后端（md2pptx / typst / Marp / Node 等）。
个别格式依赖可选的外部**系统**工具（pandoc / typst / 浏览器），见「系统依赖」。

## 安装

```bat
cd mdhub
build.bat
```
`build.bat` 会：建 `.venv` → 装 Python 依赖 → 装 Node 依赖 → 跑 `doctor`。

手动：
```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd node && npm install && cd ..
```

## 系统依赖（可选，按需安装）

`build.bat` 只装 Python + Node 依赖；**系统级外部工具需单独安装**。运行 `bin\mdhub.bat doctor`
会逐项探测并提示缺失——缺什么装什么即可。

| 子命令 | 外部工具 | 缺失时 | 安装 |
|---|---|---|---|
| `docx` | pandoc | 转换失败并提示 | `winget install pandoc` |
| `pdf` | pandoc + typst（或 MiKTeX 提供 xelatex） | 失败并提示 | `winget install pandoc` + `winget install Typst.Typst` |
| `html` | node | 自动降级基础渲染 | `winget install OpenJS.NodeJS` |
| `pptx` | python-pptx（内置 md2pptx）/ node + 浏览器 | auto 自动切换后端 | `pip install python-pptx`；Marp 需 Node + 浏览器 |
| `to-md` | markitdown（pip，`build.bat` 已装） | 子命令报缺依赖 | `pip install markitdown[all]` |

> 说明：`pptx` 默认走**内置 md2pptx**（python-pptx，无需浏览器），`--backend marp` 才需要 Node + 浏览器；
> `pdf` 默认走 **typst**（无需 LaTeX），`--engine xelatex` 才需要 MiKTeX + Eisvogel 模板。

## 使用

```bat
bin\mdhub.bat doctor                       环境探测
bin\mdhub.bat to-md  in.docx              任意文件 → Markdown（逆向）
bin\mdhub.bat docx  in.md                 Markdown → 企业模板 docx
bin\mdhub.bat html  in.md -t midnight     Markdown → 独立 HTML（Node）
bin\mdhub.bat pptx  in.md                 Markdown → PPT（md2pptx；--backend marp 切 Marp）
bin\mdhub.bat pdf   in.md                 Markdown → PDF（typst；--engine xelatex 用 Eisvogel）
bin\mdhub.bat multi in.md --to docx,html,pdf
bin\mdhub.bat pipe  in.docx --to md,docx  链式：docx→md→docx
bin\mdhub.bat sanitize templates\template.docx   模板脱敏
```

### 不使用 .bat，直接运行 Python

Windows 下不想走 `bin\mdhub.bat`，直接用 Python 跑（三种方式任选）——

> ⚠️ **必须从 `mdhub/` 根目录运行**（即包含 `mdkit/` 包目录的父目录）：
> `python -m mdkit` 会从**当前目录**查找 `mdkit` 包，从子目录或上级目录都会报
> `No module named mdkit`。`bin\mdhub.bat` 内部已 `cd` 到根目录，所以它从任何位置调用都没问题。

```bat
:: 先切到 mdhub 根目录（关键！换成你的实际 mdhub 路径，不要写死用户目录）
cd <mdhub_root>

:: ① 用 .venv 里的 Python（推荐，依赖齐全，无需激活）
.venv\Scripts\python.exe -m mdkit doctor
.venv\Scripts\python.exe -m mdkit docx "data\input\my.md" -o data\output\my.docx

:: ② 激活 .venv 后用 python（省去完整路径）
.venv\Scripts\activate
python -m mdkit pdf "data\input\my.md"

:: ③ 系统 Python（前提：已 pip install -r requirements.txt）
python -m mdkit to-md "in.docx" -o data\output\out.md
```

跨平台（Linux/macOS）：`python -m mdkit <子命令> ...`（无构建脚本，需自行安装 Python/Node 依赖）

> ⚠️ **必须走 `python -m mdkit` 入口**。`mdkit` 包通过 `__main__.py`→`cli.py` 做路由和参数解析，
> 各子命令模块（如 `mdkit/modules/md_to_pdf.py`）只提供 `add_subparser()`/`run()`，
> **没有独立脚本入口**，直接 `python mdkit/modules/md_to_pdf.py ...` 是跑不起来的。
> 参数（含含空格的文件名）记得加引号：`python -m mdkit pdf "My Report.md"`。

## 子命令一览

| 子命令 | 模块 | 后端 | 必需依赖 |
|---|---|---|---|
| `to-md` | mdkit/modules/to_md.py | markitdown | markitdown |
| `docx` | mdkit/modules/md_to_docx.py | python-docx + pandoc | python-docx + pandoc |
| `sanitize` | mdkit/modules/docx_sanitize.py | python-docx | python-docx |
| `html` | mdkit/modules/md_to_html.py | node | node（缺则基础渲染） |
| `pptx` | mdkit/modules/md_to_pptx.py | md2pptx（内置）/ Marp | npx + 浏览器 |
| `pdf` | mdkit/modules/md_to_pdf.py | typst / Eisvogel | pandoc + xelatex/typst |
| `multi` | mdkit/modules/md_to_multi.py | 组合 | 上述对应 |
| `pipe` | mdkit/modules/pipeline.py | 组合 | 上述对应 |
| `doctor` | mdkit/modules/doctor.py | — | 无 |

## 目录结构

```
mdhub/
├─ bin/mdhub.bat         一键入口
├─ build.bat             构建脚本
├─ requirements.txt      Python 依赖
├─ mdkit/
│  ├─ cli.py            argparse 路由（只分发，不耦合）
│  ├─ registry.py       子命令注册表
│  ├─ common.py         配置/路径公共工具
│  └─ modules/          各独立子命令模块
├─ node/
│  ├─ package.json      Node 渲染器依赖
│  └─ render.mjs        md → 独立 HTML（复用 assets/html）
├─ templates/           docx 企业模板（可替换）
├─ assets/
│  ├─ md2pptx/          md2pptx 后端（python-pptx，内置）
│  └─ html/            css + vendor + index.html（浏览器预览）
├─ config/mkit.json     全局默认
└─ data/                 数据目录（输入/输出）
   ├─ input/            约定输入目录
   └─ output/           统一输出目录
```

## 独立性保证

- 每个子命令一个模块，`cli.py` 只做路由；某模块挂了不影响其他命令。
- Python（.venv）与 Node（node/node_modules）依赖隔离。
- 可选后端（markitdown/texlive/Marp）lazy import + `doctor` 探测，缺失不影响核心。
- 资产放 `assets/`，各模块只读自己的子目录。

---

## 已验证（2026-11-25 更新）

| 子命令 | 结果 | 说明 |
|---|---|---|
| `docx` | ✅ | 生成企业模板 docx，封面/表格/标题编号正常（15 tables / 19 headings，封面自动检测） |
| `html` | ✅ | Node 渲染独立 HTML，Mermaid 预渲染为内联 SVG（0 错误），语法高亮生效，7 主题 |
| `to-md` | ✅ | docx → md 逆向提取（38.7 KB），封面表结构保留 |
| `sanitize` | ✅ | 模板脱敏（19 标题保留，封面/历史置占位符） |
| `multi` | ✅ | docx,html,pdf 全链路一次成功（退出码 0，无 traceback） |
| `pipe` | ✅ | md→docx 链成功；docx→md→docx 链 step1 成功 |
| `doctor` | ✅ | **7 项探测全 OK**（pandoc/node/browser/typst/markitdown/docx/lxml） |
| `pdf` | ✅ | **typst 引擎**：`DS_CN_MA_...pdf`（269.9 KB，合法 `%PDF-`，含页面） |
| `pptx` | ✅ | **md2pptx 后端**：`slide-test.pptx`（6 张幻灯片，标题/代码/表格在） |

**已装后端**（2026-11-25）
- `typst` 0.15.1（winget）→ 启用 `pdf`（pandoc `--pdf-engine=typst`）
- `python-pptx` 1.0.2 → 启用 `pptx`（md2pptx 后端）
- **markitdown 0.1.9** 已装入 `mdhub/.venv`（Python 3.14.8）→ `to-md` 开箱即用
- Chrome 已存在 → doctor 已识别（Marp 可用但不稳定，默认 md2pptx）

**环境提示**（`mdhub doctor` 会逐项列出）：
- `pdf`：已有 typst；可选装 MiKTeX 以获得 xelatex + Eisvogel 模板（更精美排版，非必需）
- `pptx`：已有 md2pptx；Marp 需浏览器（本机有 Chrome）
- `to-md`：已有 markitdown 0.1.9，开箱即用
