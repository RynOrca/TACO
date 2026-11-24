# 群聊/私聊/Agent

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from server import config
from server.agent import agent_core
from server.console import log_chat
from server.models import Message
from server.services.context import RequestContext, err
from server.storage import chat_history

MAX_MSG_LEN = 2000
# 图片文件名由图片服务生成：32 位十六进制 + 白名单后缀，客户端改不了路径
IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:jpg|jpeg|png|gif|webp)$")

SUMMARY_PROMPT = (
    "请总结本群最近的讨论，面向群里所有人："
    "先给 2-4 条结论或进展，再列出待办（谁负责、做什么），150 字以内。"
    "只依据工具读到的群聊内容，不要编造。"
)


def validate_image(value) -> Optional[str]:
    """客户端带上来的图片引用必须是图片服务真实存在的那张，否则不认。"""
    if not isinstance(value, str) or not IMAGE_NAME_RE.match(value):
        return None
    return value if (config.IMAGE_DIR / value).is_file() else None


class ChatService:
    def __init__(self, users):
        self.users = users
        # Agent 调用是阻塞的，放独立线程池，不占住连接线程
        self._agent_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
        # 定时总结调度器，由 main.py 注入（服务层不自己起线程）
        self.scheduler = None
        self._summary_cursor = 0
        self._cursor_lock = threading.Lock()

    # ---------------------------------------------------------------- 房间
    def group_room_id(self) -> int:
        """Agent 的授权边界：永远只绑群聊主房间。"""
        return chat_history.ensure_room("main")

    # ---------------------------------------------------------------- 群聊/私聊
    @staticmethod
    def _extract_body(msg: dict) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        """返回（入库内容, 图片引用或 None, 错误回复）。"""
        image = msg.get("image")
        if image is not None:
            ref = validate_image(image)
            if ref is None:
                return None, None, err("BAD_IMAGE", "图片引用无效或文件已丢失，请重新上传")
            return ref, ref, None

        content = (msg.get("msg") or "").strip()
        if not content:
            return None, None, err("EMPTY_MSG", "消息内容为空")
        if len(content) > MAX_MSG_LEN:
            return None, None, err("MSG_TOO_LONG", f"消息超过 {MAX_MSG_LEN} 字")
        return content, None, None

    def handle_group(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need

        content, image, bad = self._extract_body(msg)
        if bad:
            return bad

        try:
            mid = chat_history.save_message(
                ctx.room_id, ctx.user_id, content, "image" if image else "group")
        except Exception as e:
            return err("SAVE_FAILED", f"消息保存失败：{e}")

        log_chat("群聊", ctx.user_id, f"[图片 {image}]" if image else content,
                 ctx.room_id, "main", ctx.addr)

        payload = {
            "type": "group", "sender": ctx.user_id, "id": mid,
            "msg": "[图片]" if image else content,
        }
        if image:
            payload["msg_type"] = "image"
            payload["image"] = image
        # sender 由服务端填充！！！！
        self.users.broadcast(payload)
        return None

    def handle_private(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need

        target = (msg.get("target") or "").strip()
        if not target:
            return err("BAD_PARAM", "target 不能为空")
        if target == ctx.user_id:
            return err("SELF_PM", "不能给自己发私聊")

        content, image, bad = self._extract_body(msg)
        if bad:
            return bad

        try:
            room_name = self._pm_name(ctx.user_id, target)
            room_id = self._pm_room(ctx.user_id, target)
            mid = chat_history.save_message(
                room_id, ctx.user_id, content, "image" if image else "private")
        except Exception as e:
            return err("SAVE_FAILED", f"消息保存失败：{e}")

        log_chat("私聊", ctx.user_id, f"[图片 {image}]" if image else content,
                 room_id, room_name, ctx.addr, target=target)

        # target 一并回传：发送方要据此决定这条私聊落在哪个会话里
        payload = {
            "type": "private", "sender": ctx.user_id, "target": target,
            "msg": "[图片]" if image else content, "id": mid,
        }
        if image:
            payload["msg_type"] = "image"
            payload["image"] = image
        delivered = self.users.send_to(target, payload)
        # 回显给自己，否则发送方本地的私聊会话里看不到自己刚发的那条
        ctx.send(payload)
        if not delivered:
            return err("USER_OFFLINE", f"用户 {target} 不在线，消息已存入历史")
        return None

    @staticmethod
    def _pm_name(a: str, b: str) -> str:
        """两人私聊的固定房间名，按字典序排序保证双向一致。"""
        return "pm:" + ":".join(sorted([a, b]))

    @classmethod
    def _pm_room(cls, a: str, b: str) -> int:
        return chat_history.ensure_room(cls._pm_name(a, b), room_type="private", owner_id=a)

    # ---------------------------------------------------------------- Agent
    def handle_agent(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need

        text = (msg.get("msg") or "").strip()
        if not text:
            return err("EMPTY_MSG", "问题为空")
        scope = msg.get("scope", "private")
        if scope not in ("private", "group"):
            return err("BAD_PARAM", "scope 只能是 private 或 group")

        # 不论用户在哪提问，Agent 读的都是群聊房间；私聊内容不具备授权
        room_id = self.group_room_id()
        ctx.send({
            "type": "agent", "sender": "Agent",
            "msg": "正在思考，请稍候…", "status": "pending", "scope": scope,
        })
        self._agent_pool.submit(self._agent_task, ctx.user_id, ctx.conn, room_id, text, scope)
        return None

    def _agent_task(self, user_id: str, conn, room_id: int, text: str, scope: str):
        try:
            reply, steps = agent_core.run_detailed(
                text, max_steps=config.AGENT_MAX_STEPS, room_id=room_id, user_id=user_id,
            )
        except Exception as e:
            print(f"[Agent] 调用异常: {e}")
            reply, steps = f"Agent 调用失败：{e}", []

        payload = {
            "type": "agent", "sender": "Agent", "msg": reply,
            "status": "done", "steps": steps, "scope": scope,
        }
        if scope == "group":
            try:
                payload["id"] = chat_history.save_message(room_id, "Agent", reply, "agent")
            except Exception as e:
                print(f"[Agent] 回复落库失败: {e}")
            log_chat("Agent", "Agent", reply, room_id, "main")
            self.users.broadcast(payload)
        else:
            log_chat("Agent", "Agent", f"（只回 {user_id}）{reply}", room_id, "main")
            # 私聊问答只回给提问者，不写进群聊历史：否则群里以后能翻到别人的私聊问答
            self.users.send_to(user_id, payload, conn=conn)

    # ---------------------------------------------------------------- 定时总结
    def run_scheduled_summary(self, triggered_by: Optional[str] = None,
                              force: bool = False) -> None:
        room_id = self.group_room_id()
        rows = list(chat_history.get_recent_history(room_id, 40))
        human = [m for m in rows if m.sender != "Agent"]
        with self._cursor_lock:
            fresh = [m for m in human if m.id > self._summary_cursor]
        if not force and len(fresh) < config.AGENT_AUTO_SUMMARY_MIN_MESSAGES:
            print(f"[AutoSummary] 新消息只有 {len(fresh)} 条，跳过本次总结")
            return

        print(f"[AutoSummary] 开始总结 {len(fresh)} 条新消息（来自 {triggered_by or '定时器'}）")
        try:
            reply, steps = agent_core.run_detailed(
                SUMMARY_PROMPT, max_steps=config.AGENT_MAX_STEPS,
                room_id=room_id, user_id="Agent",
            )
        except Exception as e:
            print(f"[AutoSummary] 总结失败: {e}")
            return

        payload = {
            "type": "agent", "sender": "Agent", "msg": reply,
            "status": "done", "steps": steps, "scheduled": True, "scope": "group",
        }
        try:
            payload["id"] = chat_history.save_message(room_id, "Agent", reply, "agent")
        except Exception as e:
            print(f"[AutoSummary] 落库失败: {e}")
        with self._cursor_lock:
            self._summary_cursor = max([m.id for m in rows], default=self._summary_cursor)
        self.users.broadcast(payload)

    def handle_auto_summary(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        if self.scheduler is None:
            return err("NO_SCHEDULER", "服务端没有启用定时总结调度器")

        action = (msg.get("action") or "status").strip()
        if action == "status":
            return {"type": "autosummary", **self.scheduler.status()}

        if action == "now":
            # 手动触发不看条数门槛，想让 Agent 现在就总结就总结
            self._agent_pool.submit(self.run_scheduled_summary, ctx.user_id, True)
            return {"type": "system", "msg": f"{ctx.user_id} 让 Agent 立即总结一次群聊"}

        if action == "off":
            self.scheduler.configure(0)
            self.users.broadcast({"type": "autosummary", **self.scheduler.status()})
            return {"type": "system", "msg": f"{ctx.user_id} 关闭了 Agent 定时总结"}

        if action != "on":
            return err("BAD_PARAM", "action 只能是 status / on / off / now")

        try:
            minutes = int(msg.get("minutes") or 5)
        except (TypeError, ValueError):
            return err("BAD_PARAM", "minutes 必须是整数分钟")
        if not 1 <= minutes <= 120:
            return err("BAD_PARAM", "minutes 必须在 1-120 之间")

        self.scheduler.configure(minutes * 60)
        self.users.broadcast({"type": "autosummary", **self.scheduler.status()})
        return {"type": "system", "msg": f"{ctx.user_id} 开启了 Agent 定时总结：每 {minutes} 分钟一次"}

    # ---------------------------------------------------------------- 历史/待办
    def handle_history(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need

        target = (msg.get("target") or "").strip()
        if target:
            room_id = chat_history.room_id_by_name("pm:" + ":".join(sorted([ctx.user_id, target])))
            if room_id is None:
                return {"type": "history", "target": target, "items": []}
        else:
            room_id = ctx.room_id

        limit = msg.get("limit", 20)
        before_id = msg.get("before_id")
        if before_id:
            rows = chat_history.get_history_before(room_id, before_id, limit)
        else:
            rows = chat_history.get_recent_history(room_id, limit)
        rows = list(rows)
        items = [
            {
                "id": m.id,
                "sender": m.sender,
                "content": m.content,
                "msg_type": m.msg_type,
                "created_at": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in reversed(rows)
        ]
        return {"type": "history", "target": target or None, "items": items,
                "before_id": before_id, "more": len(rows) >= chat_history._clamp(limit)}

    def handle_todos(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        return {"type": "todos", "items": chat_history.list_todos(ctx.room_id, limit=20)}

    @staticmethod
    def format_messages(rows: List[Message], truncate: int = 200) -> str:
        if not rows:
            return "当前没有聊天记录"
        lines = []
        for m in reversed(rows):
            content = m.content if len(m.content) <= truncate else m.content[:truncate] + "…"
            ts = m.timestamp.strftime("%m-%d %H:%M") if m.timestamp else "-"
            lines.append(f"[{ts}] {m.sender}: {content}")
        return "\n".join(lines)

    def shutdown(self):
        self._agent_pool.shutdown(wait=False)
