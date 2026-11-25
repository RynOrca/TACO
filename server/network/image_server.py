"""附件（图片 / 文档 / 压缩包）的 HTTP 通道：POST 上传，GET 取回；聊天消息里只传文件名。

为什么单独走 HTTP：聊天协议的帧长度是 uint16（单包上限 65535 字节），
一个文件塞不进一个包；与其把协议改成流式分片，不如让文件走它最合适的 HTTP，
聊天室只负责传一个带随机前缀的文件名。这也正好演示"服务端 HTTP API"。

命名规则：
  图片   <32 位十六进制>.jpg
  其它   <32 位十六进制>-<清洗后的原文件名>.pdf
随机前缀由服务端生成，客户端改不了路径；原文件名只用于显示。
"""

import json
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from server import config
from server.console import log_line

EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
MIME_BY_EXT = {v: k for k, v in EXT_BY_MIME.items()}
# 常见附件的 Content-Type，下载/预览时浏览器才知道怎么处理
MIME_BY_EXT.update({
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
})

# 落盘名统一是 <32hex><后缀>：URL 里永远只有 ASCII，中文原名放在消息 meta 里
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,8}$")
SAFE_NAME_RE = re.compile(r"[^\w一-龥.\- ()]")
IMAGE_EXTS = tuple(EXT_BY_MIME.values())


def is_attachment_name(name: str) -> bool:
    if not STORED_NAME_RE.match(name):
        return False
    suffix = Path(name).suffix.lower()
    return suffix in IMAGE_EXTS or suffix in config.FILE_EXT_ALLOWED


def sanitize_filename(raw: str) -> str:
    """只留安全字符，去掉路径分隔符和奇怪符号；保留中文，方便对方看懂。"""
    name = Path(unquote(raw or "")).name          # 去掉任何路径成分
    name = SAFE_NAME_RE.sub("_", name).strip(" .")
    return name[:120] or "file"


def display_name(stored: str) -> str:
    """没有 meta 时的兜底显示名（有 meta 时用 meta.name）。"""
    return stored


class FileHandler(BaseHTTPRequestHandler):
    server_version = "TacoFile/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args):
        log_line(f"[File] {self.address_string()} {fmt % args}")

    # ---------------------------------------------------------------- 工具
    def _cors(self) -> None:
        # 前端由桥（8765）托管，文件服务在另一个端口，所以要放行跨源
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
        if length > max(config.FILE_MAX_BYTES, config.IMAGE_MAX_BYTES):
            self._send_status(413, f"文件太大，上限 {config.FILE_MAX_BYTES // 1024 // 1024} MB")
            return

        mime = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        raw_name = self.headers.get("X-Filename") or ""
        data = self.rfile.read(length)
        if len(data) != length:
            self._send_status(400, "请求体不完整")
            return

        if raw_name:
            # 带原文件名：按后缀白名单判定，原名只用来显示
            name = sanitize_filename(raw_name)
            suffix = Path(name).suffix.lower()
            if suffix not in config.FILE_EXT_ALLOWED:
                self._send_status(
                    415, f"不支持的文件类型 {suffix or '(无后缀)'}，允许：{' '.join(config.FILE_EXT_ALLOWED)}")
                return
            stored = f"{uuid.uuid4().hex}{suffix}"
            kind = "image" if suffix in IMAGE_EXTS else "file"
        else:
            # 图片：按 Content-Type 判定
            ext = EXT_BY_MIME.get(mime)
            if ext is None:
                self._send_status(415, f"只支持 jpg/png/gif/webp，收到 {mime or '空'}")
                return
            name = f"截图{ext}"
            stored = f"{uuid.uuid4().hex}{ext}"
            kind = "image"

        config.IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (config.IMAGE_DIR / stored).write_bytes(data)
        log_line(f"[File] 收到{('图片' if kind == 'image' else '文件')} {stored}"
                 f"（{length} 字节，{mime or '未知类型'}）")
        self._send_json(200, {
            "file": stored,
            "name": name,
            "kind": kind,
            "bytes": length,
            "mime": mime,
            "url": f"/file/{stored}",
        })

    def do_GET(self) -> None:
        path = unquote(self.path.split("?", 1)[0])
        if path.startswith("/img/"):
            name = path[len("/img/"):]
        elif path.startswith("/file/"):
            name = path[len("/file/"):]
        else:
            self._send_status(404, f"未知路径 {path}")
            return

        if not is_attachment_name(name):
            self._send_status(403, "文件名不合法")
            return
        target = config.IMAGE_DIR / name
        if not target.is_file():
            self._send_status(404, "文件不存在")
            return

        data = target.read_bytes()
        suffix = Path(name).suffix.lower()
        ctype = MIME_BY_EXT.get(suffix) or "application/octet-stream"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=31536000")
        # 图片直接看，其它类型按原文件名下载
        if ctype.startswith("image/"):
            self.send_header("Content-Disposition", "inline")
        else:
            self.send_header("Content-Disposition",
                             f"attachment; filename*=UTF-8''{quote(name)}")
        self.end_headers()
        self.wfile.write(data)


def start_image_server(host: str = "0.0.0.0", port: Optional[int] = None) -> ThreadingHTTPServer:
    """在后台线程里起附件服务，返回 server 对象方便关闭。"""
    httpd = ThreadingHTTPServer((host, port or config.IMAGE_PORT), FileHandler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True, name="file-http").start()
    return httpd
