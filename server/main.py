import threading

from server import config
from server.console import make_console_safe
from server.network.image_server import start_image_server
from server.network.keepalive import IdleReaper
from server.network.socket_server import SocketServer
from server.services.chat_service import ChatService
from server.services.context import Services
from server.services.router import build_default_router
from server.services.scheduler import TaskScheduler
from server.services.user_service import UserService
from server.storage.db import init_db


def main():
    make_console_safe()
    db_path = init_db()
    print(f"数据库就绪：{db_path}")

    users = UserService()
    chat = ChatService(users)
    services = Services(users=users, chat=chat)
    router = build_default_router(services)

    # 图片消息的 HTTP 通道（聊天协议只传文件名，图片本体走这里）
    image_server = start_image_server(config.HOST, config.IMAGE_PORT)
    print(f"附件服务启动成功，监听 {config.HOST}:{config.IMAGE_PORT}（图片 / 文件上传下载）")

    # 心跳与断线检测：客户端 ping，服务端按 last_seen 回收半开连接
    reaper = IdleReaper(users)
    reaper.start()
    print(f"心跳检测已启动：阈值 {config.IDLE_TIMEOUT}s，扫描间隔 {config.REAP_INTERVAL}s")

    # 定时任务：summary / reminder 统一调度，任务落库，重启后恢复
    chat.scheduler = TaskScheduler(chat, users, config.AGENT_AUTO_SUMMARY_SECONDS)
    chat.scheduler.start()
    if config.AGENT_AUTO_SUMMARY_SECONDS > 0:
        print(f"定时任务已启动：默认总结周期 {config.AGENT_AUTO_SUMMARY_SECONDS} 秒")
    else:
        print("定时任务已启动：/task 管理任务（/auto 仍兼容）")

    server = SocketServer(router, services)
    try:
        server.serve()
    except KeyboardInterrupt:
        print("收到 Ctrl+C，服务器关闭中…")
    finally:
        reaper.stop()
        chat.scheduler.stop()
        image_server.shutdown()
        server.stop()
        chat.shutdown()


if __name__ == "__main__":
    main()
