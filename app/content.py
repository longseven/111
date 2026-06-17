"""把上传文件 / 粘贴文本转换为 Anthropic content block。"""
from __future__ import annotations

import base64
from typing import Any, Dict, List

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


def image_block(data: bytes, media_type: str) -> Dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("utf-8"),
        },
    }


def pdf_block(data: bytes) -> Dict[str, Any]:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode("utf-8"),
        },
    }


def text_block(text: str) -> Dict[str, Any]:
    return {"type": "text", "text": text}


def file_to_block(filename: str, data: bytes) -> Dict[str, Any]:
    """根据文件名扩展名把字节转换为图片或 PDF block。"""
    ext = _ext(filename)
    if ext in _IMAGE_TYPES:
        return image_block(data, _IMAGE_TYPES[ext])
    if ext == "pdf":
        return pdf_block(data)
    if ext in ("txt", "md"):
        return text_block(data.decode("utf-8", errors="replace"))
    raise UnsupportedFileError(
        f"不支持的文件类型: .{ext or '(无扩展名)'}（支持 png/jpg/jpeg/webp/gif/pdf/txt/md）"
    )


def build_problem_blocks(
    file_name: str | None,
    file_bytes: bytes | None,
    pasted_text: str | None,
) -> List[Dict[str, Any]]:
    """组装解析原题所需的 content blocks。

    至少需要文件或文本之一；两者都给时一并附上。
    每个 block 前置一句引导文本，便于模型聚焦题目本体。
    """
    blocks: List[Dict[str, Any]] = []

    if file_name and file_bytes:
        blocks.append(text_block("以下是需要识别的数学题目（来自上传的文件/截图）："))
        blocks.append(file_to_block(file_name, file_bytes))

    if pasted_text and pasted_text.strip():
        blocks.append(text_block("以下是需要识别的数学题目（文本）：\n" + pasted_text.strip()))

    if not blocks:
        raise ValueError("请至少上传一个文件或粘贴题目文本。")

    return blocks
