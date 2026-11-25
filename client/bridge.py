"""TACO 客户端桥接层：原生 TCP <-> 本地 WebSocket，同时托管前端静态文件。

为什么需要这一层：浏览器不能直接开 TCP socket，而服务端只讲 TCP + TLV 协议。
于是这个进程做三件事：

  1. 每来一个前端页面，就替它建一条原生 TCP 连接（复用 protocol.pack_message / try_unpack，
     客户端这条链路上的粘包拆包一样要做）
  2. 用本地 WebSocket 把 TCP 收到的 JSON 推给页面，把页面发来的指令写回 TCP
  3. 静态托管 client/web/dist，所以生产模式只要一个进程、一个端口、一个窗口

一个页面一条 TCP 连接，是为了让"换号登录"和"开两个窗口互相测试"都跟命令行客户端一样干净。

    python -m client.bridge              # 起桥 + 打开应用窗口（服务端要先跑起来）
    python -m client.bridge --no-open    # 只起桥（开发时配合 client/web 的 npm run dev）
    python -m client.bridge --with-server  # 顺手把 server/main.py 也拉起来，单命令演示（Ctrl+C 一起停）
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

from client.socket_client import ChatClient
from server import config
from server.console import make_console_safe

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web" / "dist"
WS_PATH = "/ws"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

BUILD_HINT = (
    "前端还没有构建。在 client/web 目录执行：\n"
    "    npm install\n"
    "    npm run build\n"
    "开发模式则执行 npm run dev，再访问 http://127.0.0.1:5173"
)

OFFLINE_DETAIL = "与服务端的 TCP 连接已断开，点侧栏的连接状态可以重连"


class Link:
    """一个前端页面 <-> 服务端的一条独立 TCP 连接。"""

    def __init__(self, host: str, port: int, loop: asyncio.AbstractEventLoop):
        self.client = ChatClient(host=host, port=port)
        self.client.on_message = self._on_tcp_message
        self.loop = loop
        self.box: asyncio.Queue[str] | None = None
        self.state = "closed"
        self.detail = "尚未连接"
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 生命周期
    def attach(self, box: asyncio.Queue[str]) -> None:
        self.box = box
        self.publish_state()

    def detach(self) -> None:
        self.box = None
        self.client.close()

    def open(self) -> None:
        with self._lock:
            if self.state in ("open", "connecting"):
                return
            self.state = "connecting"
            self.detail = ""
        self.publish_state()
        threading.Thread(target=self._connect_and_pump, daemon=True, name="tcp-link").start()

    def reconnect(self) -> None:
        with self._lock:
            if self.state in ("open", "connecting"):
                return
        self.client.running = False
        self.open()

    def _connect_and_pump(self) -> None:
        if not self.client.connect(retries=1):
            with self._lock:
                self.state = "closed"
                self.detail = f"连不上 {self.client.host}:{self.client.port}，先启动 server/main.py"
            self.publish_state()
            return
        with self._lock:
            self.state = "open"
            self.detail = ""
        self.publish_state()
        # 心跳：桥替所有页面定时发 ping，服务端用它判断"这条连接还活着"
        self.client.start_heartbeat()
        try:
            self.client.recv_loop()
        finally:
            with self._lock:
                self.state = "closed"
                self.detail = OFFLINE_DETAIL
            self.publish_state()

    # ---------------------------------------------------------------- 收发
    def _on_tcp_message(self, msg: dict) -> None:
        if msg.get("type") == "pong":
            # RTT 只用于服务端/桥的日志与后续扩展，不塞给前端（前端消息类型里没有 metrics）
            rtt = self.client.note_pong(msg)
            if rtt is not None:
                print(f"[Link] {self.client.host}:{self.client.port} RTT {rtt}ms")
            return
        self.publish(msg)

    def send(self, msg: dict) -> None:
        if self.state != "open":
            self.publish_state()
            return
        self.client.send(msg)

    def publish_state(self) -> None:
        self.publish({"type": "link", "state": self.state, "detail": self.detail})

    def publish(self, payload: dict) -> None:
        box = self.box
        if box is None:
            return
        text = json.dumps(payload, ensure_ascii=False)
        try:
            self.loop.call_soon_threadsafe(box.put_nowait, text)
        except RuntimeError:
            pass  # 事件循环已经关了，进程正在退出


async def _pump(connection, box: asyncio.Queue[str]) -> None:
    while True:
        await connection.send(await box.get())


async def handle_ws(connection, args) -> None:
    box: asyncio.Queue[str] = asyncio.Queue()
    # 图片消息走服务端内置的 HTTP 服务，前端需要知道它的地址
    box.put_nowait(json.dumps(
        {"type": "hello", "image_base": f"http://{args.host}:{config.IMAGE_PORT}"},
        ensure_ascii=False,
    ))
    link = Link(args.host, args.port, asyncio.get_running_loop())
    link.attach(box)
    link.open()
    sender = asyncio.create_task(_pump(connection, box))
    try:
        async for raw in connection:
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                print(f"[Bridge] 丢弃非法前端消息: {raw!r:.120}")
                continue
            if not isinstance(msg, dict) or not isinstance(msg.get("type"), str):
                continue
            if msg["type"] == "reconnect":
                link.reconnect()
                continue
            link.send(msg)
    except ConnectionClosed:
        pass
    finally:
        sender.cancel()
        link.detach()


# -------------------------------------------------------------------- 静态文件
def _text_response(status: int, reason: str, message: str) -> Response:
    body = f"{message}\n".encode("utf-8")
    headers = Headers([
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return Response(status, reason, headers, body)


def _serve_static(request) -> Response:
    path = unquote(request.path.split("?", 1)[0])
    if not WEB_DIR.is_dir():
        return _text_response(503, "Service Unavailable", BUILD_HINT)

    target = (WEB_DIR / path.lstrip("/")).resolve()
    if path in ("", "/") or target.is_dir():
        target = WEB_DIR / "index.html"
    if WEB_DIR not in target.parents and target != WEB_DIR:
        return _text_response(403, "Forbidden", "路径越界")
    if not target.is_file():
        target = WEB_DIR / "index.html"  # 前端路由回退
        if not target.is_file():
            return _text_response(404, "Not Found", f"找不到 {path}")

    body = target.read_bytes()
    suffix = target.suffix.lower()
    ctype = (CONTENT_TYPES.get(suffix)
             or mimetypes.guess_type(target.name)[0]
             or "application/octet-stream")
    headers = Headers([
        ("Content-Type", ctype),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-cache" if suffix == ".html" else "public, max-age=31536000"),
    ])
    return Response(200, "OK", headers, body)


def process_request(connection, request) -> Response | None:
    if request.path.split("?", 1)[0] == WS_PATH:
        return None  # 走 WebSocket 握手
    return _serve_static(request)


# -------------------------------------------------------------------- 启动
def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def start_server(port: int) -> subprocess.Popen | None:
    """--with-server：在同一个控制台里把服务端拉起来，省掉一个终端。

    服务端已经在这个端口上监听时直接返回 None，不重复起一份。
    """
    if port_open(port):
        print(f"服务端已在 127.0.0.1:{port} 监听，直接复用")
        return None

    env = {**os.environ, "CHAT_PORT": str(port)}
    print(f"启动服务端：{sys.executable} -m server.main（CHAT_PORT={port}）")
    child = subprocess.Popen([sys.executable, "-m", "server.main"], cwd=PROJECT_ROOT, env=env)

    deadline = time.time() + 20
    while time.time() < deadline:
        if port_open(port):
            print(f"服务端就绪，监听 127.0.0.1:{port}")
            return child
        code = child.poll()
        if code is not None:
            raise SystemExit(f"服务端启动失败（退出码 {code}），看它上面打印的报错")
        time.sleep(0.3)
    child.terminate()
    raise SystemExit("服务端 20 秒内没有监听上端口，已中止")


def open_app_window(url: str) -> None:
    """有 Chromium 内核就用 --app 开一个无地址栏窗口，否则退回默认浏览器。"""
    candidates = [
        os.getenv("TACO_BROWSER", ""),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for exe in candidates:
        if exe and Path(exe).is_file():
            try:
                subprocess.Popen(
                    [exe, f"--app={url}", "--window-size=1240,820"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return
            except OSError:
                continue
    webbrowser.open(url)


async def amain(args) -> None:
    async with serve(
        lambda conn: handle_ws(conn, args),
        args.bind,
        args.ws_port,
        process_request=process_request,
        max_size=None,
    ):
        url = f"http://{args.bind}:{args.ws_port}/"
        print(f"TACO 客户端已就绪  {url}")
        print(f"  WebSocket  ws://{args.bind}:{args.ws_port}/ws  ->  TCP {args.host}:{args.port}")
        print(f"  静态目录   {WEB_DIR}")
        print(f"  图片服务   http://{args.host}:{config.IMAGE_PORT}/img/<文件名>")
        if args.open:
            open_app_window(url)
        await asyncio.Future()


def main() -> None:
    make_console_safe()
    parser = argparse.ArgumentParser(description="TACO 客户端桥：TCP <-> WebSocket")
    parser.add_argument("--host", default="127.0.0.1", help="服务端地址")
    parser.add_argument("--port", type=int, default=10086, help="服务端端口")
    parser.add_argument("--bind", default="127.0.0.1", help="桥监听地址")
    parser.add_argument("--ws-port", type=int, default=8765, help="桥监听端口")
    parser.add_argument("--no-open", dest="open", action="store_false",
                        help="不自动打开窗口（开发时配合 npm run dev）")
    parser.add_argument("--with-server", action="store_true",
                        help="同时启动 server/main.py（服务端没在跑时用；在这个终端按 Ctrl+C 会一起退出）")
    args = parser.parse_args()

    server = start_server(args.port) if args.with_server else None
    try:
        asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n客户端已退出")
    finally:
        if server is not None and server.poll() is None:
            print("关闭服务端…")
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    main()
