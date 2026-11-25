# TLV协议：Type + Length（Value的长度） + Value

import struct
import json
from typing import Tuple, List

class TLVProtocol:
    @staticmethod
    def encode(msg_type: int, body: dict) -> bytes:
        """TLV消息打包，对外发送完整数据包"""
        body_bytes = json.dumps(body, ensure_ascii=False).encode('utf-8')
        length = len(body_bytes) # 后续 Value 数据的总长度
        # !HH：大端序
        header = struct.pack('!HH', msg_type, length)
        return header + body_bytes

    @staticmethod
    def decode(buffer: bytes) -> Tuple[List[dict], bytes]:
        """TLV消息解包，处理缓冲区数据，解析完整消息，返回未用完的半包数据"""
        full_msgs = []
        while len(buffer) >= 4:
            msg_type, length = struct.unpack('!HH', buffer[:4])
            if len(buffer) < 4 + length:
                break
            body_bytes = buffer[4:4 + length]
            buffer = buffer[4 + length:]

            try:
                body_dict = json.loads(body_bytes.decode('utf-8'))
                full_msgs.append({"msg_type": msg_type, "body": body_dict})
            except json.JSONDecodeError:
                print("[Warning] 收到非法 JSON 数据，已丢弃")

        return full_msgs, buffer


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
    "read": 14,
    "unread": 15,
    "recall": 16,
    "mute": 17,
    "muted": 18,
}

CODE_TYPE = {code: name for name, code in TYPE_CODE.items()}


def pack_message(msg: dict) -> bytes:
    """把消息字典打包成 type + length + JSON 的完整数据包"""
    body_bytes = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    msg_type = TYPE_CODE.get(msg.get("type"), 0)
    return struct.pack("!HH", msg_type, len(body_bytes)) + body_bytes


def try_unpack(buffer: bytes):
    """从缓冲区里取出一条消息，返回 (消息字典或None, 剩余数据)；数据非法时返回 ({}, 剩余)"""
    if len(buffer) < 4:
        return None, buffer
    msg_type, length = struct.unpack("!HH", buffer[:4])
    if len(buffer) < 4 + length:
        return None, buffer

    body_bytes = buffer[4:4 + length]
    rest = buffer[4 + length:]
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
