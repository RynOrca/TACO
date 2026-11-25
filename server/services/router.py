# 消息路由：把 type 映射到 handler，网络层只调 dispatch

import time
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


def _handle_ping(ctx: RequestContext, msg: dict) -> dict:
    """心跳应答：带回客户端 seq，并附服务端时间戳，客户端据此算 RTT。"""
    return {
        "type": "pong",
        "seq": msg.get("seq"),
        "server_time": int(time.time() * 1000),
        "msg": "pong",
    }


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
    # 通用定时任务：list / add / del / on / off
    router.register("task", services.chat.handle_task)
    # 井字棋：start / move / board / status / quit
    router.register("game", services.chat.handle_game)
    # 心跳：客户端定时发 ping，服务端回 pong（last_seen 由网络层在收包时刷新）
    router.register("ping", _handle_ping)
    return router