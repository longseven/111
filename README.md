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
| `POST` | `/api/parse` | `multipart/form-data`：`file`（可选）+ `text`（可选）→ 返回 `ParsedProblem` |
| `POST` | `/api/adapt` | JSON：`{parsed, conditions}` → 返回 `{variants, scope_checks}` |

支持的上传类型：图片（png/jpg/jpeg/webp/gif）、PDF、文本（txt/md），或直接粘贴文本。

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
