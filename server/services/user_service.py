# 在线用户管理（user_id与conn的映射关系，以及单播/广播）

import hashlib
import hmac
import os
import socket
import threading
import time
from typing import Dict, List, Optional

from server.console import log_line
from server.network.protocol import FrameTooLarge, pack_message
from server.services.context import RequestContext, err
from server.storage import chat_history

PBKDF2_ROUNDS = 100_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (AttributeError, ValueError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


class UserService:
    def __init__(self):
        self._pool: Dict[str, socket.socket] = {}
        # 每条连接最后一次收到数据的时间。心跳超时回收靠它判断，与是否登录无关。
        self._conns: Dict[socket.socket, float] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 心跳
    def attach(self, conn: socket.socket) -> None:
        with self._lock:
            self._conns[conn] = time.time()

    def touch(self, conn: socket.socket) -> None:
        """收到任何帧都刷新活跃时间，不只是 ping——正常聊天也证明连接活着。"""
        with self._lock:
            if conn in self._conns:
                self._conns[conn] = time.time()

    def detach(self, conn: socket.socket) -> None:
        with self._lock:
            self._conns.pop(conn, None)

    def reap(self, idle_timeout: int) -> List[str]:
        """回收超过 idle_timeout 秒没有任何数据的连接，返回被踢下线的用户名。"""
        now = time.time()
        with self._lock:
            expired = [sock for sock, ts in self._conns.items() if now - ts > idle_timeout]
        dead: List[str] = []
        for sock in expired:
            with self._lock:
                user = next((u for u, s in self._pool.items() if s is sock), "")
                idle = int(now - self._conns.get(sock, now))
            log_line(
                f"[Heartbeat] {user or '未登录连接'} 超过 {idle}s 没有任何数据"
                f"（阈值 {idle_timeout}s），判定掉线并断开"
            )
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
            self.logout(user, sock)
            self.detach(sock)
            if user:
                dead.append(user)
        return dead

    def login(self, user_id: str, conn: socket.socket) -> bool:
        user_id = (user_id or "").strip()
        if not user_id:
            return False
        with self._lock:
            old = self._pool.get(user_id)
            self._pool[user_id] = conn
        if old is not None and old is not conn:
            try:
                old.close()
            except Exception:
                pass
        return True

    def logout(self, user_id: str, conn: socket.socket):
        if not user_id:
            return
        with self._lock:
            if self._pool.get(user_id) is conn:
                self._pool.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        with self._lock:
            return user_id in self._pool

    def online_users(self) -> List[str]:
        with self._lock:
            return list(self._pool.keys())

    def send_to(self, user_id: str, msg: dict, conn: Optional[socket.socket] = None) -> bool:
        if conn is None:
            with self._lock:
                conn = self._pool.get(user_id)
        if conn is None:
            return False
        try:
            conn.sendall(pack_message(msg))
            return True
        except FrameTooLarge as e:
            log_line(f"[Protocol] 回包超过单帧上限，已丢弃：{e}")
            return False
        except Exception as e:
            log_line(f"[User] 发送给 {user_id} 失败: {e}")
            return False

    def broadcast(self, msg: dict, exclude: Optional[str] = None) -> int:
        try:
            pkg = pack_message(msg)
        except FrameTooLarge as e:
            log_line(f"[Protocol] 广播包超过单帧上限，已丢弃：{e}")
            return 0
        with self._lock:
            items = list(self._pool.items())
        count = 0
        for user, conn in items:
            if user == exclude:
                continue
            try:
                conn.sendall(pkg)
                count += 1
            except Exception:
                pass
        return count

    def push_userlist(self):
        self.broadcast({"type": "userlist", "users": self.online_users()})

    def handle_register(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        user_id = (msg.get("user_id") or "").strip()
        password = msg.get("password") or ""
        nickname = (msg.get("nickname") or "").strip() or user_id
        if not user_id:
            return err("BAD_REGISTER", "user_id 不能为空")
        if len(user_id) > 32:
            return err("BAD_REGISTER", "user_id 最长 32 个字符")
        if not password or len(password) > 64:
            return err("BAD_REGISTER", "密码需为 1-64 个字符")

        if not chat_history.create_user(user_id, nickname, hash_password(password)):
            return err("USER_EXISTS", f"用户名 {user_id} 已被注册")

        log_line(f"用户 [{user_id}] 注册成功")
        return {"type": "system", "msg": f"注册成功，请用 /login {user_id} 密码 登录"}

    def handle_login(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        user_id = (msg.get("user_id") or "").strip()
        password = msg.get("password") or ""
        if not user_id:
            return err("BAD_LOGIN", "user_id 不能为空")

        user = chat_history.get_user(user_id)
        if user is None:
            return err("NOT_REGISTERED", f"用户 {user_id} 未注册，请先 /register 用户名 密码")
        if not verify_password(password, user["password_hash"]):
            return err("BAD_PASSWORD", "密码错误")

        # 同一条连接换号登录：先把上一个身份从在线表里摘掉，否则会留下幽灵在线用户
        if ctx.user_id and ctx.user_id != user_id:
            self.logout(ctx.user_id, ctx.conn)
        if not self.login(user_id, ctx.conn):
            return err("LOGIN_FAILED", "登录失败")

        ctx.user_id = user_id

        try:
            ctx.room_id = chat_history.ensure_room("main", owner_id=user_id)
            chat_history.join_room(ctx.room_id, user_id)
        except Exception as e:
            print(f"[User] 登录落库失败 {user_id}: {e}")

        log_line(f"用户 [{user_id}] 登录成功，room={ctx.room_id}")
        self.push_userlist()

        # 当前禁言名单：客户端据此在成员面板上标记
        try:
            mutes = chat_history.active_mutes()
            if mutes:
                ctx.send({"type": "muted", "mutes": mutes})
        except Exception as e:
            log_line(f"[User] 读取禁言名单失败: {e}")

        # 离线期间别人发来的消息：只给"数字和读到的位置"，内容客户端用历史分页自己拉
        try:
            marks = chat_history.unread_items(user_id)
            if marks:
                ctx.send({"type": "unread", "unread_items": marks})
                total = sum(m["unread"] for m in marks)
                log_line(f"用户 [{user_id}] 离线期间有 {total} 条未读（{len(marks)} 个会话）")
        except Exception as e:
            log_line(f"[User] 计算离线未读失败 {user_id}: {e}")

        return {"type": "system", "msg": f"登录成功，当前房间 room_id={ctx.room_id}"}