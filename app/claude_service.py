"""封装对 Anthropic 的三次调用：解析、改编、校验。"""
from __future__ import annotations

from typing import Any, Dict, List

import anthropic

from .config import get_settings
from .prompts import ADAPT_SYSTEM, PARSE_SYSTEM, VERIFY_SYSTEM
from .schemas import (
    AdaptConditions,
    AdaptResult,
    ParsedProblem,
    ScopeCheckResult,
)


class RefusalError(RuntimeError):
    """模型出于安全原因拒绝。"""


class ConfigError(RuntimeError):
    """缺少必要配置（如 API key）。"""


def _client() -> anthropic.Anthropic:
    settings = get_settings()
    if not settings.has_api_key:
        raise ConfigError("未配置 ANTHROPIC_API_KEY，请在环境变量中设置后重试。")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _parse(messages: List[Dict[str, Any]], system: str, output_format):
    settings = get_settings()
    client = _client()
    response = client.messages.parse(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=system,
        messages=messages,
        output_format=output_format,
    )
    if getattr(response, "stop_reason", None) == "refusal":
        raise RefusalError("模型拒绝了该请求，请调整题目或条件后重试。")
    if response.parsed_output is None:
        raise RuntimeError("模型未返回可解析的结构化结果，请重试。")
    return response.parsed_output


def parse_problem(content_blocks: List[Dict[str, Any]]) -> ParsedProblem:
    """第 1 步：解析原题，建立不超纲边界。"""
    return _parse(
        messages=[{"role": "user", "content": content_blocks}],
        system=PARSE_SYSTEM,
        output_format=ParsedProblem,
    )


def adapt_problem(parsed: ParsedProblem, conditions: AdaptConditions) -> AdaptResult:
    """第 2 步：在边界内按条件改编。"""
    user_text = (
        "【原题解析】\n"
        + parsed.model_dump_json(indent=2)
        + "\n\n【改编条件】\n"
        + conditions.model_dump_json(indent=2)
        + f"\n\n请生成 {conditions.count} 道符合上述条件且不超纲的新题。"
    )
    return _parse(
        messages=[{"role": "user", "content": user_text}],
        system=ADAPT_SYSTEM,
        output_format=AdaptResult,
    )


def verify_in_scope(parsed: ParsedProblem, result: AdaptResult) -> ScopeCheckResult:
    """第 3 步：独立校验每道新题是否超纲。"""
    variants_payload = [
        {
            "index": i,
            "stem": v.stem,
            "knowledge_points": v.knowledge_points,
            "difficulty": v.difficulty,
        }
        for i, v in enumerate(result.variants)
    ]
    user_text = (
        "【原题解析（不超纲边界）】\n"
        + parsed.model_dump_json(indent=2)
        + "\n\n【待审核的改编题】\n"
        + AdaptResult(variants=result.variants).model_dump_json(indent=2)
        + "\n\n请逐题判定是否超纲，index 与上面顺序一致。"
    )
    # variants_payload 仅为可读性保留；正文已包含完整信息。
    _ = variants_payload
    return _parse(
        messages=[{"role": "user", "content": user_text}],
        system=VERIFY_SYSTEM,
        output_format=ScopeCheckResult,
    )
