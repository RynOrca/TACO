import socket
import threading

from server import config
from server.console import log_line
from server.network.protocol import FrameTooLarge, ProtocolError, pack_message, try_unpack
from server.services.context import RequestContext, err
from server.storage import chat_history
from server.storage.db import close_db


def _enable_keepalive(sock: socket.socket) -> None:
    """TCP 保活兜底：应用层心跳之外，让内核也帮忙探测死连接。"""
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):          # Windows
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 10_000, 3_000))
        elif hasattr(socket, "TCP_KEEPIDLE"):              # Linux
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except OSError as exc:
        log_line(f"[TCP] 设置 keepalive 失败: {exc}")


class SocketServer:
    def __init__(self, router, services):
        self.router = router
        self.services = services
        self._stop = threading.Event()
        self._sock = None

    def serve(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((config.HOST, config.PORT))
        self._sock.listen(50)
        print(f"聊天室 TCP 服务器启动成功，监听 {config.HOST}:{config.PORT}")
        try:
            while not self._stop.is_set():
                try:
                    conn, addr = self._sock.accept()
                except Exception as e:
                    if not self._stop.is_set():
                        print(f"accept 出错: {e}")
                    break
                threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()
        finally:
            self._sock.close()
            self.services.chat.shutdown()
            close_db()

    def stop(self):
        self._stop.set()

    def _handle(self, conn: socket.socket, addr: tuple):
        # 每条连接先绑定一个默认房间，登录后可被 login 结果覆盖
        try:
            room_id = chat_history.ensure_room("main")
        except Exception as e:
            print(f"默认房间初始化失败： {e}")
            room_id = 0

        _enable_keepalive(conn)
        self.services.users.attach(conn)
        ctx = RequestContext(user_id="", conn=conn, room_id=room_id,
                             addr=addr, services=self.services)
        buf = b""
        try:
            while not self._stop.is_set():
                data = conn.recv(4096)
                if not data:
                    break
                self.services.users.touch(conn)      # 收到任何帧都算连接活着
                buf += data
                while True:
                    try:
                        msg, buf = try_unpack(buf)
                    except ProtocolError as e:
                        # 协议不匹配/长度异常：明确记录后关闭，不再当成"非法 JSON"静默丢弃
                        log_line(f"协议错误 {addr}: {e}")
                        return
                    if msg is None:          # 包没收全
                        break
                    if not msg:              # 非法数据
                        continue
                    reply = self.router.dispatch(ctx, msg)
                    if reply:
                        self._send_reply(conn, addr, reply)
        except OSError:
            # 对端断开、或心跳回收主动关掉了 socket：都是正常下线路径，不必刷错误
            pass
        except Exception as e:
            log_line(f"客户端 {addr} 异常: {e}")
        finally:
            self.services.users.logout(ctx.user_id, conn)
            self.services.users.detach(conn)
            try:
                conn.close()
            except OSError:
                pass
            log_line(f"客户端 {addr} 已断开")
            self.services.users.push_userlist()

    @staticmethod
    def _send_reply(conn: socket.socket, addr: tuple, reply: dict) -> None:
        """回包统一出口：超限时回错误帧，而不是让整个连接线程崩掉。"""
        try:
            conn.sendall(pack_message(reply))
        except FrameTooLarge as e:
            log_line(f"回包超限 {addr}: {e}")
            try:
                conn.sendall(pack_message(err("MSG_TOO_LONG", "回包超过单帧上限，已截断")))
            except Exception as inner:
                log_line(f"回包失败 {addr}: {inner}")
        except Exception as e:
            log_line(f"回包失败 {addr}: {e}")
