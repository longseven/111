# K12 数学题目改编系统

把一道现有数学题快速改编成若干新题：换数值、换情境、换题型、调难度，**保证不超纲**并给出**改编理由**，便于教研复用与审核。

系统是一个"视觉识别 + 受约束生成"的大模型应用，默认基于 Anthropic Claude（`claude-opus-4-8`），也可切换到任意 **OpenAI 兼容代理**（如 codexzh）走 Opus 4.8。

## 工作流程

```
上传截图/文件/文本
      │
      ▼
① 解析原题 ──► 识别 题干 / 知识点 / 学段 / 难度 / 题型   ← 这是"不超纲"的边界基准
      │
      ▼
② 输入改编条件（难度 / 题型 / 情境主题 / 改编方式 / 数量 / 严格不超纲开关）
      │
      ▼
③ 模型在边界内改编 ──► 每题含 答案 / 解析 / 知识点 / 改编理由 / 不超纲自检
      │
      ▼
④ 独立校验步骤（全新上下文）逐题判定是否超纲 ──► 前端绿色✓ / 红色✗ 徽章
```

不超纲的实现：以**第①步解析出的原题知识点与学段**作为边界，第②步生成时严格约束在该范围内，第④步再用一次独立调用客观复核，避免"自评合规"幻觉。

## 运行

### 一键启动（推荐）

```bash
# macOS / Linux
./run.sh
# Windows
run.bat
```

首次运行会自动建虚拟环境、装依赖，并从 `.env.example` 生成 `.env`；
**编辑 `.env` 填入你的 provider 与 API key**，再次运行即启动。应用会自动加载 `.env`。
浏览器打开 <http://127.0.0.1:8000>。

### 手动启动

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # 默认 provider 必填
uvicorn app.main:app --reload
```

## 切换 provider（Anthropic 官方 / OpenAI 兼容代理）

用环境变量 `LLM_PROVIDER` 切换，完整示例见 `.env.example`。

**A. Anthropic 官方（默认，支持 图片 + PDF + 文本）**

```bash
export LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
export ADAPT_MODEL=claude-opus-4-8        # 可选
```

**B. OpenAI 兼容代理（如 codexzh，走 Opus 4.8；支持 图片 + 文本，不支持 PDF）**

```bash
export LLM_PROVIDER=openai
export OPENAI_API_KEY=<代理给的 key>
export OPENAI_BASE_URL=https://api.codexzh.com/v1
export OPENAI_MODEL=claude-opus-4-8       # 用代理实际发布的模型 ID
```

OpenAI 模式可填任意代理支持的模型，例如 `claude-opus-4-8`、`gpt-5.5` 等——后端把模型名透传，切换只改 `OPENAI_MODEL`，无需改代码。

说明：
- OpenAI 模式用 chat/completions + 把 JSON Schema 写进提示来约束结构化输出，对第三方代理兼容性最好；优先请求 `json_object`，代理不支持时自动退回普通对话再解析。
- **参数自动兼容**：GPT-5 类模型要求 `max_completion_tokens` 而非 `max_tokens`，后端检测到该错误会自动切换，因此在 Claude 与 GPT-5 系列之间切换不会因该参数报错。
- OpenAI 模式下 PDF 暂不支持（各代理对文档输入实现不一），请改用图片或粘贴文本，或切回 Anthropic 模式。
- `OPENAI_MODEL` 要填代理目录里**实际存在**的模型 ID（先 `curl $OPENAI_BASE_URL/models` 查），不一定叫 `claude-opus-4-8` 或 `gpt-5.5`。

其余可选变量：`MAX_TOKENS`、`MAX_UPLOAD_BYTES`。

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 前端页面 |
| `GET` | `/api/health` | 健康检查（是否配置了 key、当前模型） |
| `POST` | `/api/generate` | `multipart/form-data`：`file`（可选）+ `text`（可选）+ `conditions`（JSON 串）→ 一步完成解析+改编+校验，返回 `{parsed, variants, scope_checks}` |
| `POST` | `/api/parse` | `multipart/form-data`：`file`（可选）+ `text`（可选）→ 返回 `ParsedProblem`（分步①，前端显示进度用） |
| `POST` | `/api/adapt` | JSON：`{parsed, conditions}` → 返回 `{variants}`（分步②） |
| `POST` | `/api/verify` | JSON：`{parsed, variants}` → 返回 `{scope_checks}`（分步③，不超纲校验） |
| `POST` | `/api/verify_answer` | JSON：`{variants}` → 返回 `{answer_checks}`（分步④，独立解题复核答案正确性） |
| `POST` | `/api/split` | `multipart/form-data`：`file`/`text` → 返回 `{problems}`（整卷拆分为多道题） |
| `POST` | `/api/export_paper` | JSON：`{groups, title, formula_mode}` → 返回 `.docx`（整卷组卷导出） |
| `POST` | `/api/export` | JSON：`{parsed, variants, title}` → 返回 `.docx`（公式为 Word 原生 OMML，MathType 兼容） |

支持的上传类型：图片（png/jpg/jpeg/webp/gif）、PDF、文本（txt/md），或直接粘贴文本。

## 导出 Word（公式可编辑 / MathType 兼容）

结果区可选「公式格式」后点「导出 Word」下载 `.docx`，两种模式：

- **可编辑公式（omml）**：公式以 **Word 原生公式（OMML）** 写入，可在 Word 公式编辑器中编辑；
  MathType 里点「Convert Equations → Word 公式转 MathType」可整篇转成 MathType 公式。
  依赖 pandoc，已由 `pypandoc-binary` 随依赖自带二进制，无需单独装。
  **Word 显示最佳；部分 WPS 因缺数学字体可能渲染不全**（文件本身正确）。
- **图片公式（image）**：用 matplotlib 把每个公式渲染成图片嵌入。**WPS 等任何软件都能正常显示、
  排版稳定**，代价是公式不可再编辑。模型常用的 `\le`/`\ge` 等缩写会自动归一化；个别无法渲染的
  公式自动退回可读纯文本。

说明：程序无法直接生成 MathType 私有的 OLE 公式对象（闭源格式无开放库可写）；OMML 是可程序化
生成、且 MathType 能一键转换的标准目标，图片模式则保证到处都能显示。

## 测试

```bash
# 离线单测（不打网络）：content block 构造 + schema 校验
pytest tests/test_smoke.py

# 接口冒烟（需 ANTHROPIC_API_KEY 与已启动的服务）
curl -F 'text=计算 3/4 + 1/6 的值。' http://127.0.0.1:8000/api/parse
```

## 目录

```
app/
  main.py           FastAPI 路由 + 静态托管
  config.py         环境变量配置（provider 切换）
  schemas.py        Pydantic 数据模型（结构化输出契约）
  content.py        文件/文本 → 中性部件 + Anthropic/OpenAI 双适配器
  prompts.py        解析 / 改编 / 校验 三段 system prompt
  llm.py            provider 抽象：Anthropic 官方 / OpenAI 兼容代理
  claude_service.py 三个环节封装（provider 无关）
static/             原生 HTML/CSS/JS 单页前端
tests/              离线单测
```
