# 使用SQLite进行连接管理与建表，WAL 模式 + 每线程一个连接 + busy_timeout
# WAL模式：Write-Ahead Logging，先写日志后改原库文件

# 对数据库做出INSERT/UPDATE/DELETE等修改时，一定要跟着.commit()!!
# 不然不会对数据库进行更新！

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
    created_at TEXT NOT NULL,
    FOREIGN KEY (room_id) REFERENCES rooms(room_id) ON DELETE CASCADE
);
--- 由于要经常排序，先建立索引
CREATE INDEX IF NOT EXISTS idx_msg_room_time ON messages(room_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msg_sender    ON messages(sender);

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
    return Message(
        id = row['id'],
        room_id = row['room_id'],
        sender = row['sender'],
        content = row['content'],
        msg_type = row['msg_type'],
        timestamp = parse_ts(row["created_at"]),
    )

if __name__ == '__main__':
    print("数据库已初始化: ", init_db())

