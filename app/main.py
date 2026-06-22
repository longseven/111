"""FastAPI 应用：解析 / 改编两个接口 + 静态前端。"""
from __future__ import annotations

import re
import traceback
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, store
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
from .schemas import (
    AdaptConditions,
    AdaptRequest,
    AdaptResult,
    AnswerVerifyRequest,
    AuthRequest,
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
auth.init_auth_db()


# 脱敏：抹掉可能混进异常文字里的 API key / Bearer 令牌，避免随报错泄露
_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9]{2})[A-Za-z0-9_\-]{6,}|(Bearer\s+)[A-Za-z0-9._\-]{8,}")


def _redact(text: str) -> str:
    return _SECRET_RE.sub(lambda m: (m.group(1) or m.group(2) or "") + "***", str(text))


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": _redact(message)})


# 无需登录的接口（其余 /api/* 一律要求有效会话）
_OPEN_API = {"/api/health"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """登录门：除 /api/auth/* 与 /api/health 外，所有 /api/* 需有效会话。

    校验通过则把当前用户存进 request.state.user 供各接口使用。
    页面与静态资源照常放行，未登录由前端弹登录框。
    """
    path = request.url.path
    if path.startswith("/api/") and not path.startswith("/api/auth/") and path not in _OPEN_API:
        user = auth.verify_token(request.cookies.get(auth.SESSION_COOKIE))
        if not user:
            return _error(401, "请先登录后再使用。")
        request.state.user = user
    return await call_next(request)


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


def _set_session(resp: JSONResponse, user: dict) -> JSONResponse:
    resp.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue_token(user),
        httponly=True,
        samesite="lax",
        max_age=14 * 24 * 3600,
    )
    return resp


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


# ---------- 账号：注册 / 登录 / 登出 / 当前用户 ----------
@app.post("/api/auth/register")
def api_register(payload: AuthRequest) -> JSONResponse:
    try:
        user = auth.register(payload.username, payload.password)
    except auth.AuthError as exc:
        return _error(400, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"注册失败：{exc}")
    return _set_session(
        JSONResponse(content={"username": user["username"], "is_admin": user["is_admin"]}), user
    )


@app.post("/api/auth/login")
def api_login(payload: AuthRequest) -> JSONResponse:
    try:
        user = auth.authenticate(payload.username, payload.password)
    except auth.AuthError as exc:
        return _error(401, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"登录失败：{exc}")
    return _set_session(
        JSONResponse(content={"username": user["username"], "is_admin": user["is_admin"]}), user
    )


@app.post("/api/auth/logout")
def api_logout() -> JSONResponse:
    resp = JSONResponse(content={"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


@app.get("/api/auth/me")
def api_me(request: Request) -> JSONResponse:
    token_user = auth.verify_token(request.cookies.get(auth.SESSION_COOKIE))
    if not token_user:
        return JSONResponse(content={"user": None})
    full = auth.get_user_by_id(token_user["id"])
    if not full:
        return JSONResponse(content={"user": None})
    return JSONResponse(
        content={
            "user": {
                "username": full["username"],
                "is_admin": bool(full["is_admin"]),
                "usage_today": auth.usage_today(full["id"]),
                "daily_quota": auth.daily_quota(),
            }
        }
    )


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
def api_config_get(request: Request) -> JSONResponse:
    view = _config_view()
    view["is_admin"] = bool(request.state.user.get("is_admin"))
    return JSONResponse(content=view)


@app.post("/api/config")
def api_config_set(payload: ConfigUpdate, request: Request) -> JSONResponse:
    """在线更新 provider/模型/key（不回显明文 key），即时生效无需重启。仅管理员可改。"""
    if not request.state.user.get("is_admin"):
        return _error(403, "仅管理员可修改模型设置。")
    try:
        updates = {k: v for k, v in payload.model_dump().items() if v is not None}
        update_runtime(updates)
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"保存设置失败：{exc}")
    view = _config_view()
    view["is_admin"] = True
    return JSONResponse(content=view)


@app.post("/api/parse")
def api_parse(
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
) -> JSONResponse:
    # 同步 def → FastAPI 线程池执行；阻塞的模型调用不再占住事件循环（多人并发不互相冻结）
    settings = get_settings()
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None

    if file is not None:
        data = file.file.read()
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
def api_adapt(payload: AdaptRequest, request: Request) -> JSONResponse:
    """第 2 步：按条件改编（不含校验，便于前端分步显示进度）。

    用同步 def 让 FastAPI 在线程池中执行：模型调用是阻塞 I/O，避免占住事件循环、
    保证 /api/verify 与 /api/verify_answer 能真正并发。
    """
    u = request.state.user
    try:
        auth.check_quota(u["id"], u["is_admin"])
    except auth.QuotaError as exc:
        return _error(429, str(exc))
    try:
        result = adapt_problem(payload.parsed, payload.conditions)
    except ConfigError as exc:
        return _error(500, str(exc))
    except RefusalError as exc:
        return _error(422, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"改编失败：{exc}")

    auth.consume(u["id"], u["is_admin"])  # 仅成功才扣配额
    return JSONResponse(content={"variants": [v.model_dump() for v in result.variants]})


@app.post("/api/verify")
def api_verify(payload: VerifyRequest) -> JSONResponse:
    """第 3 步：不超纲独立校验（同步 def → 线程池并发）。"""
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
def api_verify_answer(payload: AnswerVerifyRequest) -> JSONResponse:
    """第 4 步：独立解题复核答案正确性（同步 def → 线程池并发）。"""
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
def api_split(
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
) -> JSONResponse:
    """整卷：把含多题的试卷拆成一道道独立题目（同步 def → 线程池并发）。"""
    settings = get_settings()
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None
    if file is not None:
        data = file.file.read()
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
def api_export_paper(payload: ExportPaperRequest):
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
def api_generate(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
    text: Optional[str] = Form(default=None),
    conditions: str = Form(default="{}"),
) -> JSONResponse:
    """一步到位：上传题目 + 改编条件 → 解析 + 改编 + 不超纲校验（同步 def → 线程池并发）。"""
    u = request.state.user
    try:
        auth.check_quota(u["id"], u["is_admin"])
    except auth.QuotaError as exc:
        return _error(429, str(exc))
    settings = get_settings()
    file_name: Optional[str] = None
    file_bytes: Optional[bytes] = None
    if file is not None:
        data = file.file.read()
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

    auth.consume(u["id"], u["is_admin"])  # 仅成功才扣配额
    return JSONResponse(
        content={
            "parsed": parsed.model_dump(),
            "variants": [v.model_dump() for v in result.variants],
            "scope_checks": [c.model_dump() for c in checks.checks],
        }
    )


@app.post("/api/export")
def api_export(payload: ExportRequest):
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


# ---------- 题库：按用户隔离（每人只见自己的）----------
@app.post("/api/bank/save")
def api_bank_save(payload: BankSaveRequest, request: Request) -> JSONResponse:
    try:
        rec = store.save_record(
            payload.title, payload.kind, payload.payload, user_id=request.state.user["id"]
        )
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"保存题库失败：{exc}")
    return JSONResponse(content=rec)


@app.get("/api/bank/list")
def api_bank_list(request: Request) -> JSONResponse:
    try:
        records = store.list_records(request.state.user["id"])
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"读取题库失败：{exc}")
    return JSONResponse(content={"records": records})


@app.get("/api/bank/{rec_id}")
def api_bank_get(rec_id: int, request: Request) -> JSONResponse:
    try:
        rec = store.get_record(rec_id, request.state.user["id"])
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"读取题库失败：{exc}")
    if rec is None:
        return _error(404, "记录不存在或已删除。")
    return JSONResponse(content=rec)


@app.delete("/api/bank/{rec_id}")
def api_bank_delete(rec_id: int, request: Request) -> JSONResponse:
    try:
        ok = store.delete_record(rec_id, request.state.user["id"])
    except Exception as exc:  # noqa: BLE001
        return _server_error(f"删除题库失败：{exc}")
    if not ok:
        return _error(404, "记录不存在或已删除。")
    return JSONResponse(content={"ok": True})


# 静态资源（CSS/JS）。放在路由定义之后，避免覆盖 API 路径。
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
