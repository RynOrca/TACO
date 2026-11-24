"""Windows 控制台默认是 GBK，打一行带 emoji 的日志就抛 UnicodeEncodeError。

聊天内容里出现表情（👍）时，服务端任何 print 都可能因此炸掉正在跑的线程，
所以启动时统一把 stdout/stderr 设成"编不出来的字符替换掉"，而不是直接报错。
"""

import sys


def make_console_safe() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass  # 被重定向到文件或管道时也不用管
