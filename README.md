# K12 数学题目改编系统

把一道现有数学题快速改编成若干新题：换数值、换情境、换题型、调难度，**保证不超纲**并给出**改编理由**，便于教研复用与审核。

系统是一个"视觉识别 + 受约束生成"的大模型应用，基于 Anthropic Claude（`claude-opus-4-8`）。

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

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...      # 必填
uvicorn app.main:app --reload
```

浏览器打开 <http://127.0.0.1:8000>。

可选环境变量见 `.env.example`（`ADAPT_MODEL`、`MAX_TOKENS`、`MAX_UPLOAD_BYTES`）。

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
  config.py         环境变量配置
  schemas.py        Pydantic 数据模型（结构化输出契约）
  content.py        文件/文本 → Anthropic content block
  prompts.py        解析 / 改编 / 校验 三段 system prompt
  claude_service.py 三次模型调用封装
static/             原生 HTML/CSS/JS 单页前端
tests/              离线单测
```
