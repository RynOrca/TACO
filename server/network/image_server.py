"""图片消息的 HTTP 通道：POST 上传原图，GET 取回；聊天消息里只传文件名。

为什么单独走 HTTP：聊天协议的帧长度是 uint16（单包上限 65535 字节），
一张手机照片塞不进一个包；与其把协议改成流式分片，不如让图片走它最合适的 HTTP，
聊天室只负责传一个 32 位十六进制文件名。这也正好演示"服务端 HTTP API"。
"""

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

from server import config

EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MIME_BY_EXT = {v: k for k, v in EXT_BY_MIME.items()}
NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:jpg|jpeg|png|gif|webp)$")


class ImageHandler(BaseHTTPRequestHandler):
    server_version = "TacoImage/1.0"
    protocol_version = "HTTP/1.1"

    # 默认实现会把每条请求打到 stderr，这里统一走服务端日志格式
    def log_message(self, fmt: str, *args):
        print(f"[Image] {self.address_string()} {fmt % args}")

    # ---------------------------------------------------------------- 工具
    def _cors(self) -> None:
        # 前端由桥（8765）托管，图片服务在另一个端口，所以要放行跨源
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Filename")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_status(self, status: int, message: str) -> None:
        self._send_json(status, {"error": message})

    # ---------------------------------------------------------------- 路由
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path != "/upload":
            self._send_status(404, f"未知接口 {path}")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._send_status(411, "缺少 Content-Length")
            return
        if length > config.IMAGE_MAX_BYTES:
            self._send_status(413, f"图片太大，上限 {config.IMAGE_MAX_BYTES // 1024 // 1024} MB")
            return

        mime = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = EXT_BY_MIME.get(mime)
        if ext is None:
            self._send_status(415, f"只支持 jpg/png/gif/webp，收到 {mime or '空'}")
            return

        data = self.rfile.read(length)
        if len(data) != length:
            self._send_status(400, "请求体不完整")
            return

        name = f"{uuid.uuid4().hex}{ext}"
        config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (config.IMAGE_DIR / name).write_bytes(data)
        print(f"[Image] 收到图片 {name}（{length} 字节，{mime}）")
        self._send_json(200, {
            "file": name,
            "url": f"/img/{name}",
            "bytes": length,
            "mime": mime,
        })

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if not path.startswith("/img/"):
            self._send_status(404, f"未知路径 {path}")
            return
        name = path[len("/img/"):]
        if not NAME_RE.match(name):
            self._send_status(403, "文件名不合法")
            return
        target = config.IMAGE_DIR / name
        if not target.is_file():
            self._send_status(404, "图片不存在")
            return

        data = target.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", MIME_BY_EXT.get(Path(name).suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000")
        self.end_headers()
        self.wfile.write(data)


def start_image_server(host: str = "0.0.0.0", port: Optional[int] = None) -> ThreadingHTTPServer:
    """在后台线程里起图片服务，返回 server 对象方便关闭。"""
    httpd = ThreadingHTTPServer((host, port or config.IMAGE_PORT), ImageHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="image-http").start()
    return httpd
