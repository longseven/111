"""三个环节的业务封装：解析、改编、校验。

provider 无关——具体走 Anthropic 还是 OpenAI 兼容代理由 llm.structured_completion 决定。
ConfigError / RefusalError 从 llm 重新导出，便于 main.py 统一捕获。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .content import text_part
from .llm import ConfigError, RefusalError, structured_completion
from .prompts import ADAPT_SYSTEM, ANSWER_VERIFY_SYSTEM, PARSE_SYSTEM, VERIFY_SYSTEM
from .schemas import (
    AdaptConditions,
    AdaptResult,
    AnswerCheckResult,
    ParsedProblem,
    ScopeCheckResult,
)

__all__ = [
    "ConfigError",
    "RefusalError",
    "parse_problem",
    "adapt_problem",
    "verify_in_scope",
    "verify_answer",
    "format_choices",
]

# 选项标记：单个大写字母 A-H 紧跟 . 或 ．，且前面不是字母/数字
_OPTION_MARKER = re.compile(r"(?<![A-Za-z0-9])([A-H])[.．]")


def format_choices(text: str) -> str:
    """选择题：把各选项（A. B. C. …）分别独立成行。

    仅当检测到 ≥3 个不同选项标记时才生效，避免误伤几何题里内联的点名
    （如「点 A、B、C」用顿号、且字母后无句点，不会匹配）。
    """
    if not text:
        return text
    letters = _OPTION_MARKER.findall(text)
    if len(set(letters)) < 3:
        return text
    out = re.sub(r"\s*(?<![A-Za-z0-9])([A-H][.．])", lambda m: "\n" + m.group(1), text)
    return out.lstrip("\n").rstrip()


def parse_problem(parts: List[Dict[str, Any]]) -> ParsedProblem:
    """第 1 步：解析原题，建立不超纲边界。parts 为中性内容部件。"""
    parsed = structured_completion(PARSE_SYSTEM, parts, ParsedProblem)
    parsed.problem_text = format_choices(parsed.problem_text)
    return parsed


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
    result = structured_completion(ADAPT_SYSTEM, [text_part(user_text)], AdaptResult)
    for v in result.variants:
        v.stem = format_choices(v.stem)
    return result


def verify_answer(result: AdaptResult) -> AnswerCheckResult:
    """独立解题复核：判断每道新题的答案是否正确（全新上下文，不依赖原解析）。"""
    payload = [
        {"index": i, "stem": v.stem, "given_answer": v.answer}
        for i, v in enumerate(result.variants)
    ]
    user_text = (
        "请独立解下列每道题，并判断各自的 given_answer 是否正确：\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return structured_completion(
        ANSWER_VERIFY_SYSTEM, [text_part(user_text)], AnswerCheckResult
    )


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
