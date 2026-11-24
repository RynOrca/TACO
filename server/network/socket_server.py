import socket
import threading
from server import config
from server.storage.db import close_db
from server.network.protocol import pack_message, try_unpack
from server.services.context import RequestContext
from server.storage import chat_history

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

        ctx = RequestContext(user_id="", conn=conn, room_id=room_id,
                             addr=addr, services=self.services)
        buf = b""
        try:
            while not self._stop.is_set():
                data = conn.recv(1024)
                if not data:
                    break
                buf += data
                while True:
                    msg, buf = try_unpack(buf)
                    if msg is None:          # 包没收全
                        break
                    if not msg:              # 非法数据
                        continue
                    reply = self.router.dispatch(ctx, msg)
                    if reply:
                        try:
                            conn.sendall(pack_message(reply))
                        except Exception as e:
                            print(f"回包失败 {addr}: {e}")
                            break
        except Exception as e:
            print(f"客户端 {addr} 异常: {e}")
        finally:
            self.services.users.logout(ctx.user_id, conn)
            conn.close()
            print(f"客户端 {addr} 已断开")
            self.services.users.push_userlist()