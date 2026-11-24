"""服务端终端的输出工具：控制台编码兜底 + 聊天消息统一日志。"""

import sys
import threading

# 终端里一行消息最多打这么多字，超了截断，避免一条长消息刷屏
MAX_LOG_CHARS = 300

_print_lock = threading.Lock()


def make_console_safe() -> None:
    """Windows 控制台默认是 GBK，打一行带 emoji 的日志就抛 UnicodeEncodeError。

    聊天内容里出现表情（👍）时，服务端任何 print 都可能因此炸掉正在跑的线程，
    所以启动时统一把 stdout/stderr 设成"编不出来的字符替换掉"，而不是直接报错。
    被重定向到文件时顺手切成 UTF-8，免得日志文件里中文变乱码。
    """
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8")
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def log_line(text: str) -> None:
    """整行一次写出去。多个连接线程同时打印时，print() 会把两行粘在一起。"""
    with _print_lock:
        try:
            sys.stdout.write(text + "\n")
            sys.stdout.flush()
        except ValueError:
            pass  # 进程正在退出，stdout 已关闭


def log_chat(kind: str, sender: str, content: str, room_id: int, room_name: str,
             addr: tuple = (), target: str = None) -> None:
    """在服务端终端打一条聊天消息。

    群聊和私聊都打，并且带上各自的 room_id / 房间名 / 来源连接，
    这样终端上能直接看出"私聊只是同一个聊天室里的另一条投递路径"。

        [群聊] alice 说：大家好（room 1 main · 127.0.0.1:51234）
        [私聊] alice 对 bob 说：在吗（room 8 pm:alice:bob · 127.0.0.1:51234）
    """
    text = " ".join((content or "").split())
    if len(text) > MAX_LOG_CHARS:
        text = text[:MAX_LOG_CHARS] + "…"

    who = f"{sender} 对 {target} 说：" if target else f"{sender} 说："
    where = f"room {room_id} {room_name}"
    if addr:
        where += f" · {addr[0]}:{addr[1]}"
    log_line(f"[{kind}] {who}{text}（{where}）")
