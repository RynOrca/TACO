import copy
from datetime import datetime
from typing import Callable, Dict, List, Optional, Tuple

from server.config import TAVILY_API_KEY
from server.models import Message
from server.storage import chat_history

MAX_LIMIT = 100
MAX_OUTPUT_CHARS = 4000
MAX_CONTENT_CHARS = 200


def _truncate(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    """压缩空白并截断，避免超长内容污染上下文。"""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"


def _err(msg: str) -> str:
    """错误信息写给模型看：说明原因 + 下一步怎么做。"""
    return f"[ToolError] {msg}"


def _clamp(limit: int, default: int = 20) -> int:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, MAX_LIMIT))


def _format_rows(rows, room_id: Optional[int] = None, header: str = "") -> str:
    """把 Message 列表格式化为文本。"""
    lines = [header] if header else []
    for m in rows:
        if isinstance(m, Message):
            ts = m.timestamp.strftime("%m-%d %H:%M") if m.timestamp else "-"
            lines.append(f"[{ts}] {m.sender}: {_truncate(m.content)}")
        else:  # 兼容旧的 (sender, content, time) 返回
            lines.append(f"[{m[2]}] {m[0]}: {_truncate(m[1])}")
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def get_current_time() -> str:
    """读取服务器所在机器的当前系统时间（真实执行，不是模型猜的）。"""
    now = datetime.now()
    tz = now.astimezone().tzinfo
    return (
        f"服务器当前时间：{now:%Y-%m-%d %H:%M:%S}（{WEEKDAY_CN[now.weekday()]}）\n"
        f"时区：{tz}，UTC 偏移 {now.astimezone():%z}\n"
        f"Unix 时间戳：{int(now.timestamp())}"
    )


def _require_group_room(room_id: int) -> Optional[str]:
    """护栏：Agent 只允许碰群聊房间。私聊房间一律拒绝，报错写回给模型。"""
    try:
        is_group = chat_history.is_group_room(room_id)
    except (TypeError, ValueError):
        is_group = False
    if is_group:
        return None
    return _err(
        "当前会话是私聊房间，不在 Agent 的授权范围内："
        "你只能读取群聊里的内容，看不到任何两个人之间的私聊记录。"
    )


def tavily_search(query: str, max_results: int = 5, max_content_length: int = 300) -> str:
    """联网搜索实时信息，返回带标题/URL/摘要的纯文本。"""
    if not query or not query.strip():
        return _err("query 不能为空，请提供具体的搜索词。")
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = client.search(
            query=query.strip(),
            max_results=_clamp(max_results, default=5),
            search_depth="basic",
        )
    except Exception as e:
        return _err(f"搜索失败：{e}。可改用已有知识回答，并向用户说明未能联网核实。")

    results = resp.get("results") or []
    if not results:
        return f"未找到与「{query}」相关的结果。"

    lines = [f"搜索词：{query}", f"结果数：{len(results)}"]
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "").strip()
        url = r.get("url") or ""
        content = _truncate(r.get("content") or "", int(max_content_length))
        lines.append(f"[{i}] {title}\nURL：{url}\n内容：{content}")
    return "\n".join(lines)[:MAX_OUTPUT_CHARS]


def read_recent_chat_history(room_id: int, limit: int = 20) -> str:
    """读取指定聊天室最近的消息，按时间正序返回。"""
    denied = _require_group_room(room_id)
    if denied:
        return denied
    limit = _clamp(limit)
    rows = chat_history.get_recent_history(room_id, limit)
    if not rows:
        return f"聊天室 {room_id} 暂无聊天记录。"

    rows = list(rows)[::-1]          # DAO 是倒序取的，这里反转成正序
    header = f"聊天室 {room_id} 最近 {len(rows)} 条记录（时间正序）："
    return _format_rows(rows, header=header)


def save_history_and_todo(room_id: int, content: str, kind: str) -> str:
    """把已生成好的总结/待办写入数据库。content 必须是成品文本。"""
    denied = _require_group_room(room_id)
    if denied:
        return denied
    if not content or not content.strip():
        return _err("content 为空，请先生成内容再保存。")
    if kind == "summary":
        new_id = chat_history.save_history(room_id, content.strip())
        return f"会话总结已保存（记录 id={new_id}）。"
    if kind == "todo":
        new_id = chat_history.save_todo(room_id, content.strip())
        return f"待办事项已保存（记录 id={new_id}）。"
    return _err(f"kind 只能是 summary 或 todo，收到的是 {kind!r}。")


def search_chat_history(room_id: int, keywords: List[str], limit: int = 20) -> str:
    """按关键词检索历史消息（多关键词 OR 匹配）。"""
    if isinstance(keywords, str):
        keywords = [keywords]
    keywords = [k.strip() for k in (keywords or []) if k and k.strip()]
    if not keywords:
        return _err("未提供有效关键词。可先调用 read_recent_chat_history 了解上下文。")

    denied = _require_group_room(room_id)
    if denied:
        return denied
    limit = _clamp(limit)
    print(f"[Tool] 搜索历史消息：room={room_id}，关键词={keywords}")
    rows = chat_history.search_history(room_id, keywords, limit)
    if not rows:
        return f"聊天室 {room_id}，关键词 {keywords}：无搜索结果"

    header = f"关键词 {keywords} 命中 {len(rows)} 条："
    return _format_rows(rows, header=header)


# ===================== 工具声明（Function Calling）=====================
TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "读取服务器当前的系统时间（真实执行，返回日期、星期、时区、Unix 时间戳）。\n"
                "使用场景：用户问“现在几点/今天几号/星期几”，"
                "或需要算出聊天记录里某条消息距现在多久、判断“这周/上周”的范围。\n"
                "不要使用：能靠上下文推断出时间的问题。"
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": (
                "联网搜索实时信息（新闻、天气、价格、软件最新版本、赛事结果等）。\n"
                "使用场景：问题涉及模型知识截止后的动态信息，或用户明确要求“查一下/搜一下”。\n"
                "不要使用：闲聊、纯代码推理、能靠聊天记录或已有知识回答的问题。\n"
                "示例：用户问“最近有什么大模型发布” → "
                "tavily_search(query=\"2026 大模型发布\", max_results=5)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索词，尽量具体，含时间/实体限定"},
                    "max_results": {"type": "integer", "default": 5, "description": "返回条数，1-10"},
                    "max_content_length": {
                        "type": "integer", "default": 300,
                        "description": "每条结果正文的截断长度"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_recent_chat_history",
            "description": (
                "读取当前聊天室最近的消息原文，按时间正序返回。\n"
                "使用场景：用户问“刚才说了什么”“总结一下刚才的讨论”“我上次说过什么”等需要原文上下文的问题。\n"
                "示例：用户说“帮我总结群里刚才聊的” → read_recent_chat_history(limit=30)，再基于返回内容总结。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer", "description": "聊天室 ID（由系统提供，通常无需手动填写）"},
                    "limit": {"type": "integer", "default": 20, "description": "读取条数，1-100"},
                },
                "required": ["room_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_history_and_todo",
            "description": (
                "把已经生成好的总结或待办事项写入数据库。\n"
                "content 必须是最终成品文本，不要包含“以下是总结”这类引导语或思考过程。\n"
                "kind=\"summary\" 保存会话总结；kind=\"todo\" 保存待办事项（建议用“- [ ] 任务”列表）。\n"
                "示例：save_history_and_todo(content=\"1. 周五上线；2. 张三负责联调\", kind=\"summary\")。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer", "description": "聊天室 ID（由系统提供，通常无需手动填写）"},
                    "content": {"type": "string", "description": "要保存的成品文本"},
                    "kind": {
                        "type": "string", "enum": ["summary", "todo"],
                        "description": "保存类型：summary=会话总结，todo=待办事项"
                    },
                },
                "required": ["room_id", "content", "kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_chat_history",
            "description": (
                "按关键词在当前聊天室的历史消息中检索，多个关键词按 OR 匹配。\n"
                "使用场景：“上周谁提过性能优化”这类跨时间的定向查找；"
                "不确定关键词时先用 read_recent_chat_history 了解上下文。\n"
                "示例：search_chat_history(keywords=[\"性能\", \"压测\"], limit=20)。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "room_id": {"type": "integer", "description": "聊天室 ID（由系统提供，通常无需手动填写）"},
                    "keywords": {
                        "type": "array", "items": {"type": "string"},
                        "description": "检索关键词列表，OR 匹配"
                    },
                    "limit": {"type": "integer", "default": 20, "description": "最多返回条数"},
                },
                "required": ["room_id", "keywords"],
            },
        },
    },
]

TOOLS = {
    "get_current_time": get_current_time,
    "tavily_search": tavily_search,
    "read_recent_chat_history": read_recent_chat_history,
    "save_history_and_todo": save_history_and_todo,
    "search_chat_history": search_chat_history,
}

_ROOM_BOUND = {
    "read_recent_chat_history",
    "save_history_and_todo",
    "search_chat_history",
}


def build_room_tools(room_id: int, user_id: str = None) -> Tuple[List[dict], Dict[str, Callable]]:
    """
    为连接生成「已绑定 room_id」的工具规格与实现。

    关键点：room_id 从 schema 中移除，模型看不到也填不了，只能通过闭包
    拿到服务端注入的可信值，从根本上杜绝越权读取其他会话。
    """
    spec: List[dict] = []
    for tool in TOOLS_SPEC:
        name = tool["function"]["name"]
        if name not in _ROOM_BOUND:
            continue
        tool = copy.deepcopy(tool)                     # 深拷贝，避免污染全局 TOOLS_SPEC
        params = tool["function"]["parameters"]
        params["properties"].pop("room_id", None)
        required = params.get("required", [])
        if "room_id" in required:
            required.remove("room_id")
        spec.append(tool)

    tools_map: Dict[str, Callable] = {
        "read_recent_chat_history": lambda limit=20: read_recent_chat_history(room_id, limit),
        "save_history_and_todo": lambda content, kind: save_history_and_todo(room_id, content, kind),
        "search_chat_history": lambda keywords, limit=20: search_chat_history(room_id, keywords, limit),
        "tavily_search": tavily_search,                # 联网能力保留
        "get_current_time": get_current_time,          # 与房间无关
    }
    # 与房间无关的工具原样带进 spec
    for tool in TOOLS_SPEC:
        if tool["function"]["name"] not in _ROOM_BOUND:
            spec.append(copy.deepcopy(tool))
    return spec, tools_map


# 启动自检：声明与实现必须一一对应
assert set(TOOLS) == {t["function"]["name"] for t in TOOLS_SPEC}, "TOOLS 与 TOOLS_SPEC 不一致"