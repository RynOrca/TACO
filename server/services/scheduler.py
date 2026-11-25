"""通用定时任务调度器。

原来的 AutoSummaryScheduler 只会做一件事（定时总结），间隔存在内存里、重启就丢。
现在拆成「任务」模型，统一调度、落库、可增删启停：

  kind = summary   让 Agent 总结群聊（复用 ChatService.run_scheduled_summary）
  kind = reminder  到点广播一句提醒（不经过模型，零外部依赖）

两种时间形态：
  every:N  每 N 分钟一次（interval_seconds = N*60）
  in:N     N 分钟后只跑一次（interval_seconds = 0，跑完自动关闭）

调度线程每 TASK_TICK_SECONDS 秒扫一次到期任务；先把 next_run 推到下一次再执行，
避免"任务执行慢 → 下一轮又扫到同一条"的重复触发。
"""

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from server import config
from server.console import log_line
from server.storage import chat_history

SUMMARY = "summary"
REMINDER = "reminder"
KIND_CN = {SUMMARY: "总结", REMINDER: "提醒"}
ONE_SHOT_ARM_SECONDS = 60          # 一次性任务重新开启时，默认 1 分钟后跑


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _add_seconds(seconds: int) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def _fmt_local(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%m-%d %H:%M")
    except (TypeError, ValueError):
        return "-"


def _parse_minutes(text: str) -> int:
    try:
        minutes = int(str(text).strip())
    except (TypeError, ValueError):
        raise ValueError("时间必须是整数分钟")
    if not 1 <= minutes <= 1440:
        raise ValueError("分钟数必须在 1-1440 之间")
    return minutes


def parse_schedule(spec: str) -> Tuple[int, int]:
    """返回 (周期秒数, 一次性延迟秒数)，两者只会有一个非零。"""
    spec = (spec or "").strip().lower()
    if spec.startswith("every:"):
        return _parse_minutes(spec[len("every:"):]) * 60, 0
    if spec.startswith("in:"):
        return 0, _parse_minutes(spec[len("in:"):]) * 60
    if spec.isdigit():
        return _parse_minutes(spec) * 60, 0
    raise ValueError("时间格式：every:10（每 10 分钟）或 in:5（5 分钟后一次）")


class TaskScheduler:
    def __init__(self, chat, users, default_seconds: int = 0, tick: int = None):
        self.chat = chat
        self.users = users
        self.tick = tick if tick is not None else config.TASK_TICK_SECONDS
        self._default_seconds = max(0, int(default_seconds))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- 生命周期
    def start(self) -> None:
        if self._thread is not None:
            return
        self._bootstrap()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="task-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _bootstrap(self) -> None:
        """启动时处理两件事：迁移默认配置、处理"服务端停机期间错过的任务"。"""
        if self._default_seconds > 0 and not self._summary_tasks():
            self._create(SUMMARY, "", self._default_seconds * 60, "server", None)

        now = chat_history.now_iso()
        for task in chat_history.list_tasks():
            if not task["enabled"] or task["next_run"] > now:
                continue
            if task["interval_seconds"] > 0:
                # 周期任务：错过的周期全部跳过，顺延到下一个周期，避免一次补跑十条
                chat_history.update_task(
                    task["id"], next_run=_add_seconds(int(task["interval_seconds"])))
                log_line(f"[Task] #{task['id']} 停机期间错过周期，已顺延到下一次")
            else:
                # 一次性提醒：保留到期状态，启动后补跑一次
                log_line(f"[Task] #{task['id']} 停机期间已到期，启动后补跑一次")

    # ---------------------------------------------------------------- 兼容 /auto
    def configure(self, seconds: int) -> None:
        """兼容原来的 /auto 指令：seconds>0 设定总结周期，0 关闭。"""
        seconds = max(0, int(seconds))
        tasks = self._summary_tasks()
        if not tasks:
            if seconds > 0:
                self._create(SUMMARY, "", seconds, "server", None)
            return
        first, extra = tasks[0], tasks[1:]
        for task in extra:                      # 只保留一个总结任务，多余的清掉
            chat_history.delete_task(task["id"])
        if seconds <= 0:
            chat_history.update_task(first["id"], enabled=0)
        else:
            chat_history.update_task(first["id"], enabled=1, interval_seconds=seconds,
                                     next_run=_add_seconds(seconds))

    def status(self) -> dict:
        tasks = [t for t in self._summary_tasks() if t["enabled"]]
        if not tasks:
            return {"enabled": False, "seconds": 0}
        return {"enabled": True, "seconds": int(tasks[0]["interval_seconds"])}

    def _summary_tasks(self):
        return [t for t in chat_history.list_tasks() if t["kind"] == SUMMARY]

    # ---------------------------------------------------------------- 任务增删改
    def _create(self, kind: str, payload: str, interval_seconds: int,
                user: str, room_id) -> int:
        delay = interval_seconds
        return chat_history.create_task(
            kind=kind, payload=payload, interval_seconds=interval_seconds,
            next_run=_add_seconds(delay), created_by=user, room_id=room_id,
        )

    def add_from_text(self, rest: str, user: str, room_id) -> Tuple[bool, str]:
        """/task add 后面的部分：<summary|reminder> <every:10|in:5> [内容]"""
        parts = rest.split(maxsplit=2)
        if len(parts) < 2:
            return False, "用法：/task add summary every:10 或 /task add reminder in:5 开会"
        kind, schedule = parts[0].strip().lower(), parts[1]
        payload = parts[2].strip() if len(parts) > 2 else ""

        if kind not in (SUMMARY, REMINDER):
            return False, "类型只能是 summary（定时总结）或 reminder（定时提醒）"
        try:
            interval, delay = parse_schedule(schedule)
        except ValueError as e:
            return False, str(e)

        if kind == SUMMARY and delay > 0:
            return False, "定时总结只支持 every:<分钟>，一次性总结用 /auto now"
        if kind == REMINDER and not payload:
            return False, "定时提醒需要一句提醒内容，例如 /task add reminder in:5 开会"

        next_run = _add_seconds(delay or interval)
        task_id = chat_history.create_task(
            kind=kind, payload=payload, interval_seconds=interval,
            next_run=next_run, created_by=user, room_id=room_id,
        )
        task = chat_history.get_task(task_id)
        log_line(f"[Task] 用户 [{user}] 创建任务 #{task_id}：{self._describe(task)}")
        return True, f"已创建任务 #{task_id}：{self._describe(task)}"

    def set_enabled(self, task_id: int, enabled: bool) -> Tuple[bool, str]:
        task = chat_history.get_task(task_id)
        if task is None:
            return False, f"任务 #{task_id} 不存在"
        if enabled:
            interval = int(task["interval_seconds"])
            wait = interval if interval > 0 else ONE_SHOT_ARM_SECONDS
            chat_history.update_task(task_id, enabled=1, next_run=_add_seconds(wait))
            return True, f"任务 #{task_id} 已开启，下次 {_fmt_local(_add_seconds(wait))}"
        chat_history.update_task(task_id, enabled=0)
        return True, f"任务 #{task_id} 已暂停"

    def remove(self, task_id: int) -> Tuple[bool, str]:
        if not chat_history.delete_task(task_id):
            return False, f"任务 #{task_id} 不存在"
        return True, f"任务 #{task_id} 已删除"

    # ---------------------------------------------------------------- 查询
    @staticmethod
    def _describe(task: dict) -> str:
        kind = KIND_CN.get(task["kind"], task["kind"])
        interval = int(task["interval_seconds"])
        when = f"每 {max(1, interval // 60)} 分钟" if interval > 0 else "一次性"
        state = "开启" if task["enabled"] else "暂停"
        text = f"#{task['id']} [{kind}] {when} · 下次 {_fmt_local(task['next_run'])} · {state}"
        if task["payload"]:
            text += f" · {task['payload']}"
        return text

    def describe_all(self) -> str:
        tasks = chat_history.list_tasks()
        if not tasks:
            return ("当前没有定时任务。\n"
                    "用法：/task add summary every:10（每 10 分钟总结一次）\n"
                    "　　　/task add reminder in:5 开会（5 分钟后提醒一次）")
        lines = [f"定时任务共 {len(tasks)} 个："]
        lines += [self._describe(t) for t in tasks]
        lines.append("管理：/task del <编号>、/task on|off <编号>；/auto 仍然兼容")
        return "\n".join(lines)

    # ---------------------------------------------------------------- 调度循环
    def _loop(self) -> None:
        while not self._stop.wait(self.tick):
            try:
                due = chat_history.due_tasks(chat_history.now_iso())
            except Exception as e:
                log_line(f"[Task] 查询到期任务失败: {e}")
                continue
            for task in due:
                try:
                    self._run(task)
                except Exception as e:      # 单个任务失败不能带走调度线程
                    log_line(f"[Task] #{task['id']} 执行失败: {e}")

    def _run(self, task: dict) -> None:
        now = datetime.now(timezone.utc)
        interval = int(task["interval_seconds"])
        if interval > 0:
            chat_history.update_task(
                task["id"], next_run=_add_seconds(interval),
                last_run=_iso(now))
        else:
            chat_history.update_task(
                task["id"], enabled=0, last_run=_iso(now),
                next_run=_iso(now + timedelta(days=3650)))

        if task["kind"] == SUMMARY:
            log_line(f"[Task] #{task['id']} 触发定时总结")
            self.chat.submit_scheduled_summary(f"task#{task['id']}")
        elif task["kind"] == REMINDER:
            text = f"⏰ 定时提醒：{task['payload']}"
            self.users.broadcast({"type": "system", "msg": text})
            log_line(f"[Task] #{task['id']} 提醒已广播：{task['payload']}")
        else:
            log_line(f"[Task] #{task['id']} 未知任务类型：{task['kind']}")
