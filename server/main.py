import threading

from server import config
from server.console import make_console_safe
from server.network.image_server import start_image_server
from server.network.socket_server import SocketServer
from server.services.chat_service import ChatService
from server.services.context import Services
from server.services.router import build_default_router
from server.services.scheduler import AutoSummaryScheduler
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
    print(f"图片服务启动成功，监听 {config.HOST}:{config.IMAGE_PORT}")

    # Agent 定时总结
    chat.scheduler = AutoSummaryScheduler(chat, config.AGENT_AUTO_SUMMARY_SECONDS)
    chat.scheduler.start()
    if config.AGENT_AUTO_SUMMARY_SECONDS > 0:
        print(f"Agent 定时总结已开启：每 {config.AGENT_AUTO_SUMMARY_SECONDS} 秒一次")
    else:
        print("Agent 定时总结默认关闭，客户端可用 /auto 5 开启（每 5 分钟一次）")

    server = SocketServer(router, services)
    try:
        server.serve()
    except KeyboardInterrupt:
        print("收到 Ctrl+C，服务器关闭中…")
    finally:
        chat.scheduler.stop()
        image_server.shutdown()
        server.stop()
        chat.shutdown()


if __name__ == "__main__":
    main()
