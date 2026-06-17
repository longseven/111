"""LLM provider 抽象：Anthropic 官方 或 OpenAI 兼容代理。

对外只暴露 structured_completion(system, parts, output_format) -> Pydantic 实例，
按 settings.provider 分派到对应实现。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Type, TypeVar

from pydantic import BaseModel

from .config import get_settings
from .content import to_anthropic_content, to_openai_content

T = TypeVar("T", bound=BaseModel)


class RefusalError(RuntimeError):
    """模型出于安全原因拒绝。"""


class ConfigError(RuntimeError):
    """缺少必要配置（如 API key）。"""


def structured_completion(system: str, parts: List[Dict[str, Any]], output_format: Type[T]) -> T:
    settings = get_settings()
    if not settings.has_api_key:
        if settings.provider == "openai":
            raise ConfigError("未配置 OPENAI_API_KEY，请在环境变量中设置后重试。")
        raise ConfigError("未配置 ANTHROPIC_API_KEY，请在环境变量中设置后重试。")

    if settings.provider == "openai":
        return _openai_structured(system, parts, output_format)
    return _anthropic_structured(system, parts, output_format)


# ---------- Anthropic 官方 ----------
def _anthropic_structured(system: str, parts: List[Dict[str, Any]], output_format: Type[T]) -> T:
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    content = to_anthropic_content(parts)
    response = client.messages.parse(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
        output_format=output_format,
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise RefusalError("模型拒绝了该请求，请调整题目或条件后重试。")
    if response.parsed_output is None:
        raise RuntimeError("模型未返回可解析的结构化结果，请重试。")
    return response.parsed_output


# ---------- OpenAI 兼容代理 ----------
def _openai_structured(system: str, parts: List[Dict[str, Any]], output_format: Type[T]) -> T:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - 仅在未装 openai 时触发
        raise ConfigError("未安装 openai 库，请先执行 pip install openai。") from exc

    settings = get_settings()
    client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url or None)

    # 内容转换在 API 调用前完成；PDF 在此会抛 UnsupportedFileError（不被下方兜底吞掉）。
    content = to_openai_content(parts)

    # 第三方代理对 json_schema 严格模式支持不一，采用最通用方式：把 schema 写进提示，
    # 优先请求 json_object，失败则退回普通对话，再用 Pydantic 校验解析。
    schema = json.dumps(output_format.model_json_schema(), ensure_ascii=False)
    sys_msg = (
        system
        + "\n\n只输出一个 JSON 对象，必须严格符合以下 JSON Schema；"
        + "不要输出任何额外文字、解释或 Markdown 代码块：\n"
        + schema
    )
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": content},
    ]

    text = _openai_chat(client, settings.model, messages, settings.max_tokens)
    return output_format.model_validate_json(_extract_json(text))


def _openai_chat(client, model: str, messages: List[Dict[str, Any]], max_tokens: int) -> str:
    kwargs: Dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
    try:
        resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
    except Exception:  # noqa: BLE001 — 代理可能不支持 response_format，退回普通请求
        resp = client.chat.completions.create(**kwargs)

    choice = resp.choices[0]
    if getattr(choice.message, "refusal", None):
        raise RefusalError("模型拒绝了该请求，请调整题目或条件后重试。")
    content = choice.message.content
    if not content:
        raise RuntimeError("模型返回为空，请重试。")
    return content


def _extract_json(text: str) -> str:
    """从可能带 ``` 围栏或多余文字的回复中提取 JSON 对象。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t[:4].lower() == "json":
            t = t[4:].strip()
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]
    return t
