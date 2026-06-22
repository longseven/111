"""账号 / 会话 / 配额：纯标准库实现，多 worker 安全。

- 密码：pbkdf2_hmac(sha256) 加盐哈希，不存明文。
- 会话：无状态签名令牌（HMAC），各 worker 共享同一密钥即可校验，无需共享内存。
- 配额：每用户每日生成次数上限，保护共享 API 预算。
- 首个注册用户自动成为管理员（可改模型/key、无配额限制）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import date
from pathlib import Path
from typing import Optional

from .db import connect, db_lock, db_path

_PBKDF2_ROUNDS = 200_000
_SESSION_TTL = 14 * 24 * 3600  # 14 天
SESSION_COOKIE = "k12_session"


# ---------- 建表 ----------
def init_auth_db() -> None:
    with db_lock, connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                pw_salt TEXT NOT NULL,
                pw_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage (
                user_id INTEGER NOT NULL,
                day TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            )
            """
        )


# ---------- 服务端密钥（签名会话用）----------
def _secret() -> bytes:
    """APP_SECRET 优先；否则在 data 目录生成并持久化一份，保证多 worker / 重启一致。"""
    env = os.environ.get("APP_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    key_path = db_path().parent / "secret.key"
    try:
        if key_path.exists():
            return key_path.read_bytes()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = secrets.token_bytes(32)
        key_path.write_bytes(key)
        return key
    except OSError:
        return b"k12-fallback-secret-please-set-APP_SECRET"


# ---------- 密码 ----------
def _hash_pw(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ROUNDS)
    return dk.hex()


def _verify_pw(password: str, salt: str, expected: str) -> bool:
    return hmac.compare_digest(_hash_pw(password, salt), expected)


# ---------- 用户 CRUD ----------
def user_count() -> int:
    with db_lock, connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def get_user(username: str) -> Optional[dict]:
    with db_lock, connect() as conn:
        row = conn.execute(
            "SELECT id, username, pw_salt, pw_hash, is_admin FROM users WHERE username = ?",
            (username.strip(),),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> Optional[dict]:
    with db_lock, connect() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


class AuthError(ValueError):
    """注册/登录失败（用户名占用、口令错误等）。"""


def register(username: str, password: str) -> dict:
    username = (username or "").strip()
    if not (2 <= len(username) <= 32):
        raise AuthError("用户名长度需为 2–32 个字符。")
    if len(password or "") < 6:
        raise AuthError("密码至少 6 位。")
    salt = secrets.token_bytes(16).hex()
    pw_hash = _hash_pw(password, salt)
    created = date.today().isoformat()
    with db_lock, connect() as conn:
        is_admin = 1 if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0 else 0
        try:
            cur = conn.execute(
                "INSERT INTO users (username, pw_salt, pw_hash, is_admin, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (username, salt, pw_hash, is_admin, created),
            )
        except Exception as exc:  # noqa: BLE001 — UNIQUE 冲突等
            raise AuthError("用户名已被注册。") from exc
        uid = cur.lastrowid
    return {"id": uid, "username": username, "is_admin": bool(is_admin)}


def authenticate(username: str, password: str) -> dict:
    user = get_user(username)
    if not user or not _verify_pw(password, user["pw_salt"], user["pw_hash"]):
        raise AuthError("用户名或密码不正确。")
    return {"id": user["id"], "username": user["username"], "is_admin": bool(user["is_admin"])}


# ---------- 会话令牌（无状态 HMAC 签名）----------
def issue_token(user: dict) -> str:
    import time

    exp = int(time.time()) + _SESSION_TTL
    payload = f"{user['id']}:{1 if user['is_admin'] else 0}:{exp}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def verify_token(token: Optional[str]) -> Optional[dict]:
    """校验会话令牌，返回 {id, is_admin} 或 None。"""
    import time

    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        user_id, is_admin, exp, sig = raw.split(":")
        payload = f"{user_id}:{is_admin}:{exp}"
        good = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        if int(exp) < int(time.time()):
            return None
        return {"id": int(user_id), "is_admin": is_admin == "1"}
    except Exception:  # noqa: BLE001 — 任意解析失败都视为无效令牌
        return None


# ---------- 配额 ----------
def daily_quota() -> int:
    return int(os.environ.get("DAILY_QUOTA", "50"))


class QuotaError(RuntimeError):
    """超出每日配额。"""


def check_quota(user_id: int, is_admin: bool) -> None:
    """生成前置检查：管理员不限；普通用户当日已达上限则抛 QuotaError（不扣减）。"""
    if is_admin:
        return
    limit = daily_quota()
    if limit <= 0:
        return
    if usage_today(user_id) >= limit:
        raise QuotaError(f"今日生成已达上限（{limit} 次/天），请明天再试或联系管理员。")


def consume(user_id: int, is_admin: bool, n: int = 1) -> None:
    """生成成功后扣减配额（失败不扣，避免网络/模型报错白白消耗）。"""
    if is_admin or daily_quota() <= 0:
        return
    today = date.today().isoformat()
    with db_lock, connect() as conn:
        conn.execute(
            "INSERT INTO usage (user_id, day, count) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, day) DO UPDATE SET count = count + ?",
            (user_id, today, n, n),
        )


def usage_today(user_id: int) -> int:
    today = date.today().isoformat()
    with db_lock, connect() as conn:
        row = conn.execute(
            "SELECT count FROM usage WHERE user_id = ? AND day = ?", (user_id, today)
        ).fetchone()
    return row[0] if row else 0
