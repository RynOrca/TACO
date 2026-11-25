# TACO 应用层协议 v2
#
# 帧格式（8 字节定长头，大端）：
#
#   +--------+---------+--------+----------------+-----------------+
#   | magic  | version | type   | length         | body (JSON)     |
#   | uint16 | uint8   | uint8  | uint32         | length 字节      |
#   | 0x5443 | 2       | 0-255  | 上限 2MB        | UTF-8           |
#   +--------+---------+--------+----------------+-----------------+
#
# 为什么从 v1 的 type(2)+length(2) 升级：
#   1. v1 的 length 是 uint16，单帧最大 65535 字节。历史分页 20 条长中文、
#      Agent 长回复都会超过这个值，struct.pack 直接抛异常，客户端连错误码都收不到。
#   2. v1 没有版本标识：服务端拿到半截 v2 帧头只会当成"非法 JSON"丢弃，无法提示版本不匹配。
#   3. magic 让"连错端口/说错协议"变成一个明确的错误，而不是靠猜。
#
# 粘包/拆包的约定没有变：接收端用缓冲区累积，`try_unpack` 返回 (None, buffer) 表示
# 半包，等下一次 recv；一次 recv 里有多包时循环解完为止。

import json
import struct

MAGIC = 0x5443          # "TC"
VERSION = 2
HEADER = struct.Struct("!HBBI")   # magic, version, type, length
HEADER_SIZE = HEADER.size          # 8

# 单帧 body 上限。既够装下 600KB 的历史页，也能挡住"声明 4GB 长度"的恶意包。
MAX_FRAME_BYTES = 2 * 1024 * 1024


class ProtocolError(Exception):
    """帧头不合法：魔数/版本不对，或声明的长度超过上限。"""


class FrameTooLarge(ValueError):
    """要发送的 body 超过单帧上限。调用方应回一条错误帧，而不是断开连接。"""


TYPE_CODE = {
    "login": 1,
    "group": 2,
    "private": 3,
    "agent": 4,
    "ping": 5,
    "pong": 6,
    "system": 7,
    "userlist": 8,
    "error": 9,
    "register": 10,
    "todos": 11,
    "history": 12,
    "autosummary": 13,
    "task": 14,
    "game": 15,
}

CODE_TYPE = {code: name for name, code in TYPE_CODE.items()}


def pack_message(msg: dict) -> bytes:
    """把消息字典打包成 v2 帧。body 超限抛 FrameTooLarge，由调用方决定怎么处理。"""
    body_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if len(body_bytes) > MAX_FRAME_BYTES:
        raise FrameTooLarge(
            f"消息体 {len(body_bytes)} 字节，超过单帧上限 {MAX_FRAME_BYTES} 字节"
        )
    msg_type = TYPE_CODE.get(msg.get("type"), 0)
    if not 0 <= msg_type <= 0xFF:
        raise ValueError(f"消息类型编码越界：{msg_type}")
    return HEADER.pack(MAGIC, VERSION, msg_type, len(body_bytes)) + body_bytes


def try_unpack(buffer: bytes):
    """从缓冲区里取出一条消息。

    返回 (消息字典或 None, 剩余数据)：
      - None  表示半包，等下一次 recv；
      - {}    表示 body 不是合法 JSON，已丢弃；
      - 抛出 ProtocolError 表示帧头不合法（魔数/版本/长度），调用方应关闭连接。
    """
    if len(buffer) < HEADER_SIZE:
        return None, buffer

    magic, version, msg_type, length = HEADER.unpack_from(buffer)
    if magic != MAGIC:
        raise ProtocolError(
            f"帧头魔数不匹配（收到 {magic:#06x}）：可能连错了端口，或客户端不是 v{VERSION} 协议"
        )
    if version != VERSION:
        raise ProtocolError(f"协议版本不支持（收到 v{version}，服务端支持 v{VERSION}）：请更新客户端")
    if length > MAX_FRAME_BYTES:
        raise ProtocolError(f"帧长度 {length} 超过上限 {MAX_FRAME_BYTES}，已拒绝")

    if len(buffer) < HEADER_SIZE + length:
        return None, buffer

    body_bytes = buffer[HEADER_SIZE:HEADER_SIZE + length]
    rest = buffer[HEADER_SIZE + length:]
    try:
        msg = json.loads(body_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("[Warning] 收到非法 JSON 数据，已丢弃")
        return {}, rest
    if not isinstance(msg, dict):
        return {}, rest

    name = CODE_TYPE.get(msg_type)
    if name:
        msg.setdefault("type", name)
    return msg, rest
