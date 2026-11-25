"""空闲连接回收：心跳的另一半。

客户端每 HEARTBEAT_SECONDS 发一次 ping，服务端在收包时刷新 last_seen；
这个线程每 REAP_INTERVAL 秒扫一遍，超过 IDLE_TIMEOUT 秒没有任何帧的连接
直接断开并从在线列表里移除。

它解决的是"半开连接"：进程被暂停、虚拟机挂起、拔网线、路由中断时，
双方内核都不会报错，recv 会一直阻塞——只有应用层心跳能发现。
"""

import threading

from server import config
from server.console import log_line


class IdleReaper:
    def __init__(self, users, timeout: int = None, interval: int = None):
        self.users = users
        self.timeout = timeout if timeout is not None else config.IDLE_TIMEOUT
        self.interval = interval if interval is not None else config.REAP_INTERVAL
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="idle-reaper")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                dead = self.users.reap(self.timeout)
            except Exception as e:          # 单次异常不能把线程带走
                log_line(f"[Heartbeat] 回收线程异常: {e}")
                continue
            if dead:
                self.users.push_userlist()
                log_line(f"[Heartbeat] 本轮回收 {len(dead)} 个连接：{', '.join(dead)}")
