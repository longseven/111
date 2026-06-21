"""题库：把改编结果存进本地 SQLite，支持保存 / 列表 / 读取 / 删除。

无需额外依赖，用标准库 sqlite3。数据库文件默认在项目根 data/bank.db，
可用环境变量 BANK_DB_PATH 覆盖。payload 整体以 JSON 文本存一列，
读写两端都是前端用的同一结构，便于「存题库 → 一键调回结果区」。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_BASE_DIR = Path(__file__).resolve().parent.parent
_lock = threading.Lock()


def _db_path() -> Path:
    override = os.environ.get("BANK_DB_PATH", "").strip()
    if override:
        return Path(override)
    return _BASE_DIR / "data" / "bank.db"


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def _count_items(kind: str, payload: Dict[str, Any]) -> int:
    if kind == "paper":
        return len(payload.get("groups") or [])
    return len(payload.get("variants") or [])


def save_record(title: str, kind: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    title = (title or "未命名").strip() or "未命名"
    kind = kind if kind in ("single", "paper") else "single"
    created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    count = _count_items(kind, payload)
    with _lock, _connect() as conn:
        cur = conn.execute(
            "INSERT INTO records (title, kind, item_count, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (title, kind, count, json.dumps(payload, ensure_ascii=False), created),
        )
        rec_id = cur.lastrowid
    return {"id": rec_id, "title": title, "kind": kind, "item_count": count, "created_at": created}


def list_records() -> List[Dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT id, title, kind, item_count, created_at FROM records ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_record(rec_id: int) -> Optional[Dict[str, Any]]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT id, title, kind, item_count, payload, created_at FROM records WHERE id = ?",
            (rec_id,),
        ).fetchone()
    if row is None:
        return None
    rec = dict(row)
    rec["payload"] = json.loads(rec["payload"])
    return rec


def delete_record(rec_id: int) -> bool:
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM records WHERE id = ?", (rec_id,))
    return cur.rowcount > 0
