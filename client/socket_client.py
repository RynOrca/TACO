import socket
import threading
import time

from server import config
from server.console import make_console_safe
from server.network.protocol import ProtocolError, pack_message, try_unpack

HOST = "127.0.0.1"
PORT = 10086


class ChatClient:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.username = None
        self.running = False
        self.rtt_ms = None
        self._send_lock = threading.Lock()   # 保护 sendall，避免多线程交错
        self._ping_sent = {}                 # seq -> 发送时刻(ms)，用来算 RTT
        self._ping_seq = 0
        self._hb_stop = threading.Event()

    def connect(self, retries=3, delay=2):
        for i in range(retries):
            try:
                self.sock = socket.create_connection((self.host, self.port), timeout=5)
                self.sock.settimeout(None)
                self.running = True
                # 重连时换一个新的停止事件，避免上一轮心跳线程被"复活"
                self._hb_stop = threading.Event()
                print(f"已连接到服务器 {self.host}:{self.port}")
                return True
            except Exception as e:
                print(f"连接失败({i + 1}/{retries}): {e}")
                time.sleep(delay)
        return False

    def start_heartbeat(self, interval: int = None):
        """定时发 ping。服务端靠它判断连接是否还活着，同时用应答算 RTT。"""
        interval = interval or config.HEARTBEAT_SECONDS
        stop = self._hb_stop

        def loop():
            while self.running and not stop.wait(interval):
                self._ping_seq += 1
                now_ms = int(time.time() * 1000)
                self._ping_sent[self._ping_seq] = now_ms
                # 只留最近 10 个，避免长时间运行后字典无限增长
                for seq in list(self._ping_sent)[:-10]:
                    self._ping_sent.pop(seq, None)
                self.send({"type": "ping", "seq": self._ping_seq, "ts": now_ms})

        threading.Thread(target=loop, daemon=True, name="heartbeat").start()

    def note_pong(self, msg: dict):
        """收到 pong 时算 RTT（毫秒）。返回 None 表示这轮的 seq 已经过期。"""
        seq = msg.get("seq")
        sent = self._ping_sent.pop(seq, None) if seq is not None else None
        if sent is not None:
            self.rtt_ms = int(time.time() * 1000) - sent
        return self.rtt_ms

    def send(self, msg_dict: dict):
        if not self.sock:
            print("未连接，消息丢弃")
            return
        pkg = pack_message(msg_dict)
        with self._send_lock:
            try:
                self.sock.sendall(pkg)
            except Exception as e:
                print(f"发送失败: {e}")

    def recv_loop(self):
        buffer = b""
        while self.running:
            try:
                data = self.sock.recv(1024)
            except Exception as e:
                if self.running:
                    print(f"\n连接中断: {e}")
                break
            if not data:
                print("\n服务器已关闭连接")
                break

            buffer += data
            while True:
                try:
                    msg, buffer = try_unpack(buffer)
                except ProtocolError as e:
                    print(f"\n[协议错误] {e}")
                    self.running = False
                    return
                if msg is None: # 包没收全，等下一批
                    break
                if not msg: # 非法数据，跳过
                    continue
                self.on_message(msg)

    def on_message(self, msg: dict):
        mtype = msg.get("type")
        sender = msg.get("sender", "系统")
        text = msg.get("msg", "")
        suffix = "[图片]" if msg.get("msg_type") == "image" else ""

        if mtype == "system":
            print(f"\n[系统] {text}")
        elif mtype == "group":
            print(f"\n[群聊] {sender}: {text}{suffix}")
        elif mtype == "private":
            print(f"\n[私聊] {sender} -> 我: {text}{suffix}")
        elif mtype == "agent":
            print(f"\n[Agent] {text}")
            for i, step in enumerate(msg.get("steps") or [], 1):
                mark = "ok" if step.get("ok") else "!!"
                print(f"        [{mark}] {i}. {step.get('name')}({step.get('args')}) "
                      f"{step.get('ms')}ms -> {step.get('preview')}")
        elif mtype == "userlist":
            print(f"\n[在线] {len(msg.get('users', []))} 人：{', '.join(msg.get('users', []))}")
        elif mtype == "error":
            print(f"\n[错误] {msg.get('code')}: {text}")
        elif mtype == "autosummary":
            state = "开启" if msg.get("enabled") else "关闭"
            print(f"\n[定时总结] {state}（间隔 {msg.get('seconds', 0)} 秒）")
        elif mtype == "pong":
            rtt = self.note_pong(msg)
            suffix = f"，RTT {rtt}ms" if rtt is not None else ""
            print(f"\n[pong] 服务器存活{suffix}")
        else:
            print(f"\n[未知消息] {msg}")

    # ---------- 关闭 ---------
    def close(self):
        self.running = False
        self._hb_stop.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
            self.sock = None
        print("已断开连接")


# ============ 交互式命令 ============
HELP_TEXT = """
可用命令：
  /register 用户名 密码      注册新账号
  /login 用户名 密码         登录（必须先登录）
  @Agent 问题              向 Agent 提问，答案发回群里
  /agent 问题              向 Agent 提问（只回给我自己）
  /agent@group 问题        向 Agent 提问，并要求在群里公开回答
  /auto 5 | off | now      定时总结：每 5 分钟 / 关闭 / 立刻总结一次
  /pm 目标用户名 消息      私聊
  /quit                    退出
  其他内容                 直接作为群聊消息发送
"""


def main():
    make_console_safe()
    client = ChatClient()
    if not client.connect():
        print("无法连接服务器，退出")
        return

    # 启动接收线程（daemon，主线程退出即结束）
    t = threading.Thread(target=client.recv_loop, daemon=True)
    t.start()
    # 心跳线程：服务端靠它判断这条连接还活着，顺带测 RTT
    client.start_heartbeat()

    print(HELP_TEXT)
    try:
        while client.running:
            line = input().strip()
            if not line:
                continue

            # ---- 注册 ----
            if line.startswith("/register"):
                parts = line.split(maxsplit=2)
                if len(parts) < 3:
                    print("用法: /register 用户名 密码")
                    continue
                client.send({
                    "type": "register",
                    "user_id": parts[1].strip(),
                    "password": parts[2].strip(),
                })
                continue

            # ---- 登录 ----
            if line.startswith("/login"):
                parts = line.split(maxsplit=2)
                if len(parts) < 3:
                    print("用法: /login 用户名 密码")
                    continue
                client.username = parts[1].strip()
                client.send({
                    "type": "login",
                    "user_id": client.username,
                    "password": parts[2].strip(),
                })
                continue

            # ---- 退出 ----
            if line == "/quit":
                break

            # ---- 井字棋 ----
            if line.startswith("/game"):
                client.send({"type": "game", "text": line[len("/game"):].strip()})
                continue

            # ---- 定时任务 ----
            if line.startswith("/task"):
                client.send({"type": "task", "text": line[len("/task"):].strip()})
                continue

            # ---- 定时总结 ----
            if line.startswith("/auto"):
                parts = line.split(maxsplit=1)
                arg = parts[1].strip().lower() if len(parts) > 1 else ""
                if arg == "off":
                    client.send({"type": "autosummary", "action": "off"})
                elif arg == "now":
                    client.send({"type": "autosummary", "action": "now"})
                elif arg.isdigit():
                    client.send({"type": "autosummary", "action": "on", "minutes": int(arg)})
                else:
                    client.send({"type": "autosummary", "action": "status"})
                continue

            # ---- @Agent（默认在群里公开回答）----
            if line.lower().startswith("@agent"):
                if not client.username:
                    print("请先 /login 用户名 密码")
                    continue
                question = line[len("@agent"):].strip()
                if not question:
                    print("用法: @Agent 你的问题")
                    continue
                client.send({"type": "agent", "msg": question, "scope": "group"})
                continue

            # ---- Agent ----
            if line.startswith("/agent"):
                if not client.username:
                    print("请先 /login 用户名 密码")
                    continue
                scope = "private"
                rest = line[len("/agent"):].strip()
                if rest.startswith("@group"):
                    scope = "group"
                    rest = rest[len("@group"):].strip()
                if not rest:
                    print("用法: /agent 你的问题")
                    continue
                client.send({"type": "agent", "msg": rest, "scope": scope})
                continue

            # ---- 私聊 ----
            if line.startswith("/pm"):
                parts = line.split(maxsplit=2)
                if len(parts) < 3:
                    print("用法: /pm 目标用户名 消息")
                    continue
                client.send({
                    "type": "private",
                    "target": parts[1],
                    "msg": parts[2],
                })
                continue

            # ---- 默认：群聊 ----
            if not client.username:
                print("请先 /login 用户名 密码")
                continue
            client.send({"type": "group", "msg": line})

    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出…")
    finally:
        client.close()


if __name__ == "__main__":
    main()
