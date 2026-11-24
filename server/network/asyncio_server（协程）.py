# 协程来实现TCP服务器

import asyncio
from typing import Dict
from network.protocol import TLVProtocol

# 在线客户端 {地址: StreamWriter}
CLIENT_POOL:Dict[str, asyncio.StreamWriter] = {}
# 消息队列
MSG_QUEUE = asyncio.Queue()

async def send_to_client(client_addr:str, msg_type:int, body:dict):
    """单点发送消息"""
    if client_addr in CLIENT_POOL:  # 确保在线
        writer = CLIENT_POOL[client_addr]
        try:
            pkg = TLVProtocol.encode(msg_type, body)
            writer.write(pkg)
            await writer.drain()
        except Exception as e:
            print(f"[Network] 消息发送给 {client_addr} 失败：{e}")

# exclude 表示需要排除的地址（555被孤立了）
async def broadcast(msg_type:int, body:dict, exclude:str=None):
    """广播群发"""
    pkg = TLVProtocol.encode(msg_type, body)
    # 使用list()拷贝，防止迭代时字典被修改
    for addr, writer in list(CLIENT_POOL.items()):
        if addr != exclude:
            try:
                writer.write(pkg)
                await writer.drain()
            except Exception:
                pass

# 处理单客户端
async def client_handle(reader: asyncio.StreamReader, writer:asyncio.StreamWriter):
    """单客户端连接总调度协程"""
    peername = writer.get_extra_info('peername')
    client_addr = f"{peername[0]}:{peername[1]}"
    CLIENT_POOL[client_addr] = writer
    print(f"新客户端接入：{client_addr}")
    # 接收缓存
    recv_buffer = b""

    try:
        while True:
            # 异步非阻塞读取数据，IO等待让出CPU，read()是协程对象
            recv_data = await reader.read(4096)
            if not recv_data:
                print(f"客户端 {client_addr} 断开连接")
                break

            recv_buffer += recv_data
            # 解析，提取出完整消息和接收缓存
            full_msgs, recv_buffer = TLVProtocol.decode(recv_buffer)

            # 放入消息队列中
            for msg in full_msgs:
                msg["client_addr"] = client_addr
                await MSG_QUEUE.put(msg)

    except ConnectionResetError:
        print(f"客户端 {client_addr} 异常断开（强制关闭）")
    except Exception as e:
        print(f"客户端 {client_addr} 连接异常：{e}")
    finally:
        # 连接断开，清理资源
        if client_addr in CLIENT_POOL:
            del CLIENT_POOL[client_addr]
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        print(f"客户端 {client_addr} 已断开")


async def client_logic_worker():
    """后台业务协程：专门消费队列"""
    print("[服务] 业务逻辑处理协程启动成功")
    while True:
        msg_info = await MSG_QUEUE.get()
        client_addr = msg_info["client_addr"]
        msg_type = msg_info["msg_type"]
        msg_body = msg_info["body"]

        # services/router.py的任务
        print(f"【业务处理】来自:{client_addr} | 类型:{msg_type} | 内容:{msg_body}")

        if msg_type == 1:
            resp_body = {"content": f"已收到消息：{msg_body.get('content', '')}"}
            await send_to_client(client_addr, msg_type, resp_body)

        MSG_QUEUE.task_done()


# 启动入口
async def start_server(host="0.0.0.0", port=8888):
    # 启动后台业务逻辑协程
    asyncio.create_task(client_logic_worker())

    # 启动 TLV-TCP 服务
    server = await asyncio.start_server(client_handle, host=host, port=port)
    print("========================================")
    print(f"🚀 智能聊天室 Network 层启动成功")
    print(f"监听端口：{port}")
    print("========================================")

    async with server:
        await server.serve_forever()