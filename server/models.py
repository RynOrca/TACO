# 将数据存储持久化，就需要用到数据模型，告诉其他模块消息的结构、字段和类型

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class User:
    user_id: str
    nickname: str
    password_hash: str
    status: str = "online"  # online / offline
    last_login: Optional[datetime] = None


@dataclass
class Message:
    id: int
    sender: str
    room_id: int
    content: str
    msg_type: str     # group / private / image / file / agent / system
    timestamp: datetime
    # 附加信息（JSON）：文件消息存 {"name","size","mime"}
    meta: Optional[dict] = None


@dataclass
class TodoItem:
    id: int
    user_id: str
    content: str
    status: str        # pending / done
    created_at: datetime