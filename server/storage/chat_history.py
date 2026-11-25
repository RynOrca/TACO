# 聊天记录、待办的 CRUD，返回 Message 对象
# CRUD: Create, Read, Update, Delete
# SQL语句传入输入时采用 ? 的形式，避免SQL注入

# 不会，让ai写；内容教学放到docs/内

from typing import List,Optional
from server.storage.db import get_conn, transaction,now_iso,row_to_message
from server.models import Message

MAX_LIMIT = 100

def _clamp(limit: int, default: int = 20) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def _like(keyword: str) -> str:
    """转义 LIKE 通配符，防止用户输入 % _ 影响检索。"""
    kw = (keyword or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{kw}%"


def _require_room(room_id: int) -> int:
    if not room_exists(room_id):
        raise ValueError(f"聊天室不存在：room_id={room_id}")
    return int(room_id)

def room_exists(room_id: int) -> bool:
    row = get_conn().execute(
        "SELECT 1 FROM rooms WHERE room_id = ?", (int(room_id),)
    ).fetchone()
    return row is not None


def room_id_by_name(name: str) -> Optional[int]:
    row = get_conn().execute(
        "SELECT room_id FROM rooms WHERE name = ?", (name,)
    ).fetchone()
    return row["room_id"] if row else None


def is_group_room(room_id: int) -> bool:
    """群聊房间还是私聊房间——Agent 工具用它守住授权边界。"""
    row = get_conn().execute(
        "SELECT room_type FROM rooms WHERE room_id = ?", (int(room_id),)
    ).fetchone()
    return bool(row) and row["room_type"] == "group"


def is_member(room_id: int, user_id: str) -> bool:
    row = get_conn().execute(
        "SELECT 1 FROM room_members WHERE room_id = ? AND user_id = ?",
        (int(room_id), user_id),
    ).fetchone()
    return row is not None


def ensure_room(name: str, room_type: str = "group", owner_id: Optional[str] = None) -> int:
    """按名称取房间，不存在则创建。返回 room_id。"""
    with transaction() as tx:
        cur = tx.execute(
            "INSERT OR IGNORE INTO rooms (name, room_type, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (name, room_type, owner_id, now_iso()),
        )
        row = tx.execute("SELECT room_id FROM rooms WHERE name = ?", (name,)).fetchone()
        room_id = row["room_id"]
        if cur.rowcount > 0 and owner_id:
            tx.execute(
                "INSERT OR IGNORE INTO room_members (room_id, user_id, joined_at) VALUES (?, ?, ?)",
                (room_id, owner_id, now_iso()),
            )
    return room_id


def save_message(room_id: int, sender: str, content: str,
                 msg_type: str = "group") -> int:
    _require_room(room_id)
    if not content or not content.strip():
        raise ValueError("content 不能为空")
    with transaction() as tx:
        cur = tx.execute(
            """INSERT INTO messages (room_id, sender, content, msg_type, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (int(room_id), sender, content.strip(), msg_type, now_iso()),
        )
        return cur.lastrowid


def get_recent_history(room_id: int, limit: int = 20) -> List[Message]:
    """最近 limit 条，按时间倒序返回（调用方可反转成正序）。"""
    limit = _clamp(limit)
    rows = get_conn().execute(
        """SELECT id, room_id, sender, content, msg_type, created_at
           FROM messages WHERE room_id = ?
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (int(room_id), limit),
    ).fetchall()
    return [row_to_message(r) for r in rows]


def get_history_before(room_id: int, before_id: int, limit: int = 20) -> List[Message]:
    """最近 limit 条中 id 小于 before_id 的部分，按时间倒序返回（用于向上翻页）。"""
    limit = _clamp(limit)
    rows = get_conn().execute(
        """SELECT id, room_id, sender, content, msg_type, created_at
           FROM messages WHERE room_id = ? AND id < ?
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (int(room_id), int(before_id), limit),
    ).fetchall()
    return [row_to_message(r) for r in rows]


def search_history(room_id: int, keywords: List[str], limit: int = 20) -> List[Message]:
    """多关键词 OR 检索，命中数多的排前面。"""
    if isinstance(keywords, str):
        keywords = [keywords]
    kws = [k.strip() for k in (keywords or []) if k and k.strip()]
    if not kws:
        return []
    limit = _clamp(limit)

    like_params = [_like(k) for k in kws]
    where = " OR ".join(["content LIKE ? ESCAPE '\\'"] * len(kws))
    rank = " + ".join(["CASE WHEN content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END"] * len(kws))

    rows = get_conn().execute(
        f"""SELECT id, room_id, sender, content, msg_type, created_at
            FROM messages
            WHERE room_id = ? AND ({where})
            ORDER BY ({rank}) DESC, created_at DESC
            LIMIT ?""",
        [int(room_id)] + like_params + like_params + [limit],
    ).fetchall()
    return [row_to_message(r) for r in rows]


def count_messages(room_id: int) -> int:
    row = get_conn().execute(
        "SELECT COUNT(*) AS c FROM messages WHERE room_id = ?", (int(room_id),)
    ).fetchone()
    return row["c"] if row else 0

def save_history(room_id: int, content: str, sender: str = "Agent") -> int:
    """保存会话总结。msg_type 固定为 summary，便于与真人消息区分。"""
    return save_message(room_id, sender, content, msg_type="summary")


def save_todo(room_id: int, content: str, assignee: Optional[str] = None) -> int:
    """保存待办事项到 todos 表，返回 todo id。"""
    _require_room(room_id)
    if not content or not content.strip():
        raise ValueError("content 不能为空")
    with transaction() as tx:
        cur = tx.execute(
            """INSERT INTO todos (room_id, assignee, content, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (int(room_id), assignee, content.strip(), now_iso()),
        )
        return cur.lastrowid


def list_todos(room_id: int, status: Optional[str] = None, limit: int = 50) -> List[dict]:
    limit = _clamp(limit, default=50)
    if status:
        rows = get_conn().execute(
            """SELECT id, assignee, content, status, created_at, done_at
               FROM todos WHERE room_id = ? AND status = ?
               ORDER BY created_at DESC LIMIT ?""",
            (int(room_id), status, limit),
        ).fetchall()
    else:
        rows = get_conn().execute(
            """SELECT id, assignee, content, status, created_at, done_at
               FROM todos WHERE room_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (int(room_id), limit),
        ).fetchall()
    return [dict(r) for r in rows]


def update_todo(todo_id: int, status: str) -> bool:
    """status: pending / done。返回是否更新成功。"""
    if status not in ("pending", "done"):
        raise ValueError("status 只能是 pending 或 done")
    with transaction() as tx:
        cur = tx.execute(
            """UPDATE todos SET status = ?, done_at = ?
               WHERE id = ? AND status != ?""",
            (status, now_iso() if status == "done" else None, int(todo_id), status),
        )
        return cur.rowcount > 0

def ensure_user(user_id: str, nickname: str = "", password_hash: str = "") -> str:
    with transaction() as tx:
        tx.execute(
            """INSERT OR IGNORE INTO users (user_id, nickname, password_hash, status)
               VALUES (?, ?, ?, 'offline')""",
            (user_id, nickname, password_hash),
        )
    return user_id


def create_user(user_id: str, nickname: str, password_hash: str) -> bool:
    """注册新用户。用户名已存在时返回 False，不覆盖原记录。"""
    with transaction() as tx:
        cur = tx.execute(
            """INSERT OR IGNORE INTO users (user_id, nickname, password_hash, status)
               VALUES (?, ?, ?, 'offline')""",
            (user_id, nickname, password_hash),
        )
        return cur.rowcount > 0


def get_user(user_id: str) -> Optional[dict]:
    row = get_conn().execute(
        """SELECT user_id, nickname, password_hash, status, last_login
           FROM users WHERE user_id = ?""",
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def join_room(room_id: int, user_id: str) -> bool:
    with transaction() as tx:
        cur = tx.execute(
            """INSERT OR IGNORE INTO room_members (room_id, user_id, joined_at)
               VALUES (?, ?, ?)""",
            (int(room_id), user_id, now_iso()),
        )
        return cur.rowcount > 0



# ---------------------------------------------------------------- 定时任务
TASK_FIELDS = ("kind", "payload", "interval_seconds", "next_run",
               "last_run", "enabled", "room_id")


def create_task(kind: str, next_run: str, payload: str = "",
                interval_seconds: int = 0, created_by: str = "",
                room_id: Optional[int] = None) -> int:
    with transaction() as tx:
        cur = tx.execute(
            """INSERT INTO scheduled_tasks
               (kind, payload, interval_seconds, next_run, enabled, created_by, created_at, room_id)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)""",
            (kind, payload, int(interval_seconds), next_run, created_by, now_iso(),
             int(room_id) if room_id is not None else None),
        )
        return cur.lastrowid


def get_task(task_id: int) -> Optional[dict]:
    row = get_conn().execute(
        "SELECT * FROM scheduled_tasks WHERE id = ?", (int(task_id),)
    ).fetchone()
    return dict(row) if row else None


def list_tasks() -> List[dict]:
    rows = get_conn().execute(
        "SELECT * FROM scheduled_tasks ORDER BY id"
    ).fetchall()
    return [dict(r) for r in rows]


def due_tasks(now: str) -> List[dict]:
    rows = get_conn().execute(
        """SELECT * FROM scheduled_tasks
           WHERE enabled = 1 AND next_run <= ?
           ORDER BY next_run""",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_task(task_id: int, **fields) -> bool:
    """只允许改白名单里的列，避免调用方把 SQL 玩坏。"""
    clean = {k: v for k, v in fields.items() if k in TASK_FIELDS}
    if not clean:
        return False
    sets = ", ".join(f"{k} = ?" for k in clean)
    with transaction() as tx:
        cur = tx.execute(
            f"UPDATE scheduled_tasks SET {sets} WHERE id = ?",
            [*clean.values(), int(task_id)],
        )
        return cur.rowcount > 0


def delete_task(task_id: int) -> bool:
    with transaction() as tx:
        cur = tx.execute("DELETE FROM scheduled_tasks WHERE id = ?", (int(task_id),))
        return cur.rowcount > 0


if __name__ == "__main__":
    from server.storage.db import init_db
    init_db()

    ensure_user("alice", "Alice")
    ensure_user("bob", "Bob")
    rid = ensure_room("demo", owner_id="alice")
    save_message(rid, "alice", "周五上线，张三负责联调")
    save_message(rid, "bob", "压测报告我下午发")
    save_history(rid, "1. 周五上线\n2. 张三负责联调")
    tid = save_todo(rid, "整理压测报告", assignee="bob")

    print("最近记录：", [(m.sender, m.content[:20]) for m in get_recent_history(rid, 5)])
    print("搜索'压测'：", [(m.sender, m.content[:20]) for m in search_history(rid, ["压测"], 5)])
    print("待办：", list_todos(rid))
    print("标记完成：", update_todo(tid, "done"))