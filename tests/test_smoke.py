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
from app.llm import _extract_json, _openai_chat
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


# ---------- OpenAI 参数兼容回退 ----------
class _StubMessage:
    def __init__(self, content):
        self.content = content
        self.refusal = None


class _StubResp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": _StubMessage(content)})()]


class _StubCompletions:
    def __init__(self, behavior):
        self.behavior = behavior
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.behavior(kwargs)


class _StubClient:
    def __init__(self, behavior):
        self.chat = type("Chat", (), {"completions": _StubCompletions(behavior)})()


def test_openai_switches_to_max_completion_tokens():
    def behavior(kwargs):
        if "max_tokens" in kwargs:
            raise RuntimeError("Unsupported parameter: 'max_tokens'. Use 'max_completion_tokens' instead.")
        return _StubResp('{"ok": 1}')

    client = _StubClient(behavior)
    out = _openai_chat(client, "gpt-5.5", [{"role": "user", "content": "x"}], 100)
    assert out == '{"ok": 1}'
    calls = client.chat.completions.calls
    assert len(calls) == 2
    assert "max_completion_tokens" in calls[1] and "max_tokens" not in calls[1]


def test_openai_drops_response_format_when_unsupported():
    def behavior(kwargs):
        if "response_format" in kwargs:
            raise RuntimeError("response_format is not supported by this model")
        return _StubResp('{"ok": 1}')

    client = _StubClient(behavior)
    out = _openai_chat(client, "some-model", [{"role": "user", "content": "x"}], 100)
    assert out == '{"ok": 1}'
    calls = client.chat.completions.calls
    assert len(calls) == 2 and "response_format" not in calls[1]


def test_openai_real_error_propagates():
    def behavior(kwargs):
        raise RuntimeError("invalid api key")

    client = _StubClient(behavior)
    with pytest.raises(RuntimeError, match="invalid api key"):
        _openai_chat(client, "m", [{"role": "user", "content": "x"}], 100)


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
    assert c.extra_instructions == ""  # 自由描述默认空
    with pytest.raises(ValueError):
        AdaptConditions(count=9)


def test_adapt_conditions_extra_instructions():
    c = AdaptConditions(extra_instructions="改成篮球应用题，难一点")
    assert "篮球" in c.model_dump_json()


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


# ---------- Word 导出 ----------
def _sample_variants():
    return [
        AdaptedVariant(
            stem="已知 $X \\sim B(4,p)$，求 $P(X=2)=\\frac{3}{8}$ 是否成立。",
            answer="成立",
            solution="$P(X=2)=C_4^2(\\frac{1}{2})^2(\\frac{1}{2})^2=\\frac{3}{8}$。",
            knowledge_points=["二项分布"],
            difficulty="易",
            adaptation_reason="仅改数值。",
            within_scope_note="未超纲。",
        )
    ]


def test_build_markdown_contains_math_and_fields():
    from app.export import build_markdown

    md = build_markdown(None, _sample_variants(), "改编题目")
    assert "# 改编题目" in md
    assert "\\frac{3}{8}" in md  # LaTeX 公式原样进入 markdown
    assert "改编理由" in md


def test_strip_latex_fallback():
    from app.export import strip_latex

    out = strip_latex("结果为 $\\frac{3}{8}$ 且 $a \\le b$")
    assert "(3)/(8)" in out and "≤" in out and "$" not in out


def test_export_docx_is_valid_docx():
    import io
    import zipfile

    from app.export import export_docx

    data = export_docx(None, _sample_variants(), "改编题目")
    assert data[:2] == b"PK"  # zip 魔数
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        assert "word/document.xml" in names
        xml = z.read("word/document.xml").decode("utf-8")
    # 装了 pandoc 则应含 OMML 公式；否则为纯文本兜底，至少含题目内容
    from app.export import pandoc_available

    if pandoc_available():
        assert "oMath" in xml
    else:
        assert "改编题目" in xml or "B(4" in xml


def test_export_docx_image_mode_embeds_pictures():
    import io
    import zipfile

    from app.export import export_docx

    data = export_docx(None, _sample_variants(), "改编题目", formula_mode="image")
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
    # 图片模式应嵌入公式图片
    assert any(n.startswith("word/media/") for n in names)


def test_render_math_png_handles_le_abbrev():
    from app.export import _render_math_png

    png = _render_math_png(r"P(\frac{3}{2} \le X \le \frac{5}{2}) = \frac{3}{8}")
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_format_choices_splits_options():
    from app.claude_service import format_choices

    out = format_choices("下列说法错误的是（） A. p=1/2 B. D(X)=1 C. P=3/8 D. E=2")
    lines = [ln.strip() for ln in out.split("\n")]
    assert any(ln.startswith("A.") for ln in lines)
    assert any(ln.startswith("D.") for ln in lines)
    assert sum(ln[:2] in ("A.", "B.", "C.", "D.") for ln in lines) == 4


def test_format_choices_leaves_geometry_points():
    from app.claude_service import format_choices

    s = "在三角形 ABC 中，点 D、E、F 分别是中点，求 AD 的长。"
    assert format_choices(s) == s  # 无 A. 式句点标记，不误伤


def test_export_image_mode_line_breaks():
    import io
    import zipfile

    from app.export import export_docx

    v = _sample_variants()[0]
    v.stem = "下列错误的是（）\nA. $p=1$\nB. $q=2$\nC. $r=3$\nD. $s=4$"
    data = export_docx(None, [v], "t", formula_mode="image")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "<w:br/>" in xml or "<w:br />" in xml


# ---------- .env 加载 ----------
def test_load_dotenv(tmp_path):
    import os

    from app.config import _load_dotenv

    f = tmp_path / ".env"
    f.write_text(
        '# 注释行\nFOO_TEST_KEY=bar\nQUOTED_KEY="baz"\nEMPTY_LINE_BELOW=\n',
        encoding="utf-8",
    )
    try:
        _load_dotenv(f)
        assert os.environ.get("FOO_TEST_KEY") == "bar"
        assert os.environ.get("QUOTED_KEY") == "baz"  # 引号被去掉
        # 已存在的环境变量不被覆盖
        os.environ["FOO_TEST_KEY"] = "keep"
        _load_dotenv(f)
        assert os.environ["FOO_TEST_KEY"] == "keep"
    finally:
        for k in ("FOO_TEST_KEY", "QUOTED_KEY", "EMPTY_LINE_BELOW"):
            os.environ.pop(k, None)
