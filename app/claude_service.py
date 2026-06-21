"""三个环节的业务封装：解析、改编、校验。

provider 无关——具体走 Anthropic 还是 OpenAI 兼容代理由 llm.structured_completion 决定。
ConfigError / RefusalError 从 llm 重新导出，便于 main.py 统一捕获。
"""
from __future__ import annotations

from typing import Any, Dict, List

from .content import text_part
from .llm import ConfigError, RefusalError, structured_completion
from .prompts import ADAPT_SYSTEM, PARSE_SYSTEM, VERIFY_SYSTEM
from .schemas import (
    AdaptConditions,
    AdaptResult,
    ParsedProblem,
    ScopeCheckResult,
)

__all__ = [
    "ConfigError",
    "RefusalError",
    "parse_problem",
    "adapt_problem",
    "verify_in_scope",
]


def parse_problem(parts: List[Dict[str, Any]]) -> ParsedProblem:
    """第 1 步：解析原题，建立不超纲边界。parts 为中性内容部件。"""
    return structured_completion(PARSE_SYSTEM, parts, ParsedProblem)


def adapt_problem(parsed: ParsedProblem, conditions: AdaptConditions) -> AdaptResult:
    """第 2 步：在边界内按条件改编。"""
    user_text = (
        "【原题解析】\n"
        + parsed.model_dump_json(indent=2)
        + "\n\n【改编条件】\n"
        + conditions.model_dump_json(indent=2)
        + f"\n\n请生成 {conditions.count} 道符合上述条件且不超纲的新题。"
    )
    if conditions.extra_instructions.strip():
        user_text += (
            "\n请特别注意用户口述的额外要求："
            + conditions.extra_instructions.strip()
            + "（在不超纲前提下尽量满足）。"
        )
    return structured_completion(ADAPT_SYSTEM, [text_part(user_text)], AdaptResult)


def verify_in_scope(parsed: ParsedProblem, result: AdaptResult) -> ScopeCheckResult:
    """第 3 步：独立校验每道新题是否超纲。"""
    user_text = (
        "【原题解析（不超纲边界）】\n"
        + parsed.model_dump_json(indent=2)
        + "\n\n【待审核的改编题】\n"
        + result.model_dump_json(indent=2)
        + "\n\n请逐题判定是否超纲，index 与上面顺序一致。"
    )
    return structured_completion(VERIFY_SYSTEM, [text_part(user_text)], ScopeCheckResult)
