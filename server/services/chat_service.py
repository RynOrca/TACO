# 群聊/私聊/Agent

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from server import config
from server.agent import agent_core
from server.console import log_chat, log_line
from server.models import Message
from server.network.image_server import EXT_BY_MIME
from server.services import game_service
from server.services.context import RequestContext, err
from server.storage import chat_history
from server.storage.db import parse_ts

MAX_MSG_LEN = 2000
# 撤回时限：超过这个秒数就不让撤了，避免翻旧账
RECALL_WINDOW_SECONDS = 120
# 用户名允许的字符，@提及从这里切
MENTION_RE = re.compile(r"@([\w一-龥-]{1,32})")
# 附件落盘名由服务端生成：32 位随机前缀 + 白名单后缀，客户端改不了路径
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,8}$")
# 单页历史最多多少字节。超过就少给几条，避免把整个回包顶到协议单帧上限
MAX_HISTORY_BYTES = 512 * 1024
# Agent 回复落库/广播前的最大字节数，超了截断并标注
MAX_AGENT_REPLY_BYTES = 32 * 1024


def _clamp_reply(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_AGENT_REPLY_BYTES:
        return text
    return raw[:MAX_AGENT_REPLY_BYTES].decode("utf-8", errors="ignore") + "\n…（回复过长，已截断）"

SUMMARY_PROMPT = (
    "请总结本群最近的讨论，面向群里所有人："
    "先给 2-4 条结论或进展，再列出待办（谁负责、做什么），150 字以内。"
    "只依据工具读到的群聊内容，不要编造。"
)

GAME_HELP = chr(10).join((
    "棋牌室（井字棋 / 五子棋 / 21 点）：",
    "  /game start            和 Agent 下一局（默认井字棋）",
    "  /game start gomoku     和 Agent 下五子棋（15×15，五连获胜）",
    "  /game start bj         和 Agent 玩 21 点（你只知道自己的牌）",
    "  /game invite 用户名     邀请另一位成员对弈（对方 /game accept 接受）",
    "  /game accept | decline  接受 / 拒绝邀请",
    "  /game move 5           下在第 5 格（1-9，从左到右、从上到下）",
    "  /game watch            观战所有进行中的对局",
    "  /game board | status   看当前棋盘 / 看战绩",
    "  /game quit             退出对局（人对人时判对方胜）",
))


def validate_attachment(value) -> Optional[str]:
    """客户端带上来的附件引用必须是附件服务真实存在的那一份，否则不认。"""
    if not isinstance(value, str):
        return None
    if not STORED_NAME_RE.match(value):
        return None
    suf = Path(value).suffix.lower()
    allowed = tuple(EXT_BY_MIME.values()) + config.FILE_EXT_ALLOWED
    if suf not in allowed:
        return None
    return value if (config.IMAGE_DIR / value).is_file() else None


def attachment_kind(value: str) -> str:
    """"image" 还是 "file"：按后缀判断，客户端说了不算。"""
    return "image" if Path(value).suffix.lower() in EXT_BY_MIME.values() else "file"


class ChatService:
    def __init__(self, users):
        self.users = users
        # Agent 调用是阻塞的，放独立线程池，不占住连接线程
        self._agent_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="agent")
        # 定时总结调度器，由 main.py 注入（服务层不自己起线程）
        self.scheduler = None
        # 井字棋：每个用户一盘，状态只在服务端
        self.games = game_service.GameService(users)
        self._summary_cursor = 0
        self._cursor_lock = threading.Lock()

    # ---------------------------------------------------------------- 房间
    def group_room_id(self) -> int:
        """群聊主房间。Agent 读群聊永远只绑这里。"""
        return chat_history.ensure_room("main")

    @staticmethod
    def agent_room_id(user_id: str) -> int:
        """每个用户自己与 Agent 的私聊房间：只有本人能读写，别人（含别人的 Agent 任务）碰不到。"""
        room_id = chat_history.ensure_room(
            f"agent:{user_id}", room_type="private", owner_id=user_id)
        chat_history.join_room(room_id, user_id)
        return room_id

    # ---------------------------------------------------------------- 禁言
    @staticmethod
    def mute_block(ctx: RequestContext) -> Optional[dict]:
        """被禁言的人不能发言（私聊、群聊、问 Agent 都挡）。"""
        muted = chat_history.active_mute(ctx.user_id)
        if not muted:
            return None
        until = parse_ts(muted["until_at"])
        left = int((until - datetime.now(timezone.utc)).total_seconds()) if until else 0
        return err("MUTED", f"你被 {muted['by_user'] or '管理员'} 禁言中，还剩 {max(left, 1)} 秒")

    def handle_mute(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        if ctx.user_id not in config.ADMIN_USERS:
            return err("FORBIDDEN", "只有管理员能禁言/解禁（在 .env 里配置 ADMIN_USERS）")

        action = (msg.get("action") or "list").strip()
        if action == "list":
            return {"type": "muted", "mutes": chat_history.active_mutes()}

        target = (msg.get("target") or "").strip()
        if not target:
            return err("BAD_PARAM", "target 不能为空")
        if target == ctx.user_id:
            return err("BAD_PARAM", "不能禁言自己")
        if chat_history.get_user(target) is None:
            return err("NOT_FOUND", f"用户 {target} 不存在")

        if action == "unmute":
            removed = chat_history.unmute_user(target)
            self.broadcast_mutes()
            if not removed:
                return err("BAD_STATE", f"{target} 当前没有被禁言")
            return {"type": "system", "msg": f"{ctx.user_id} 解除了 {target} 的禁言"}

        if action != "mute":
            return err("BAD_PARAM", "action 只能是 mute / unmute / list")

        try:
            minutes = int(msg.get("minutes") or 5)
        except (TypeError, ValueError):
            return err("BAD_PARAM", "minutes 必须是整数分钟")
        if not 1 <= minutes <= 1440:
            return err("BAD_PARAM", "minutes 必须在 1-1440 之间（最长 24 小时）")

        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        chat_history.mute_user(target, until.isoformat(timespec="seconds"),
                               ctx.user_id, (msg.get("reason") or "").strip())
        self.broadcast_mutes()
        log_line(f"[禁言] {ctx.user_id} 禁言 {target} {minutes} 分钟")
        return {"type": "system", "msg": f"{ctx.user_id} 禁言 {target} {minutes} 分钟"}

    def broadcast_mutes(self) -> None:
        self.users.broadcast({"type": "muted", "mutes": chat_history.active_mutes()})

    # ---------------------------------------------------------------- 群聊/私聊
    @staticmethod
    def _extract_body(msg: dict) -> Tuple[Optional[str], Optional[str], Optional[dict]]:
        """返回（入库内容, 附件引用或 None, 错误回复）。

        正文消息：content 就是用户打的字。
        附件消息：content 存附件服务上的文件名，display 由 meta 补上原名/大小。
        """
        attachment = msg.get("file") if msg.get("file") is not None else msg.get("image")
        if attachment is not None:
            ref = validate_attachment(attachment)
            if ref is None:
                return None, None, err("BAD_ATTACHMENT", "附件引用无效或文件已丢失，请重新上传")
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
        muted = self.mute_block(ctx)
        if muted:
            return muted

        content, attachment, bad = self._extract_body(msg)
        if bad:
            return bad

        meta = self._attachment_meta(attachment, msg)
        msg_type = attachment_kind(attachment) if attachment else "group"
        try:
            mid = chat_history.save_message(
                ctx.room_id, ctx.user_id, content, msg_type, meta)
        except Exception as e:
            return err("SAVE_FAILED", f"消息保存失败：{e}")

        log_chat("群聊", ctx.user_id, self._log_text(attachment, content, meta),
                 ctx.room_id, "main", ctx.addr)

        # @提及：只认真实存在的用户名，前端据此高亮/提醒被提到的人
        mentions = [n for n in dict.fromkeys(MENTION_RE.findall(content or ""))
                    if n != ctx.user_id and chat_history.get_user(n) is not None]

        payload = {
            "type": "group", "sender": ctx.user_id, "id": mid,
            "msg": self._msg_text(attachment, content, meta),
        }
        if mentions:
            payload["mentions"] = mentions
        if attachment:
            payload["msg_type"] = msg_type
            payload["image" if msg_type == "image" else "file"] = attachment
            if meta:
                payload["meta"] = meta
        # sender 由服务端填充！！！！
        self.users.broadcast(payload)
        return None

    def handle_private(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        muted = self.mute_block(ctx)
        if muted:
            return muted

        target = (msg.get("target") or "").strip()
        if not target:
            return err("BAD_PARAM", "target 不能为空")
        if target == ctx.user_id:
            return err("SELF_PM", "不能给自己发私聊")

        content, attachment, bad = self._extract_body(msg)
        if bad:
            return bad

        meta = self._attachment_meta(attachment, msg)
        msg_type = attachment_kind(attachment) if attachment else "private"
        try:
            room_name = self._pm_name(ctx.user_id, target)
            room_id = self._pm_room(ctx.user_id, target)
            mid = chat_history.save_message(
                room_id, ctx.user_id, content, msg_type, meta)
        except Exception as e:
            return err("SAVE_FAILED", f"消息保存失败：{e}")

        log_chat("私聊", ctx.user_id, self._log_text(attachment, content, meta),
                 room_id, room_name, ctx.addr, target=target)

        # target 一并回传：发送方要据此决定这条私聊落在哪个会话里
        payload = {
            "type": "private", "sender": ctx.user_id, "target": target,
            "msg": self._msg_text(attachment, content, meta), "id": mid,
        }
        if attachment:
            payload["msg_type"] = msg_type
            payload["image" if msg_type == "image" else "file"] = attachment
            if meta:
                payload["meta"] = meta
        delivered = self.users.send_to(target, payload)
        # 回显给自己，否则发送方本地的私聊会话里看不到自己刚发的那条
        ctx.send(payload)
        if not delivered:
            return err("USER_OFFLINE", f"用户 {target} 不在线，消息已存入历史")
        return None

    @staticmethod
    def _attachment_meta(attachment: Optional[str], msg: dict) -> Optional[dict]:
        """附件消息的附加信息（原名、大小、类型），存进 messages.meta 供历史和界面使用。"""
        if not attachment:
            return None
        meta = {
            "name": (msg.get("name") or "").strip()[:160] or attachment,
            "size": int(msg.get("size") or 0),
            "mime": (msg.get("mime") or "").strip()[:80],
        }
        return meta

    @staticmethod
    def _msg_text(attachment: Optional[str], content: str, meta: Optional[dict]) -> str:
        if not attachment:
            return content
        if attachment_kind(attachment) == "image":
            return "[图片]"
        return f"[文件 {(meta or {}).get('name') or attachment}]"

    @classmethod
    def _log_text(cls, attachment: Optional[str], content: str, meta: Optional[dict]) -> str:
        if not attachment:
            return content
        kind = "图片" if attachment_kind(attachment) == "image" else "文件"
        return f"[{kind} {(meta or {}).get('name') or attachment}]"

    @staticmethod
    def _pm_name(a: str, b: str) -> str:
        """两人私聊的固定房间名，按字典序排序保证双向一致。"""
        return "pm:" + ":".join(sorted([a, b]))

    @classmethod
    def _pm_room(cls, a: str, b: str) -> int:
        room_id = chat_history.ensure_room(cls._pm_name(a, b), room_type="private", owner_id=a)
        # 双方都登记成成员，登录时才知道"我参与过哪些私聊"，用来算离线未读
        chat_history.join_room(room_id, a)
        chat_history.join_room(room_id, b)
        return room_id

    # ---------------------------------------------------------------- Agent
    def handle_agent(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        muted = self.mute_block(ctx)
        if muted:
            return muted

        text = (msg.get("msg") or "").strip()
        if not text:
            return err("EMPTY_MSG", "问题为空")
        scope = msg.get("scope", "private")
        if scope not in ("private", "group"):
            return err("BAD_PARAM", "scope 只能是 private 或 group")

        include_private = bool(msg.get("include_private"))
        group_room = self.group_room_id()
        agent_room = self.agent_room_id(ctx.user_id)

        # 提问先作为一条真实消息落库：群里问就广播，私下问只进"我和 Agent"的房间
        try:
            if scope == "group":
                question = text if text.lower().startswith("@agent") else f"@Agent {text}"
                qid = chat_history.save_message(group_room, ctx.user_id, question, "agent_ask_group")
                self.users.broadcast({
                    "type": "group", "sender": ctx.user_id, "msg": question,
                    "msg_type": "agent_ask_group", "agent_scope": "group", "id": qid,
                })
                thread, answer_room = "main", group_room
            else:
                qid = chat_history.save_message(agent_room, ctx.user_id, text, "agent_ask_private")
                ctx.send({
                    "type": "agent_ask", "sender": ctx.user_id, "msg": text,
                    "scope": "private", "id": qid,
                })
                thread, answer_room = "agent", agent_room
        except Exception as e:
            return err("SAVE_FAILED", f"提问保存失败：{e}")

        # 勾了"包含私聊"就把这层授权明确写进这一轮的提示词里，
        # 否则模型只会按默认 scope=group 去读，勾选形同虚设
        prompt = text
        if include_private:
            prompt = (
                f"{text}\n\n"
                "（本次任务已授权你读取该用户与你的私聊记录："
                "请用 read_recent_chat_history(scope=\"agent_private\") 看一眼，"
                "如果里面有结论或待办，合并进回答。）"
            )

        ctx.send({
            "type": "agent", "sender": "Agent",
            "msg": "正在思考，请稍候…", "status": "pending",
            "scope": scope, "thread": thread,
        })
        self._agent_pool.submit(
            self._agent_task, ctx.user_id, ctx.conn, group_room,
            agent_room if include_private else None,
            prompt, scope, thread, answer_room,
        )
        return None

    def _agent_task(self, user_id: str, conn, group_room: int,
                    agent_room: Optional[int], text: str, scope: str,
                    thread: str, answer_room: int):
        try:
            reply, steps = agent_core.run_detailed(
                text, max_steps=config.AGENT_MAX_STEPS, room_id=group_room,
                user_id=user_id, agent_room_id=agent_room,
            )
        except Exception as e:
            print(f"[Agent] 调用异常: {e}")
            reply, steps = f"Agent 调用失败：{e}", []

        reply = _clamp_reply(reply)
        payload = {
            "type": "agent", "sender": "Agent", "msg": reply,
            "status": "done", "steps": steps, "scope": scope, "thread": thread,
        }
        try:
            payload["id"] = chat_history.save_message(answer_room, "Agent", reply, "agent")
        except Exception as e:
            print(f"[Agent] 回复落库失败: {e}")

        if thread == "main":
            log_chat("Agent", "Agent", reply, group_room, "main")
            self.users.broadcast(payload)
        else:
            log_chat("Agent", "Agent", f"（只回 {user_id}）{reply}", answer_room,
                     f"agent:{user_id}")
            self.users.send_to(user_id, payload, conn=conn)

    # ---------------------------------------------------------------- 撤回
    def handle_recall(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        try:
            msg_id = int(msg.get("id"))
        except (TypeError, ValueError):
            return err("BAD_PARAM", "撤回需要带上消息 id")

        row = chat_history.get_message(msg_id)
        if row is None:
            return err("NOT_FOUND", "消息不存在")
        if row["sender"] != ctx.user_id:
            return err("FORBIDDEN", "只能撤回自己发的消息")
        if row["msg_type"] in ("recalled", "summary"):
            return err("BAD_STATE", "这条消息不能撤回")

        created = parse_ts(row["created_at"])
        if created is not None:
            age = (datetime.now(timezone.utc) - created).total_seconds()
            if age > RECALL_WINDOW_SECONDS:
                return err("TOO_LATE", f"超过 {RECALL_WINDOW_SECONDS // 60} 分钟，不能撤回")

        if not chat_history.recall_message(msg_id, ctx.user_id):
            return err("FAILED", "撤回失败，请重试")

        payload = {"type": "recall", "id": msg_id, "sender": ctx.user_id,
                   "room_id": row["room_id"]}
        room_name = chat_history.room_name(row["room_id"]) or ""
        if room_name.startswith("agent:"):
            # 我和 Agent 的私聊：只通知本人
            ctx.send(payload)
        elif room_name.startswith("pm:"):
            other = room_name[3:].split(":")
            target = next((n for n in other if n != ctx.user_id), None)
            if target:
                self.users.send_to(target, payload)
            ctx.send(payload)
        else:
            self.users.broadcast(payload)

        log_line(f"[撤回] {ctx.user_id} 撤回了 room {row['room_id']} 的消息 #{msg_id}")
        return None

    # ---------------------------------------------------------------- 定时总结
    def submit_scheduled_summary(self, triggered_by: str = ""):
        """给调度器用的异步入口：Agent 调用会阻塞，丢进线程池，不占住调度线程。"""
        self._agent_pool.submit(self.run_scheduled_summary, triggered_by, False)

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

        reply = _clamp_reply(reply)
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

    # ---------------------------------------------------------------- 井字棋
    def _spectators(self, game) -> int:
        """观战人数 = 在线人数 - 这盘的两个玩家。"""
        online = set(self.users.online_users())
        players = {u for u in (game.x_user, game.o_user) if u}
        return max(0, len(online - players))

    def _game_state(self, game, viewer: Optional[str] = None) -> dict:
        """按视角裁剪后的结构化状态。21 点的暗牌在别人的视图里根本不存在。"""
        snap = game.view_for(viewer)
        snap["type"] = "game"
        snap["action"] = "state"
        snap["game_id"] = game.id
        snap["spectators"] = self._spectators(game)
        kind = getattr(game, "kind", "ttt")
        snap["scores"] = {u: self.games.score(u, kind)
                          for u in (game.x_user, game.o_user) if u}
        return snap

    @staticmethod
    def _game_result_text(game) -> str:
        if game.result == "draw":
            return "平局"
        return f"{game.players()[game.winner]} 获胜"

    def _game_line(self, game, note: str = "") -> str:
        players = game.players()
        label = game_service.game_name(getattr(game, "kind", "ttt"))
        head = f"[{label}] {players['X']} vs {players['O']}"
        if note:
            head += f" · {note}"
        if game.over:
            return f"{head} · 结果：{self._game_result_text(game)}"
        if getattr(game, "kind", "ttt") == "bj":
            seats = getattr(game, "seats", [])
            current = game.view_for(None)["bj"]["current"]
            who = f"轮到 {current}" if current else "结算中"
            return f"{head}（{len(seats)} 人同桌）· {who}"
        return f"{head} · 轮到 {players[game.turn]}"

    def _push_game(self, game, note: str = "", announce: bool = True) -> None:
        """按人裁剪后推送牌桌状态。

        棋类大家看到的是同一份；21 点的暗牌只发给本人，其他人的视图里根本没这张牌。
        """
        for user in self.users.online_users():
            self.users.send_to(user, self._game_state(game, user))
        if announce:
            self.users.broadcast({"type": "system", "msg": self._game_line(game, note)})

    def handle_game(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        # 禁言是"不能发言"，下棋会在群里广播，一并拦掉
        muted = self.mute_block(ctx)
        if muted:
            return muted

        text = (msg.get("text") or "").strip()
        action, _, rest = text.partition(" ")
        action = action.strip().lower()
        rest = rest.strip()

        if not action or action == "help":
            game = self.games.current(ctx.user_id)
            if game is None:
                return {"type": "system", "msg": GAME_HELP}
            ctx.send(self._game_state(game))
            return {"type": "system", "msg": self._game_line(game)}

        # ---------------- 跟 Agent 开一局 ----------------
        if action == "start":
            kind = (rest.strip().lower() or "ttt")
            if kind in ("ttt", "井字棋"):
                kind = "ttt"
            elif kind in ("gomoku", "五子棋", "gomoku5"):
                kind = "gomoku"
            elif kind in ("bj", "blackjack", "21", "21点"):
                kind = "bj"
            else:
                return err("BAD_PARAM", "支持：/game start、/game start gomoku、/game start bj")
            self.games.prune()
            for finished in self.games.finished_for(ctx.user_id):
                self._close_game(finished)
            current = self.games.current(ctx.user_id)
            if current is not None and not current.over:
                ctx.send(self._game_state(current))
                return {"type": "system",
                        "msg": "你还有一局没下完：\n" + self._game_line(current)}
            game = self.games.start_vs_agent(ctx.user_id, ctx.room_id, kind)
            label = game_service.game_name(kind)
            self._push_game(game, note=f"{ctx.user_id} 开局（{label}，对手：Agent）")
            return None

        # ---------------- 邀请另一位成员 ----------------
        if action == "invite":
            self.games.prune()
            parts = rest.split()
            target = parts[0] if parts else ""
            kind = parts[1].lower() if len(parts) > 1 else "ttt"
            if kind in ("gomoku", "五子棋"):
                kind = "gomoku"
            elif kind in ("bj", "21", "21点"):
                kind = "bj"
            else:
                kind = "ttt"
            if not target:
                return err("BAD_PARAM", "用法：/game invite 用户名")
            if chat_history.get_user(target) is None:
                return err("NOT_FOUND", f"用户 {target} 不存在")
            if not self.users.is_online(target):
                return err("USER_OFFLINE", f"{target} 不在线，等他上线再邀请")
            ok, detail = self.games.invite(ctx.user_id, target, kind)
            if not ok:
                return err("BAD_GAME", detail)
            self.users.send_to(target, {
                "type": "game", "action": "invite", "game_id": "",
                "from": ctx.user_id, "kind": kind,
                "ttl": game_service.INVITE_TTL_SECONDS,
            })
            return {"type": "system", "msg": f"[{game_service.game_name(kind)}] {detail}，对方发 /game accept 即可开局"}

        if action in ("accept", "decline"):
            pending = self.games.pending_invite(ctx.user_id)
            if pending is None:
                return err("NO_INVITE", "没有待处理的邀请（可能已过期）")
            inviter = pending["from"]
            if action == "decline":
                self.games.decline(ctx.user_id)
                self.users.send_to(inviter, {
                    "type": "system", "msg": f"[{game_service.game_name(kind)}] {ctx.user_id} 拒绝了你的邀请"})
                return {"type": "system", "msg": "已拒绝邀请"}
            ok, detail, game = self.games.accept(ctx.user_id)
            if not ok or game is None:
                return err("BAD_GAME", detail)
            self._push_game(game, note=f"{inviter}（X）vs {ctx.user_id}（O）开局")
            self.users.send_to(inviter, {"type": "system", "msg": f"[{game_service.game_name(game.kind)}] {detail}"})
            return {"type": "system", "msg": detail}

        # ---------------- 21 点：要牌 / 停牌 ----------------
        if action in ("hit", "stand"):
            game = self.games.current(ctx.user_id)
            if game is None or getattr(game, "kind", "ttt") != "bj":
                return err("NO_GAME", "你当前没有 21 点对局，先 /game start bj")
            if action == "hit":
                ok, detail = game.hit(ctx.user_id)
            else:
                ok, detail = game.stand(ctx.user_id)
            if not ok:
                return err("BAD_STATE", detail)
            self._push_game(game, announce=False)
            if game.over:
                self._finish_game(game, kind="bj")
            return None

        # ---------------- 落子 ----------------
        if action == "move":
            game = self.games.current(ctx.user_id)
            if game is None:
                return err("NO_GAME", "你当前没有进行中的对局，先 /game start 或 /game invite 用户名")
            try:
                cell = int(rest)
            except (TypeError, ValueError):
                return err("BAD_MOVE", "用法：/game move 5（1-9）")
            ok, detail = game.move(cell, user_id=ctx.user_id)
            if not ok:
                return err("BAD_MOVE", detail)

            self._push_game(game, note=f"{ctx.user_id} 下在 {cell}")
            if game.over:
                self._finish_game(game)
            elif getattr(game, "kind", "ttt") != "bj" and game.vs_agent and game.turn == "O":
                self._agent_pool.submit(self._game_agent_task, ctx.user_id, game)
            return None

        # ---------------- 观战 / 查询 ----------------
        if action == "watch":
            ongoing = self.games.ongoing()
            if not ongoing:
                return {"type": "system", "msg": "当前没有进行中的对局可观战。"}
            for game in ongoing:
                ctx.send(self._game_state(game))
            lines = ["进行中的对局："] + [self._game_line(g) for g in ongoing]
            lines.append("右栏棋盘可以直接看，观战时不能落子。")
            return {"type": "system", "msg": "\n".join(lines)}

        if action == "board":
            game = self.games.current(ctx.user_id)
            if game is None:
                return {"type": "system", "msg": "当前没有进行中的对局。\n" + GAME_HELP}
            ctx.send(self._game_state(game))
            return {"type": "system", "msg": self._game_line(game)}

        if action == "status":
            game = self.games.current(ctx.user_id)
            head = self.games.score_text(ctx.user_id)
            if game is not None:
                ctx.send(self._game_state(game))
                return {"type": "system", "msg": head + "\n" + self._game_line(game)}
            return {"type": "system", "msg": head + "\n当前没有进行中的对局。"}

        if action == "rematch":
            game = self.games.current(ctx.user_id)
            if game is None:
                finished = [g for g in self.games.finished_for(ctx.user_id) if not g.vs_agent]
                game = max(finished, key=lambda g: g.updated_at, default=None)
            if game is None:
                return err("NO_GAME", "没有可重开的对局，先 /game start 或 /game invite 用户名")
            if not game.over:
                return err("BAD_STATE", "这一局还没结束")
            if game.vs_agent:
                # 人和 Agent：不用等谁确认，直接开新局
                self._close_game(game)
                fresh = self.games.start_vs_agent(ctx.user_id, ctx.room_id)
                self._push_game(fresh, note=f"{ctx.user_id} 又来一局（对手：Agent）")
                return None

            ready, detail = game.vote_rematch(ctx.user_id)
            if not ready:
                self._push_game(game, announce=False)
                self.users.broadcast({"type": "system", "msg": (
                    f"[{game_service.game_name(getattr(game, 'kind', 'ttt'))}] {ctx.user_id} 想再来一局 · {detail}")})
                return None

            # 双方都确认：关掉旧局，换先手开新局
            self._close_game(game)
            fresh = self.games.rematch(game)
            self._push_game(fresh, note=(
                f"再来一局 · {fresh.players()['X']}（X）vs {fresh.players()['O']}（O）"))
            return None

        if action == "quit":
            current_game = self.games.current(ctx.user_id)
            if current_game is not None and getattr(current_game, "kind", "") == "bj":
                seats = [s for s in current_game.seats if s.user != ctx.user_id]
                if seats:
                    current_game.seats = seats
                    current_game._normalise_turn()
                    self._push_game(current_game, note=f"{ctx.user_id} 离开了牌桌", announce=True)
                    self.games.drop(ctx.user_id)
                    return {"type": "system", "msg": "你已离开牌桌"}
                self._close_game(current_game)
                return {"type": "system", "msg": "你已离开牌桌（这张桌没人了，已关闭）"}
            game = current_game
            if game is None:
                # 结束后玩家名额已释放：从"已结束但还留着"的棋局里找我那一盘
                finished = [g for g in self.games.finished_for(ctx.user_id) if not g.vs_agent]
                game = max(finished, key=lambda g: g.updated_at, default=None)
                if game is None:
                    return {"type": "system", "msg": "当前没有进行中的对局。"}
                self._close_both(ctx.user_id, game, "退出了对局")
                return {"type": "system", "msg": "已退出，这一局对双方都关闭了。"}
            if not game.over and not game.vs_agent and game.forfeit(ctx.user_id):
                # 人对人中途退出：判对方胜，然后把这一局对双方关闭
                self.games.record(game)
                self._push_game(game, note=f"{ctx.user_id} 认输")
                self._close_both(ctx.user_id, game, "认输退出")
                return {"type": "system", "msg": "你已认输退出，这一局对双方都结束了。"}
            else:
                # 人对 Agent：只关掉自己这一局
                self._close_game(game)
                self.users.broadcast({"type": "system", "msg": (
                    f"[{game_service.game_name(getattr(game, 'kind', 'ttt'))}] {ctx.user_id} 退出了对局。{self.games.score_text(ctx.user_id, getattr(game, 'kind', 'ttt'))}")})
            return None

        return err("BAD_GAME",
                   "用法：/game start | invite 用户名 | accept | decline | "
                   "move 5 | watch | board | status | quit")

    def _finish_game(self, game, kind: str = "ttt") -> None:
        """收尾：记战绩、广播最终棋盘。

        这里故意不发 closed：客户端要留着棋盘给双方看结果，等他们开新局或点"关闭"再清。
        """
        if not game.over:
            return
        self.games.record(game)
        self._push_game(game, note="本局结束")
        self.games.release(game)

    def _close_both(self, user_id: str, game, reason: str) -> None:
        """人对人：一个人点退出，两个人的棋局一起关掉。"""
        self.users.broadcast({"type": "game", "action": "closed", "game_id": game.id})
        self.games.close(game)
        self.users.broadcast({"type": "system", "msg": (
            f"[{game_service.game_name(getattr(game, 'kind', 'ttt'))}] {user_id} {reason}，本局已结束。"
            f"{self.games.score_text(user_id, getattr(game, 'kind', 'ttt'))}")})

    def _close_game(self, game) -> None:
        self.users.broadcast({"type": "game", "action": "closed", "game_id": game.id})
        self.games.close(game)

    def handle_disconnect(self, user_id: str) -> None:
        """连接断开（主动退出或被心跳回收）：对局里的一方掉线，判对方胜。"""
        if not user_id or self.users.is_online(user_id):
            return          # 换号登录/多端登录：这个人还在线，别动他的棋局
        self.games.clear_invites(user_id)
        game = self.games.current(user_id)
        if game is None or game.over:
            return
        if getattr(game, "kind", "") == "bj":
            # 21 点是一桌人：掉线只摘掉自己的座位，别把别人的牌局cancel掉
            left = self.games.remove_player(game, user_id)
            if not left:
                self._close_game(game)
                self.users.broadcast({"type": "system", "msg": "[21 点] 牌桌没人了，已关闭"})
            else:
                self._push_game(game, note=f"{user_id} 掉线离开", announce=True)
            return
        if game.vs_agent:
            self._close_game(game)
            self.users.broadcast({"type": "system", "msg": (
                f"[{game_service.game_name(getattr(game, 'kind', 'ttt'))}] {user_id} 掉线，对局已取消")})
            return
        if game.forfeit(user_id):
            self.games.record(game)
            # 保留棋盘给还在线的一方看结果，只释放玩家名额（开新局时会清理）
            self._push_game(game, note=f"{user_id} 掉线，判负")
            self.games.release(game)
            log_line(f"[Game] {user_id} 掉线，对局 {game.id} 判负收尾")

    def _game_local_move(self, user_id: str, game, label: str) -> None:
        """纯本地落子：不调用模型，几乎瞬间完成。适合演示时不想等模型的地方。"""
        cell = game.auto_move()
        if cell is None:
            return
        row, col = divmod(cell - 1, getattr(game, "size", 3))
        where = f"{row + 1} 行 {col + 1} 列" if getattr(game, "size", 3) > 3 else f"第 {cell} 格"
        text = f"我下在{where}（本地策略，未调用模型）。"
        if game.over:
            text += f"\n结果：{self._game_result_text(game)}"
        if getattr(game, "kind", "ttt") != "gomoku":
            text = f"{text}\n\n{game.render()}"

        self._push_game(game, announce=False)
        payload = {"type": "agent", "sender": "Agent", "msg": text,
                   "status": "done", "steps": [], "scope": "group"}
        try:
            payload["id"] = chat_history.save_message(
                self.group_room_id(), "Agent", text, "agent")
        except Exception as e:
            print(f"[Game] 落库失败: {e}")
        self.users.broadcast(payload)
        if game.over:
            self._finish_game(game)
        else:
            self.users.broadcast({"type": "system", "msg": self._game_line(game, "本地策略落子")})

    def _game_agent_task(self, user_id: str, game) -> None:
        """Agent 的一轮落子。

        三档速度（AGENT_GAME_FAST）：
          0  普通请求：带思考链，约 3 秒一步
          1  快路径：关思考 + 短超时，约 1.5 秒一步，仍由模型选点并点评
          2  纯本地：启发式直接落子、不调用模型，几乎瞬间完成（会注明未调用模型）
        """
        label = game_service.game_name(getattr(game, "kind", "ttt"))
        if config.AGENT_GAME_FAST >= 2:
            self._game_local_move(user_id, game, label)
            return

        # 给模型一个参考落点：不强制，但能大幅减少“落在已有棋子上”的无效重试
        suggestion = ""
        if getattr(game, "kind", "ttt") == "gomoku":
            hint = game_service.best_gomoku_move(list(game.board), game.size, "O")
            if hint is not None:
                suggestion = f"参考落点：{hint}（你也可以选别的合法位置）。"
        prompt = (
            f"你在和用户 {user_id} 玩{label}。你执 O，对方执 X，对方先手。\n"
            f"当前棋盘（数字是空位）：\n{game.render()}\n"
            f"可落子位置：{game.legal_moves()[:60]}（共 {len(game.legal_moves())} 个）。\n"
            f"{suggestion}\n"
            "规则：必须调用 game_move(cell) 落子，cell 只能从可落子位置里取；"
            "落子后用一句话点评这步棋，不要输出完整棋谱，也不要替玩家落子。"
        )
        spec, tools = game_service.game_tools(game, user_id)
        try:
            # 落子是"每步都要等"的调用，走快路径：不要思考链、短超时
            reply, steps = agent_core.run_detailed(
                prompt, max_steps=2, room_id=self.group_room_id(),
                user_id=user_id, extra_tools=(spec, tools),
                fast=config.AGENT_GAME_FAST)
        except Exception as e:
            print(f"[Game] Agent 调用异常: {e}")
            reply, steps = f"Agent 调用失败：{e}", []

        if game.cancelled:
            return

        # 模型没落子（或着法非法又没纠正）时用本地 minimax 兜底，别把棋局卡死
        fallback = False
        if not game.over and game.turn == "O":
            cell = game.auto_move()
            if cell is not None:
                fallback = True
                reply = (reply or "").strip() + f"\n（模型没有给出合法落子，已用本地策略下在 {cell}）"

        text = _clamp_reply((reply or "").strip())
        if game.over:
            text += f"\n结果：{self._game_result_text(game)}"
        if getattr(game, "kind", "ttt") != "gomoku":
            text = f"{text}\n\n{game.render()}"

        # 先推状态，再广播 Agent 的点评
        self._push_game(game, announce=False)

        payload = {"type": "agent", "sender": "Agent", "msg": text,
                   "status": "done", "steps": steps, "scope": "group"}
        try:
            payload["id"] = chat_history.save_message(
                self.group_room_id(), "Agent", text, "agent")
        except Exception as e:
            print(f"[Game] 落库失败: {e}")
        self.users.broadcast(payload)

        if game.over:
            self._finish_game(game)
        elif fallback:
            log_line(f"[Game] {user_id} 的对局由本地策略代打了一步")
            self.users.broadcast({"type": "system", "msg": self._game_line(game, "Agent 落子")})

    # ---------------------------------------------------------------- 定时任务
    def handle_task(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need
        if self.scheduler is None:
            return err("NO_SCHEDULER", "服务端没有启用定时任务调度器")

        text = (msg.get("text") or "").strip()
        action, _, rest = text.partition(" ")
        action = action.strip().lower() or "list"
        rest = rest.strip()

        if action == "list":
            return {"type": "system", "msg": self.scheduler.describe_all()}

        if action == "add":
            ok, out = self.scheduler.add_from_text(rest, ctx.user_id, ctx.room_id)
            return {"type": "system", "msg": out} if ok else err("BAD_TASK", out)

        if action in ("del", "on", "off"):
            try:
                task_id = int(rest)
            except (TypeError, ValueError):
                return err("BAD_PARAM", "用法：/task del|on|off <任务编号>")
            if action == "del":
                ok, out = self.scheduler.remove(task_id)
            else:
                ok, out = self.scheduler.set_enabled(task_id, action == "on")
            return {"type": "system", "msg": out} if ok else err("BAD_TASK", out)

        return err("BAD_PARAM",
                   "用法：/task list、/task add summary every:10、"
                   "/task add reminder in:5 开会、/task del|on|off <编号>")

    # ---------------------------------------------------------------- 历史/待办
    def handle_history(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        need = ctx.require_login()
        if need:
            return need

        if msg.get("agent"):
            room_id = self.agent_room_id(ctx.user_id)
            target = ""
        elif (msg.get("target") or "").strip():
            target = msg["target"].strip()
            room_id = chat_history.room_id_by_name("pm:" + ":".join(sorted([ctx.user_id, target])))
            if room_id is None:
                return {"type": "history", "target": target, "items": []}
        else:
            target = ""
            room_id = ctx.room_id

        limit = msg.get("limit", 20)
        before_id = msg.get("before_id")
        if before_id:
            rows = chat_history.get_history_before(room_id, before_id, limit)
        else:
            rows = chat_history.get_recent_history(room_id, limit)
        rows = list(rows)

        # 按字节数收缩这一页：长消息太多时不硬塞进一帧，宁可少给几条让客户端继续翻页
        trimmed = False
        kept: List[Message] = []
        total = 0
        for m in rows:                      # rows 是从新到旧
            size = len(m.content.encode("utf-8")) + 120
            if kept and total + size > MAX_HISTORY_BYTES:
                trimmed = True
                break
            kept.append(m)
            total += size
        rows = kept

        items = [
            {
                "id": m.id,
                "sender": m.sender,
                "content": m.content,
                "msg_type": m.msg_type,
                "meta": m.meta,
                "created_at": m.timestamp.isoformat() if m.timestamp else None,
            }
            for m in reversed(rows)
        ]
        return {"type": "history", "target": target or None, "items": items,
                "agent": bool(msg.get("agent")),
                "before_id": before_id,
                "more": trimmed or len(rows) >= chat_history._clamp(limit)}

    def handle_read(self, ctx: RequestContext, msg: dict) -> Optional[dict]:
        """已读回执：客户端把"我看到的最后一条 id"报上来，下次登录就不算它未读了。"""
        need = ctx.require_login()
        if need:
            return need
        try:
            if msg.get("agent"):
                room_id = self.agent_room_id(ctx.user_id)
            else:
                target = (msg.get("target") or "").strip()
                room_id = (chat_history.room_id_by_name(self._pm_name(ctx.user_id, target))
                           if target else ctx.room_id)
            if room_id is None:
                return None
            chat_history.mark_read(room_id, ctx.user_id, msg.get("id"))
        except Exception as e:
            log_line(f"[Read] 标记已读失败 {ctx.user_id}: {e}")
        return None

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
            ts = m.timestamp.astimezone().strftime("%m-%d %H:%M") if m.timestamp else "-"
            lines.append(f"[{ts}] {m.sender}: {content}")
        return "\n".join(lines)

    def shutdown(self):
        self._agent_pool.shutdown(wait=False)
