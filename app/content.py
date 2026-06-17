"""把上传文件 / 粘贴文本转换为中性内容部件，再由适配器转成各 provider 的格式。

中性部件（part）形如：
- {"kind": "text",  "text": "..."}
- {"kind": "image", "media_type": "image/png", "data_b64": "..."}
- {"kind": "pdf",   "data_b64": "..."}
"""
from __future__ import annotations

import base64
from typing import Any, Dict, List, Optional

# 扩展名 → 图片 media_type
_IMAGE_TYPES: Dict[str, str] = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
}


class UnsupportedFileError(ValueError):
    """文件类型不受支持。"""


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _b64(data: bytes) -> str:
    return base64.standard_b64encode(data).decode("utf-8")


# ---------- 中性部件构造 ----------
def text_part(text: str) -> Dict[str, Any]:
    return {"kind": "text", "text": text}


def image_part(data: bytes, media_type: str) -> Dict[str, Any]:
    return {"kind": "image", "media_type": media_type, "data_b64": _b64(data)}


def pdf_part(data: bytes) -> Dict[str, Any]:
    return {"kind": "pdf", "data_b64": _b64(data)}


def file_to_part(filename: str, data: bytes) -> Dict[str, Any]:
    ext = _ext(filename)
    if ext in _IMAGE_TYPES:
        return image_part(data, _IMAGE_TYPES[ext])
    if ext == "pdf":
        return pdf_part(data)
    if ext in ("txt", "md"):
        return text_part(data.decode("utf-8", errors="replace"))
    raise UnsupportedFileError(
        f"不支持的文件类型: .{ext or '(无扩展名)'}（支持 png/jpg/jpeg/webp/gif/pdf/txt/md）"
    )


def build_problem_parts(
    file_name: Optional[str],
    file_bytes: Optional[bytes],
    pasted_text: Optional[str],
) -> List[Dict[str, Any]]:
    """组装解析原题所需的中性部件。至少需要文件或文本之一。"""
    parts: List[Dict[str, Any]] = []

    if file_name and file_bytes:
        parts.append(text_part("以下是需要识别的数学题目（来自上传的文件/截图）："))
        parts.append(file_to_part(file_name, file_bytes))

    if pasted_text and pasted_text.strip():
        parts.append(text_part("以下是需要识别的数学题目（文本）：\n" + pasted_text.strip()))

    if not parts:
        raise ValueError("请至少上传一个文件或粘贴题目文本。")

    return parts


# ---------- 适配器：中性部件 → provider 内容 ----------
def to_anthropic_content(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in parts:
        kind = p["kind"]
        if kind == "text":
            out.append({"type": "text", "text": p["text"]})
        elif kind == "image":
            out.append({
                "type": "image",
                "source": {"type": "base64", "media_type": p["media_type"], "data": p["data_b64"]},
            })
        elif kind == "pdf":
            out.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": p["data_b64"]},
            })
    return out


def to_openai_content(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in parts:
        kind = p["kind"]
        if kind == "text":
            out.append({"type": "text", "text": p["text"]})
        elif kind == "image":
            data_url = f"data:{p['media_type']};base64,{p['data_b64']}"
            out.append({"type": "image_url", "image_url": {"url": data_url}})
        elif kind == "pdf":
            raise UnsupportedFileError(
                "OpenAI 兼容模式暂不支持 PDF，请改用图片或粘贴文本，或切换到 Anthropic 模式（LLM_PROVIDER=anthropic）。"
            )
    return out
