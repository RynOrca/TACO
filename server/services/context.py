# 请求上下文与服务容器，避免各 service 互相 import 造成循环依赖。

import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from server.services.user_service import UserService
    from server.services.chat_service import ChatService

def err(code: str, msg: str) -> dict:
    return {"type": "error", "code": code, "msg": msg}

@dataclass
class Services:
    users: "UserService"
    chat: "ChatService"

@dataclass
class RequestContext:
    """一条连接一个上下文，登录前后复用同一个对象。"""
    user_id: str
    conn: socket.socket
    room_id: int
    addr: tuple = ()
    services: Optional[Services] = None

    def send(self, msg: dict) -> bool:
        from server.network.protocol import FrameTooLarge, pack_message
        try:
            self.conn.sendall(pack_message(msg))
            return True
        except FrameTooLarge:
            try:
                self.conn.sendall(pack_message(err("MSG_TOO_LONG", "回包超过单帧上限，已截断")))
            except Exception:
                pass
            return False
        except Exception as e:
            print(f"发送失败 {self.addr}: {e}")
            return False

    def require_login(self) -> Optional[dict]:
        if not self.user_id:
            return err("NOT_LOGIN", "请先 /login 用户名")
        return None