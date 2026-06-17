"""离线单测：中性部件构造、provider 适配器与 schema 校验，不打网络。"""
from __future__ import annotations

import base64

import pytest

from app.content import (
    UnsupportedFileError,
    build_problem_parts,
    file_to_part,
    text_part,
    to_anthropic_content,
    to_openai_content,
)
from app.llm import _extract_json
from app.schemas import (
    AdaptConditions,
    AdaptedVariant,
    AdaptResult,
    ParsedProblem,
    ScopeCheck,
    ScopeCheckResult,
)


# ---------- 中性部件 ----------
def test_image_part():
    part = file_to_part("题目.png", b"\x89PNG\r\n")
    assert part["kind"] == "image"
    assert part["media_type"] == "image/png"
    assert base64.standard_b64decode(part["data_b64"]) == b"\x89PNG\r\n"


def test_jpg_maps_to_jpeg():
    assert file_to_part("a.JPG", b"data")["media_type"] == "image/jpeg"


def test_pdf_part():
    part = file_to_part("paper.pdf", b"%PDF-1.7")
    assert part["kind"] == "pdf"


def test_text_file_part():
    part = file_to_part("q.txt", "计算 1+1".encode("utf-8"))
    assert part["kind"] == "text" and "计算" in part["text"]


def test_unsupported_extension():
    with pytest.raises(UnsupportedFileError):
        file_to_part("a.docx", b"x")


def test_build_parts_text_only():
    parts = build_problem_parts(None, None, "计算 3/4 + 1/6")
    assert any("3/4" in p.get("text", "") for p in parts)


def test_build_parts_requires_input():
    with pytest.raises(ValueError):
        build_problem_parts(None, None, "   ")


# ---------- 适配器 ----------
def test_anthropic_adapter():
    parts = [text_part("题"), file_to_part("a.png", b"img"), file_to_part("d.pdf", b"%PDF")]
    blocks = to_anthropic_content(parts)
    types = [b["type"] for b in blocks]
    assert types == ["text", "image", "document"]
    assert blocks[1]["source"]["type"] == "base64"
    assert blocks[2]["source"]["media_type"] == "application/pdf"


def test_openai_adapter_image():
    blocks = to_openai_content([text_part("题"), file_to_part("a.png", b"img")])
    assert blocks[0]["type"] == "text"
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_adapter_rejects_pdf():
    with pytest.raises(UnsupportedFileError):
        to_openai_content([file_to_part("d.pdf", b"%PDF")])


# ---------- JSON 提取 ----------
def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == '{"a": 1}'


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_extract_json_with_prose():
    assert _extract_json('结果如下：{"a": 1} 完毕') == '{"a": 1}'


# ---------- schema 往返 ----------
def test_parsed_problem_roundtrip():
    p = ParsedProblem(
        problem_text="计算 3/4 + 1/6 的值。",
        knowledge_points=["分数加法", "通分"],
        grade_band="小学五年级",
        difficulty="易",
        problem_type="计算题",
    )
    assert ParsedProblem(**p.model_dump()).knowledge_points == ["分数加法", "通分"]


def test_adapt_conditions_defaults_and_bounds():
    c = AdaptConditions()
    assert c.count == 2 and c.allow_extension is False
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
