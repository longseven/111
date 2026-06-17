"""离线单测：content block 构造与 schema 校验，不打网络。"""
from __future__ import annotations

import base64

import pytest

from app.content import (
    UnsupportedFileError,
    build_problem_blocks,
    file_to_block,
)
from app.schemas import (
    AdaptConditions,
    AdaptedVariant,
    AdaptResult,
    ParsedProblem,
    ScopeCheck,
    ScopeCheckResult,
)


# ---------- content blocks ----------
def test_image_block():
    block = file_to_block("题目.png", b"\x89PNG\r\n")
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(block["source"]["data"]) == b"\x89PNG\r\n"


def test_jpg_maps_to_jpeg():
    block = file_to_block("a.JPG", b"data")
    assert block["source"]["media_type"] == "image/jpeg"


def test_pdf_block():
    block = file_to_block("paper.pdf", b"%PDF-1.7")
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"


def test_text_file_block():
    block = file_to_block("q.txt", "计算 1+1".encode("utf-8"))
    assert block["type"] == "text"
    assert "计算" in block["text"]


def test_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        file_to_block("a.docx", b"x")


def test_build_blocks_text_only():
    blocks = build_problem_blocks(None, None, "计算 3/4 + 1/6")
    assert any("3/4" in b.get("text", "") for b in blocks)


def test_build_blocks_requires_input():
    with pytest.raises(ValueError):
        build_problem_blocks(None, None, "   ")


def test_build_blocks_file_and_text():
    blocks = build_problem_blocks("q.png", b"img", "补充说明")
    types = [b["type"] for b in blocks]
    assert "image" in types
    # 文本引导 + 文件 + 文本补充
    assert types.count("text") >= 1


# ---------- schema 往返 ----------
def test_parsed_problem_roundtrip():
    p = ParsedProblem(
        problem_text="计算 3/4 + 1/6 的值。",
        knowledge_points=["分数加法", "通分"],
        grade_band="小学五年级",
        difficulty="易",
        problem_type="计算题",
    )
    data = p.model_dump()
    assert ParsedProblem(**data).knowledge_points == ["分数加法", "通分"]


def test_adapt_conditions_defaults_and_bounds():
    c = AdaptConditions()
    assert c.count == 2
    assert c.allow_extension is False
    with pytest.raises(ValueError):
        AdaptConditions(count=9)


def test_adapt_result_roundtrip():
    v = AdaptedVariant(
        stem="计算 2/3 + 1/4。",
        answer="11/12",
        solution="通分得 8/12 + 3/12 = 11/12。",
        knowledge_points=["分数加法"],
        difficulty="易",
        adaptation_reason="仅替换数值，题型与知识点不变。",
        within_scope_note="仍为分数加法，未超出小学五年级范围。",
    )
    res = AdaptResult(variants=[v])
    assert AdaptResult(**res.model_dump()).variants[0].answer == "11/12"


def test_scope_check_result():
    r = ScopeCheckResult(checks=[ScopeCheck(index=0, passed=True, reason="知识点一致。")])
    assert r.checks[0].passed is True
