"""题库：把改编结果存进本地 SQLite，按用户隔离（每人只见自己的）。

payload 整体以 JSON 文本存一列，读写两端都是前端用的同一结构，
便于「存题库 → 一键调回结果区」。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import connect, db_lock


def init_db() -> None:
    with db_lock, connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                item_count INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        # 迁移：老库可能没有 user_id 列
        cols = {r[1] for r in conn.execute("PRAGMA table_info(records)")}
        if "user_id" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN user_id INTEGER")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_records_user ON records(user_id, id DESC)")


def _count_items(kind: str, payload: Dict[str, Any]) -> int:
    if kind == "paper":
        return len(payload.get("groups") or [])
    return len(payload.get("variants") or [])


def save_record(
    title: str, kind: str, payload: Dict[str, Any], user_id: Optional[int] = None
) -> Dict[str, Any]:
    title = (title or "未命名").strip() or "未命名"
    kind = kind if kind in ("single", "paper") else "single"
    created = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    count = _count_items(kind, payload)
    with db_lock, connect() as conn:
        cur = conn.execute(
            "INSERT INTO records (user_id, title, kind, item_count, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, title, kind, count, json.dumps(payload, ensure_ascii=False), created),
        )
        rec_id = cur.lastrowid
    return {"id": rec_id, "title": title, "kind": kind, "item_count": count, "created_at": created}


def list_records(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    with db_lock, connect() as conn:
        rows = conn.execute(
            "SELECT id, title, kind, item_count, created_at FROM records"
            " WHERE user_id IS ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_record(rec_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    with db_lock, connect() as conn:
        row = conn.execute(
            "SELECT id, title, kind, item_count, payload, created_at FROM records"
            " WHERE id = ? AND user_id IS ?",
            (rec_id, user_id),
        ).fetchone()
    if row is None:
        return None
    rec = dict(row)
    rec["payload"] = json.loads(rec["payload"])
    return rec


def delete_record(rec_id: int, user_id: Optional[int] = None) -> bool:
    with db_lock, connect() as conn:
        cur = conn.execute(
            "DELETE FROM records WHERE id = ? AND user_id IS ?", (rec_id, user_id)
        )
    return cur.rowcount > 0
