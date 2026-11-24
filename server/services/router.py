# 消息路由：把 type 映射到 handler，网络层只调 dispatch

from typing import Callable, Dict, Optional
from server.services.context import RequestContext, err
Handler = Callable[[RequestContext, dict], Optional[dict]]

class MessageRouter:
    def __init__(self):
        self._handlers: Dict[str, Handler] = {}

    def register(self, msg_type: str, handler: Handler):
        self._handlers[msg_type] = handler

    def dispatch(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        if not isinstance(msg, dict):
            return err("BAD_FORMAT", "消息必须是 JSON 对象")

        if msg.get("sys") is True:
            return None

        mtype = msg.get("type")
        if not isinstance(mtype, str):
            return err("BAD_TYPE", "消息缺少 type 字段")

        handler = self._handlers.get(mtype)
        if handler is None:
            return err("UNKNOWN_TYPE", f"不支持的消息类型：{mtype}")

        try:
            return handler(ctx, msg)
        except Exception as e:
            print(f"[Router] 处理 {mtype} 异常: {e}")
            return err("INTERNAL", "服务器内部错误")


def build_default_router(services) -> MessageRouter:
    router = MessageRouter()
    router.register("register", services.users.handle_register)
    router.register("login", services.users.handle_login)
    router.register("group", services.chat.handle_group)
    router.register("private", services.chat.handle_private)
    router.register("agent", services.chat.handle_agent)
    router.register("todos", services.chat.handle_todos)
    router.register("history", services.chat.handle_history)
    # Agent 定时总结：查询状态 / 开 / 关 / 立刻跑一次
    router.register("autosummary", services.chat.handle_auto_summary)
    # 心跳：客户端定时发 ping，服务端回 pong
    router.register("ping", lambda ctx, msg: {"type": "pong", "msg": "pong"})
    return router