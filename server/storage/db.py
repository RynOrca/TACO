# 使用SQLite进行连接管理与建表，WAL 模式 + 每线程一个连接 + busy_timeout
# WAL模式：Write-Ahead Logging，先写日志后改原库文件

# 对数据库做出INSERT/UPDATE/DELETE等修改时，一定要跟着.commit()!!
# 不然不会对数据库进行更新！

import json
import sqlite3
import threading
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional
from server.config import DB_PATH

# 创建线程本地存储对象，每个线程独立，互不干扰
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS rooms (
    room_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    room_type  TEXT NOT NULL DEFAULT 'group',
    owner_id   TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users ( 
    user_id TEXT PRIMARY KEY, 
    nickname TEXT NOT NULL DEFAULT '', 
    password_hash TEXT NOT NULL DEFAULT '', 
    status TEXT NOT NULL DEFAULT 'offline', 
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS room_members (
    room_id INTEGER NOT NULL, 
    user_id TEXT NOT NULL, 
    joined_at TEXT NOT NULL, 
    PRIMARY KEY (room_id, user_id),
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE, 
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    INTEGER NOT NULL,
    sender     TEXT NOT NULL,
    content    TEXT NOT NULL,
    msg_type   TEXT NOT NULL DEFAULT 'group',
    meta       TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
--- 由于要经常排序，先建立索引
CREATE INDEX IF NOT EXISTS idx_msg_room_time ON messages(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msg_sender    ON messages(sender);

CREATE TABLE IF NOT EXISTS mutes (
    user_id    TEXT PRIMARY KEY,
    until_at   TEXT NOT NULL,
    by_user    TEXT,
    reason     TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS room_reads (
    room_id      INTEGER NOT NULL,
    user_id      TEXT NOT NULL,
    last_read_id INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (room_id, user_id),
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    room_id    INTEGER NOT NULL,
    assignee   TEXT,
    content    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    done_at    TEXT,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_todo_room_status ON todos(room_id, status);

-- 定时任务：summary（让 Agent 总结）/ reminder（到点广播一句话）
-- interval_seconds > 0 表示周期任务；= 0 表示一次性任务（跑完自动关闭）
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,
    payload          TEXT NOT NULL DEFAULT '',
    interval_seconds INTEGER NOT NULL DEFAULT 0,
    next_run         TEXT NOT NULL,
    last_run         TEXT,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_by       TEXT,
    created_at       TEXT NOT NULL,
    room_id          INTEGER
);
CREATE INDEX IF NOT EXISTS idx_task_next ON scheduled_tasks(enabled, next_run);
"""

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def get_conn() -> sqlite3.Connection:
    """获取当前线程的连接（懒创建）"""
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn

def init_db() -> str:
    p = Path(DB_PATH)
    parent = p.parent
    if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    conn.executescript(SCHEMA)
    # 老库补列：SCHEMA 里的 CREATE TABLE IF NOT EXISTS 不会给已有表加字段
    for table, column, decl in (("messages", "meta", "TEXT"),):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            print(f"[db] 已为 {table} 补上 {column} 列")
    conn.commit()
    return DB_PATH

def close_db():
    conn = getattr(_local, "conn",None)
    if conn is not None:
        conn.close()
        _local.conn = None

@contextmanager
def transaction():
    """写操作统一入口，自动 commit / rollback"""
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def now_iso() -> str:
    """统一时间格式"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

# 解析时间字符串，把ISO格式时间字符串转成datetime对象
def parse_ts(value:Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None

def row_to_message(row:sqlite3.Row):
    """sqlite3.Row 转换成 models.Message 格式"""
    from server.models import Message
    meta = None
    try:
        raw = row["meta"]
    except (IndexError, KeyError):
        raw = None
    if raw:
        try:
            meta = json.loads(raw)
        except (TypeError, ValueError):
            meta = None
    return Message(
        id = row['id'],
        room_id = row['room_id'],
        sender = row['sender'],
        content = row['content'],
        msg_type = row['msg_type'],
        timestamp = parse_ts(row["created_at"]),
        meta = meta,
    )

if __name__ == '__main__':
    print("数据库已初始化: ", init_db())

