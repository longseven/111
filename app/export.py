"""把改编结果导出为 Word（.docx）。

公式策略：优先用 pandoc 把 $...$ LaTeX 转成 Word 原生公式（OMML）——它在
Word 公式编辑器里可编辑，且 MathType 可一键「Word 公式 → MathType」整篇转换。
未装 pandoc 时退回 python-docx，公式以可读纯文本呈现，并在文首给出提示。
"""
from __future__ import annotations

import re
import tempfile
from io import BytesIO
from pathlib import Path
from typing import List, Optional

from .schemas import AdaptedVariant, ParsedProblem


def pandoc_available() -> bool:
    try:
        import pypandoc

        pypandoc.get_pandoc_path()
        return True
    except Exception:  # noqa: BLE001
        return False


def build_markdown(
    parsed: Optional[ParsedProblem], variants: List[AdaptedVariant], title: str
) -> str:
    """组装 Markdown；其中 $...$ 数学公式会被 pandoc 转为 Word OMML 公式。"""
    out: List[str] = [f"# {title}", ""]
    if parsed is not None:
        out += [
            f"**原题**：{parsed.problem_text}",
            "",
            f"**知识点**：{'、'.join(parsed.knowledge_points)}　**学段**：{parsed.grade_band}",
            "",
        ]
    for i, v in enumerate(variants, 1):
        out += [
            f"## 第 {i} 题（难度：{v.difficulty}）",
            "",
            v.stem,
            "",
            f"**参考答案**：{v.answer}",
            "",
            f"**解析**：{v.solution}",
            "",
            f"**知识点**：{'、'.join(v.knowledge_points)}",
            "",
            f"**改编理由**：{v.adaptation_reason}",
            "",
        ]
    return "\n".join(out)


def _export_with_pandoc(md: str) -> bytes:
    import pypandoc

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "out.docx"
        pypandoc.convert_text(
            md, "docx", format="markdown+tex_math_dollars", outputfile=str(out)
        )
        return out.read_bytes()


def strip_latex(text: str) -> str:
    """无 pandoc 时的兜底：把 $...$ 中常见 LaTeX 转成可读纯文本。"""

    def repl(m: "re.Match[str]") -> str:
        s = m.group(1)
        s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"(\1)/(\2)", s)
        s = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", s)
        for a, b in (
            ("\\times", "×"), ("\\cdot", "·"), ("\\div", "÷"),
            ("\\leq", "≤"), ("\\le", "≤"), ("\\geq", "≥"), ("\\ge", "≥"),
            ("\\neq", "≠"), ("\\pm", "±"), ("\\sim", "~"), ("\\%", "%"),
        ):
            s = s.replace(a, b)
        s = re.sub(r"\\left|\\right", "", s)
        s = s.replace("{", "").replace("}", "")
        s = re.sub(r"\\[a-zA-Z]+", "", s)
        return s.strip()

    return re.sub(r"\$\$?(.+?)\$\$?", repl, text, flags=re.S)


def _export_with_docx(
    parsed: Optional[ParsedProblem], variants: List[AdaptedVariant], title: str
) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(
        "提示：在运行环境中安装 pandoc（或 pip 安装 pypandoc-binary）后重新导出，"
        "公式将变为可在 Word/MathType 中编辑的格式。"
    )
    if parsed is not None:
        doc.add_paragraph(f"原题：{strip_latex(parsed.problem_text)}")
        doc.add_paragraph(
            f"知识点：{'、'.join(parsed.knowledge_points)}　学段：{parsed.grade_band}"
        )
    for i, v in enumerate(variants, 1):
        doc.add_heading(f"第 {i} 题（难度：{v.difficulty}）", level=1)
        doc.add_paragraph(strip_latex(v.stem))
        doc.add_paragraph(f"参考答案：{strip_latex(v.answer)}")
        doc.add_paragraph(f"解析：{strip_latex(v.solution)}")
        doc.add_paragraph(f"知识点：{'、'.join(v.knowledge_points)}")
        doc.add_paragraph(f"改编理由：{v.adaptation_reason}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def export_docx(
    parsed: Optional[ParsedProblem],
    variants: List[AdaptedVariant],
    title: str = "改编题目",
) -> bytes:
    """返回 .docx 字节流。有 pandoc 走 OMML 公式，否则退回纯文本。"""
    if pandoc_available():
        try:
            return _export_with_pandoc(build_markdown(parsed, variants, title))
        except Exception:  # noqa: BLE001 — pandoc 失败则退回 python-docx
            pass
    return _export_with_docx(parsed, variants, title)
