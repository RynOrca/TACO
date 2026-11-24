# Agent 定时总结：一个后台线程按固定间隔让 Agent 总结群聊，结果广播回 main

import threading


class AutoSummaryScheduler:
    """间隔可随时改（/auto 指令），0 表示关闭。

    - 线程常驻，用 Event.wait(interval) 代替 sleep，改间隔能立刻生效
    - 实际执行委托给 ChatService.run_scheduled_summary（那里才知道房间和 Agent）
    """

    def __init__(self, chat, default_seconds: int = 0):
        self.chat = chat
        self._interval = max(0, int(default_seconds))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="auto-summary")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ---------------------------------------------------------------- 控制
    def configure(self, seconds: int) -> None:
        self._interval = max(0, int(seconds))
        self._wake.set()          # 让循环重新算一次等待时间

    def status(self) -> dict:
        return {
            "enabled": self._interval > 0,
            "seconds": self._interval,
        }

    # ---------------------------------------------------------------- 循环
    def _loop(self) -> None:
        while not self._stop.is_set():
            interval = self._interval
            if interval <= 0:
                self._wake.wait(1.0)
                self._wake.clear()
                continue
            if self._wake.wait(interval):
                self._wake.clear()
                continue
            try:
                self.chat.run_scheduled_summary()
            except Exception as e:      # 单次失败不能把线程带走
                print(f"[AutoSummary] 本轮失败: {e}")
