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
            md,
            "docx",
            format="markdown+tex_math_dollars+hard_line_breaks",
            outputfile=str(out),
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

    def add_lines(label: str, text: str) -> None:
        p = doc.add_paragraph()
        if label:
            p.add_run(label).bold = True
        for li, line in enumerate(text.split("\n")):
            if li > 0:
                p.add_run().add_break()
            p.add_run(strip_latex(line))

    doc = Document()
    doc.add_heading(title, level=0)
    doc.add_paragraph(
        "提示：在运行环境中安装 pandoc（或 pip 安装 pypandoc-binary）后重新导出，"
        "公式将变为可在 Word/MathType 中编辑的格式。"
    )
    if parsed is not None:
        add_lines("原题：", parsed.problem_text)
        doc.add_paragraph(
            f"知识点：{'、'.join(parsed.knowledge_points)}　学段：{parsed.grade_band}"
        )
    for i, v in enumerate(variants, 1):
        doc.add_heading(f"第 {i} 题（难度：{v.difficulty}）", level=1)
        add_lines("", v.stem)
        add_lines("参考答案：", v.answer)
        add_lines("解析：", v.solution)
        doc.add_paragraph(f"知识点：{'、'.join(v.knowledge_points)}")
        doc.add_paragraph(f"改编理由：{v.adaptation_reason}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def export_docx(
    parsed: Optional[ParsedProblem],
    variants: List[AdaptedVariant],
    title: str = "改编题目",
    formula_mode: str = "omml",
) -> bytes:
    """返回 .docx 字节流。

    formula_mode:
    - "omml"  ：公式为 Word 原生可编辑公式（pandoc；MathType 可转换）。Word 显示最佳。
    - "image" ：公式渲染成图片嵌入（matplotlib）。WPS 等任何软件都能正常显示，但不可编辑。
    无 pandoc 时 omml 模式退回纯文本。
    """
    # 导出前对题干/选项做分行规整，兼容生成时未分行的（含旧）数据
    from .claude_service import format_choices

    if parsed is not None:
        parsed = parsed.model_copy(
            update={"problem_text": format_choices(parsed.problem_text)}
        )
    variants = [v.model_copy(update={"stem": format_choices(v.stem)}) for v in variants]

    if formula_mode == "image":
        return _export_with_images(parsed, variants, title)
    if pandoc_available():
        try:
            return _export_with_pandoc(build_markdown(parsed, variants, title))
        except Exception:  # noqa: BLE001 — pandoc 失败则退回 python-docx
            pass
    return _export_with_docx(parsed, variants, title)


# ---------- 图片公式模式 ----------
def _normalize_latex(s: str) -> str:
    """把模型常用的 LaTeX 缩写改成 matplotlib mathtext 认的全名。"""
    s = re.sub(r"\\le(?![a-zA-Z])", r"\\leq", s)
    s = re.sub(r"\\ge(?![a-zA-Z])", r"\\geq", s)
    s = re.sub(r"\\ne(?![a-zA-Z])", r"\\neq", s)
    return s


def _render_math_png(latex: str) -> Optional[bytes]:
    """用 matplotlib 把单个 LaTeX 公式渲染成 PNG；失败返回 None。线程安全（不用 pyplot）。"""
    try:
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.figure import Figure

        fig = Figure()
        FigureCanvasAgg(fig)
        fig.text(0.0, 0.0, f"${_normalize_latex(latex)}$", fontsize=12)
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", pad_inches=0.03)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 — 该公式渲染失败，交由上层退回纯文本
        return None


def _split_segments(text: str):
    """把含 $...$ 的文本切成 [(kind, content)]，kind ∈ {'text','math'}。"""
    parts = re.split(r"(\$\$.+?\$\$|\$.+?\$)", text, flags=re.S)
    segs = []
    for p in parts:
        if not p:
            continue
        if p.startswith("$$") and p.endswith("$$"):
            segs.append(("math", p[2:-2]))
        elif p.startswith("$") and p.endswith("$"):
            segs.append(("math", p[1:-1]))
        else:
            segs.append(("text", p))
    return segs


def _add_rich_paragraph(doc, label: str, text: str) -> None:
    """新增一个段落：可选加粗 label，正文里的 $...$ 公式渲染成行内图片，失败退回纯文本。"""
    from PIL import Image
    from docx.shared import Inches

    p = doc.add_paragraph()
    if label:
        run = p.add_run(label)
        run.bold = True
    for li, line in enumerate(text.split("\n")):
        if li > 0:
            p.add_run().add_break()  # 选择题选项等：另起一行
        for kind, content in _split_segments(line):
            if kind == "text":
                p.add_run(content)
                continue
            png = _render_math_png(content)
            if png:
                w, h = Image.open(BytesIO(png)).size
                p.add_run().add_picture(BytesIO(png), height=Inches(h / 200))
            else:
                p.add_run(strip_latex("$" + content + "$"))


def _export_with_images(
    parsed: Optional[ParsedProblem], variants: List[AdaptedVariant], title: str
) -> bytes:
    from docx import Document

    doc = Document()
    doc.add_heading(title, level=0)
    if parsed is not None:
        _add_rich_paragraph(doc, "原题：", parsed.problem_text)
        doc.add_paragraph(
            f"知识点：{'、'.join(parsed.knowledge_points)}　学段：{parsed.grade_band}"
        )
    for i, v in enumerate(variants, 1):
        doc.add_heading(f"第 {i} 题（难度：{v.difficulty}）", level=1)
        _add_rich_paragraph(doc, "", v.stem)
        _add_rich_paragraph(doc, "参考答案：", v.answer)
        _add_rich_paragraph(doc, "解析：", v.solution)
        doc.add_paragraph(f"知识点：{'、'.join(v.knowledge_points)}")
        doc.add_paragraph(f"改编理由：{v.adaptation_reason}")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
