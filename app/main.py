"""FastAPI 应用：解析 / 改编两个接口 + 静态前端。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from .claude_service import (
    ConfigError,
    RefusalError,
    adapt_problem,
    parse_problem,
    verify_in_scope,
)
from .config import get_settings
from .content import UnsupportedFileError, build_problem_parts
from .export import export_docx
from .schemas import AdaptRequest, AdaptResponse, ExportRequest

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="K12 数学题目改编系统")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {
        "ok": True,
        "provider": settings.provider,
        "has_api_key": settings.has_api_key,
        "model": settings.model,
    }


@app.post("/api/parse")
async def api_parse(
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
) -> JSONResponse:
    settings = get_settings()
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None

    if file is not None:
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            return _error(413, f"文件过大，上限为 {settings.max_upload_bytes // (1024 * 1024)}MB。")
        file_name, file_bytes = file.filename or "upload", data

    try:
        parts = build_problem_parts(file_name, file_bytes, text)
        parsed = parse_problem(parts)
    except (UnsupportedFileError, ValueError) as exc:
        return _error(400, str(exc))
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001 — 兜底返回结构化错误
        return _error(502, f"解析失败：{exc}")

    return JSONResponse(content=parsed.model_dump())


@app.post("/api/adapt")
async def api_adapt(payload: AdaptRequest) -> JSONResponse:
    try:
        result = adapt_problem(payload.parsed, payload.conditions)
        checks = verify_in_scope(payload.parsed, result)
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error(502, f"改编失败：{exc}")

    response = AdaptResponse(variants=result.variants, scope_checks=checks.checks)
    return JSONResponse(content=response.model_dump())


@app.post("/api/export")
async def api_export(payload: ExportRequest):
    try:
        data = export_docx(
            payload.parsed, payload.variants, payload.title, payload.formula_mode
        )
    except Exception as exc:  # noqa: BLE001
        return _error(502, f"导出失败：{exc}")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="adapted_problems.docx"'},
    )


# 静态资源（CSS/JS）。放在路由定义之后，避免覆盖 API 路径。
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
