"""面向模型结构化输出与 API 交互的数据模型。

每个面向模型的字段都带 description，作为隐式 schema 提示，
帮助模型产出符合预期的结构化结果。
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ---------- 第 1 步：解析原题 ----------
class ParsedProblem(BaseModel):
    """对原题的识别结果，构成"不超纲"的边界基准。"""

    problem_text: str = Field(description="从图片/文件/文本中识别出的完整题干（含已知条件与问题）。")
    knowledge_points: List[str] = Field(
        description="本题考查的数学知识点列表，尽量具体，例如['一元一次方程','行程问题']。"
    )
    grade_band: str = Field(description="本题所属的年级学段，例如'小学六年级'或'初中七年级'。")
    difficulty: str = Field(description="题目难度，取值为'易'、'中'或'难'之一。")
    problem_type: str = Field(description="题型，例如'选择题'、'填空题'、'解答题'、'应用题'。")


# ---------- 第 2 步：改编条件（前端表单 → 后端） ----------
class AdaptConditions(BaseModel):
    """用户填写的改编条件。"""

    difficulty_change: Literal["easier", "keep", "harder"] = Field(
        default="keep", description="难度调整方向：更简单/保持/更难。"
    )
    target_type: str = Field(
        default="keep",
        description="目标题型：'keep' 表示保持原题型，否则为目标题型如'选择题''应用题'。",
    )
    scenario_theme: str = Field(
        default="", description="情境/背景主题（自由文本，可空），例如'购物''行程''体育'。"
    )
    extra_instructions: str = Field(
        default="",
        description=(
            "用户用自然语言口述的改编要求（自由文本，可空），"
            "例如'改成关于篮球比赛的应用题，难度高一点，出3道'。在不超纲前提下尽量满足。"
        ),
    )
    change_mode: Literal["values", "scenario", "phrasing", "comprehensive"] = Field(
        default="values",
        description="改编方式：values=仅换数值，scenario=换情境，phrasing=换问法，comprehensive=综合。",
    )
    count: int = Field(default=2, ge=1, le=5, description="生成新题数量，1 到 5。")
    allow_extension: bool = Field(
        default=False,
        description="是否允许轻微拓展知识点；False 表示严格不超纲（默认）。",
    )
    grade_hint: str = Field(default="", description="可选的年级提示，用于辅助约束。")


# ---------- 第 2 步输出：改编结果 ----------
class AdaptedVariant(BaseModel):
    """一道改编后的新题。"""

    stem: str = Field(description="改编后的新题干。")
    answer: str = Field(description="参考答案（最终结果）。")
    solution: str = Field(description="解题步骤与解析。")
    knowledge_points: List[str] = Field(description="本新题考查的知识点列表。")
    difficulty: str = Field(description="新题难度，'易'/'中'/'难'。")
    adaptation_reason: str = Field(
        description="改编理由：逐条列出相对原题的具体改动，每条一行，格式「维度：原内容 → 新内容」（如'情境：行程 → 购物'）；只写真实改动，不写空泛套话。"
    )
    within_scope_note: str = Field(
        description="不超纲自检说明：解释本题为何仍在原题知识点与学段范围内。"
    )


class AdaptResult(BaseModel):
    variants: List[AdaptedVariant] = Field(description="改编生成的新题列表。")


# ---------- 第 3 步：独立校验 ----------
class ScopeCheck(BaseModel):
    """对单道改编题的不超纲判定。"""

    index: int = Field(description="对应改编题在列表中的序号，从 0 开始。")
    passed: bool = Field(description="是否仍在原题知识点与学段范围内（未超纲）。")
    reason: str = Field(description="判定理由；若未通过，需指出超纲之处。")


class ScopeCheckResult(BaseModel):
    checks: List[ScopeCheck] = Field(description="逐题的不超纲判定结果。")


# ---------- 组合返回 ----------
class AdaptResponse(BaseModel):
    variants: List[AdaptedVariant]
    scope_checks: List[ScopeCheck]


class AdaptRequest(BaseModel):
    parsed: ParsedProblem
    conditions: AdaptConditions


class VerifyRequest(BaseModel):
    parsed: ParsedProblem
    variants: List[AdaptedVariant]


# ---------- 答案正确性校验 ----------
class AnswerCheck(BaseModel):
    """对单道新题答案的独立复核结果。"""

    index: int = Field(description="对应改编题序号，从 0 开始。")
    correct: bool = Field(description="给定答案 given_answer 是否正确。")
    correct_answer: str = Field(description="独立解题得到的正确答案（用 LaTeX，$...$ 包裹公式）。")
    reason: str = Field(description="判断依据/解题要点；若不正确，指出错在哪。")


class AnswerCheckResult(BaseModel):
    checks: List[AnswerCheck] = Field(description="逐题的答案复核结果。")


class AnswerVerifyRequest(BaseModel):
    variants: List[AdaptedVariant]


class ExportRequest(BaseModel):
    parsed: Optional[ParsedProblem] = None
    variants: List[AdaptedVariant]
    title: str = "改编题目"
    formula_mode: Literal["omml", "image"] = Field(
        default="omml",
        description="公式格式：omml=Word 原生可编辑公式；image=渲染成图片（WPS 等任何软件都能显示，不可编辑）。",
    )
