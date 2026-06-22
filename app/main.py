"""FastAPI 应用：解析 / 改编两个接口 + 静态前端。"""
from __future__ import annotations

import traceback
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
    split_paper,
    verify_answer,
    verify_in_scope,
)
from .config import get_settings, update_runtime
from .content import UnsupportedFileError, build_problem_parts
from .export import export_docx, export_paper_docx
from . import store
from .schemas import (
    AdaptConditions,
    AdaptRequest,
    AdaptResult,
    AnswerVerifyRequest,
    BankSaveRequest,
    ConfigUpdate,
    ExportPaperRequest,
    ExportRequest,
    VerifyRequest,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="K12 数学题目改编系统")
store.init_db()


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    """禁用缓存：更新代码后普通刷新即可拿到最新前端，无需强制刷新。"""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def _server_error(message: str) -> JSONResponse:
    """502 错误：同时把完整堆栈打到终端（运行 ./run.sh 的窗口）便于定位。"""
    traceback.print_exc()
    return _error(502, message)


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


def _config_view() -> dict:
    s = get_settings()
    return {
        "provider": s.provider,
        "anthropic_model": s.anthropic_model,
        "openai_model": s.openai_model,
        "openai_base_url": s.openai_base_url,
        "has_anthropic_key": bool(s.anthropic_api_key.strip()),
        "has_openai_key": bool(s.openai_api_key.strip()),
        "has_api_key": s.has_api_key,
        "model": s.model,
    }


@app.get("/api/config")
async def api_config_get() -> JSONResponse:
    return JSONResponse(content=_config_view())


@app.post("/api/config")
async def api_config_set(payload: ConfigUpdate) -> JSONResponse:
    """在线更新 provider/模型/key（不回显明文 key），即时生效无需重启。"""
    try:
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        update_runtime(updates)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"保存设置失败：{exc}")
    return JSONResponse(content=_config_view())


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
        return _server_error(f"解析失败：{exc}")

    return JSONResponse(content=parsed.model_dump())


@app.post("/api/adapt")
async def api_adapt(payload: AdaptRequest) -> JSONResponse:
    """第 2 步：按条件改编（不含校验，便于前端分步显示进度）。"""
    try:
        result = adapt_problem(payload.parsed, payload.conditions)
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"改编失败：{exc}")

    return JSONResponse(content={"variants": [v.model_dump() for v in result.variants]})


@app.post("/api/verify")
async def api_verify(payload: VerifyRequest) -> JSONResponse:
    """第 3 步：不超纲独立校验。"""
    try:
        checks = verify_in_scope(payload.parsed, AdaptResult(variants=payload.variants))
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"校验失败：{exc}")

    return JSONResponse(content={"scope_checks": [c.model_dump() for c in checks.checks]})


@app.post("/api/verify_answer")
async def api_verify_answer(payload: AnswerVerifyRequest) -> JSONResponse:
    """第 4 步：独立解题复核答案正确性。"""
    try:
        checks = verify_answer(AdaptResult(variants=payload.variants))
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"答案校验失败：{exc}")

    return JSONResponse(content={"answer_checks": [c.model_dump() for c in checks.checks]})


@app.post("/api/split")
async def api_split(
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
) -> JSONResponse:
    """整卷：把含多题的试卷拆成一道道独立题目。"""
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
        result = split_paper(parts)
    except (UnsupportedFileError, ValueError) as exc:
        return _error(400, str(exc))
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"拆分试卷失败：{exc}")

    return JSONResponse(content={"problems": result.problems})


@app.post("/api/export_paper")
async def api_export_paper(payload: ExportPaperRequest):
    try:
        groups = [(g.parsed, g.variants) for g in payload.groups]
        data = export_paper_docx(groups, payload.title, payload.formula_mode)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"导出失败：{exc}")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="adapted_paper.docx"'},
    )


@app.post("/api/generate")
async def api_generate(
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
    conditions: str = Form(default="{}"),
) -> JSONResponse:
    """一步到位：上传题目 + 改编条件 → 解析 + 改编 + 不超纲校验。"""
    settings = get_settings()
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None
    if file is not None:
        data = await file.read()
        if len(data) > settings.max_upload_bytes:
            return _error(413, f"文件过大，上限为 {settings.max_upload_bytes // (1024 * 1024)}MB。")
        file_name, file_bytes = file.filename or "upload", data

    try:
        cond = AdaptConditions.model_validate_json(conditions)
    except Exception:  # noqa: BLE001
        return _error(400, "改编条件格式有误。")

    try:
        parts = build_problem_parts(file_name, file_bytes, text)
        parsed = parse_problem(parts)
        result = adapt_problem(parsed, cond)
        checks = verify_in_scope(parsed, result)
    except (UnsupportedFileError, ValueError) as exc:
        return _error(400, str(exc))
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"生成失败：{exc}")

    return JSONResponse(
        content={
            "parsed": parsed.model_dump(),
            "variants": [v.model_dump() for v in result.variants],
            "scope_checks": [c.model_dump() for c in checks.checks],
        }
    )


@app.post("/api/export")
async def api_export(payload: ExportRequest):
    try:
        data = export_docx(
            payload.parsed, payload.variants, payload.title, payload.formula_mode
        )
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"导出失败：{exc}")
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="adapted_problems.docx"'},
    )


# ---------- 题库：保存 / 列表 / 读取 / 删除 ----------
@app.post("/api/bank/save")
async def api_bank_save(payload: BankSaveRequest) -> JSONResponse:
    try:
        rec = store.save_record(payload.title, payload.kind, payload.payload)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"保存题库失败：{exc}")
    return JSONResponse(content=rec)


@app.get("/api/bank/list")
async def api_bank_list() -> JSONResponse:
    try:
        records = store.list_records()
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"读取题库失败：{exc}")
    return JSONResponse(content={"records": records})


@app.get("/api/bank/{rec_id}")
async def api_bank_get(rec_id: int) -> JSONResponse:
    try:
        rec = store.get_record(rec_id)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"读取题库失败：{exc}")
    if rec is None:
        return _error(404, "记录不存在或已删除。")
    return JSONResponse(content=rec)


@app.delete("/api/bank/{rec_id}")
async def api_bank_delete(rec_id: int) -> JSONResponse:
    try:
        ok = store.delete_record(rec_id)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"删除题库失败：{exc}")
    if not ok:
        return _error(404, "记录不存在或已删除。")
    return JSONResponse(content={"ok": True})


# 静态资源（CSS/JS）。放在路由定义之后，避免覆盖 API 路径。
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
