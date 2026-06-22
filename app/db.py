"""共享 SQLite 连接层：题库、账号、配额共用同一数据库文件。

WAL + busy_timeout 让多 worker 进程并发读写安全；db_lock 在进程内串行化写。
数据库路径由 BANK_DB_PATH 指定（Docker 已指向挂载卷），默认 data/bank.db。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent

# 进程内写串行化（跨进程靠 SQLite 的 WAL + busy_timeout）
db_lock = threading.Lock()


def db_path() -> Path:
    override = os.environ.get("BANK_DB_PATH", "").strip()
    if override:
        return Path(override)
    return _BASE_DIR / "data" / "bank.db"


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn
