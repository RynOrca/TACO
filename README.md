# TACO

**TCP-Agent Chatroom Online** —— 基于原生 Socket 的多线程聊天室，内置一个会自己查聊天记录的 AI Agent。

课程设计项目：不依赖任何 Web 框架，从 TCP 粘包处理、消息路由、数据持久化一路写到 Agent 工具调用，动手搭建整个链路。

## 功能

| 功能 | 说明 |
| --- | --- |
| 注册 / 登录 | `/register 用户名 密码`、`/login 用户名 密码`，密码以 PBKDF2-SHA256 加盐存储；同名重连会踢掉旧连接 |
| 群聊 | 直接输入内容发送，服务端广播给所有在线用户 |
| 私聊 | `/pm 目标用户 消息`，两人固定映射到一个 `pm:a:b` 房间，双向一致 |
| AI Agent | 群里 `@Agent 问题` 直接公开回答，`/agent 问题` 只回给自己，`/agent@group 问题` 指定公开；键盘快捷入口见右栏「问 Agent」 |
| Agent 工具 | 读最近聊天记录、按关键词检索、保存总结/待办、**读取服务器当前时间**、Tavily 联网搜索；每次调用的名字/参数/耗时/结果预览随回复一起回传，界面上按「真实工具调用 N 次」逐条展开 |
| Agent 定时总结 | 到点自动让 Agent 总结群聊并广播；`/auto 5` 开启（每 5 分钟）、`/auto off` 关闭、`/auto now` 立刻跑一次，右栏也有一组按钮 |
| 表情 / 图片消息 | 表情是 Unicode 字符，跟着普通文本走；整条消息只有 1-3 个表情时放大显示。图片先压到最大边 1280，走服务端内置 HTTP 服务上传，聊天消息里只传一个 32 位十六进制文件名（也支持 Ctrl+V 粘贴截图） |
| 私聊隔离 | 私聊只存 `pm:a:b` 房间、只在两人之间单播；Agent 的工具被钉死在群聊房间，读不到任何私聊内容，私聊提问的回答也不落群聊历史 |
| 历史消息 | 全部落 SQLite，按房间+时间建索引；客户端首屏只拉**最近 20 条**，滚到顶部再按 `before_id` 向前翻页，每次 20 条 |
| 在线列表 | 用户上下线时向所有人推送 `userlist`，客户端实时渲染成员面板 |
| 图形界面 | Vite + React 前端（铅印风格三栏），经 Python 桥接层走原生 TCP；支持登录/注册、群聊、私聊、成员、待办、Agent 卡片、向上翻页加载更早消息 |

## 房间模型：到底有几个"聊天室"

课设说的「多人聊天室」是**一个聊天室**，不是一个 IM 里那种可以随便新建、可加入退出的"群列表"。TACO 按这个理解实现：

- **只有一个群聊房间 `main`**：所有人登录后都在里面，发一条消息服务端广播给所有在线用户。没有建群、拉人、退群。
- **私聊不是"另一个聊天室"**，而是消息的一条投递路径：`/pm 目标 消息` 时服务端把两人映射成一个固定名字的 `pm:a:b` 房间（名字按字典序排，双方一致），消息只单播给这两个人。客户端把它显示成一个会话，但对你来说它就是"和某人的私聊"，不需要加入、不能邀请第三人。
- 因此「多个在线用户 + 一个群聊广播 + 一对一的私聊」是同一套连接、同一套协议、同一个聊天室里并存的两种可见范围，这也正是课设验收里「三个客户端同时在线、私聊与群聊」的意思。

服务端内部仍然用 `rooms` 表区分房间（`room_type` = `group` / `private`），因为历史消息、待办都要按房间落库；但这是**存储和权限边界**，不是用户可以自由切换的"多聊天室"功能。

```
                    ┌──────────── main（群聊，广播给所有人） ────────────┐
alice ──socket──►   │                                                    │
bob   ──socket──►   │   pm:alice:bob（私聊，只单播给这两个人）           │
carol ──socket──►   │                                                    │
                    └────────────────────────────────────────────────────┘
Agent 只被授权读 main，pm:* 房间对它不可读（见「Agent 与工具层」）
```

## 项目架构

服务端将项目功能解耦分层，共分为：网络接入层、业务逻辑层、Agent 与工具层、数据存储层。客户端负责实现与服务端的通信以及 UI。

```
├── server/                  # 【服务端】
│   ├── main.py              # 启动入口：初始化数据库、启动 Socket 监听
│   ├── config.py            # 配置：读取 .env，端口 / 数据库、图片目录 / LLM 与 Tavily 的 Key
│   ├── console.py           # 让 Windows GBK 控制台遇到 emoji 时不再抛异常
│   ├── models.py            # 数据模型（User / Message / TodoItem 数据类）
│   │
│   ├── network/             # 【网络接入层】
│   │   ├── socket_server.py # 管理客户端连接、多线程调度、单播/广播
│   │   ├── protocol.py      # 核心！处理 TCP 粘包/拆包（Header + JSON Body）
│   │   ├── image_server.py  # 图片消息的 HTTP 通道：POST /upload 存盘、GET /img/<文件名> 取回
│   │   └── asyncio_server（协程）.py   # 早期协程版实现，已弃用，仅作对照保留
│   │
│   ├── services/            # 【业务逻辑层】
│   │   ├── router.py        # 消息分发路由：解析业务指令，调用对应 service
│   │   ├── user_service.py  # 登录、在线用户管理、单播/广播
│   │   ├── chat_service.py  # 群聊、私聊（含图片）、Agent 调用编排、定时总结执行
│   │   ├── scheduler.py     # AutoSummaryScheduler：间隔可改的后台定时线程
│   │   └── context.py       # 请求上下文 RequestContext + 服务容器 Services（避免循环 import）
│   │
│   ├── agent/               # 【Agent 与工具层】
│   │   ├── agent_core.py    # 构造 Prompt、调用大模型、ReAct 循环、执行工具、收集调用记录
│   │   └── tools.py         # 真实工具函数（含系统时间工具、群聊授权护栏）+ Function Calling 声明
│   │
│   └── storage/             # 【数据存储层】
│       ├── db.py            # 连接管理（WAL + 每线程一个连接 + busy_timeout）、建表语句
│       └── chat_history.py  # 聊天记录、待办、用户、房间的 CRUD（DAO）
│
├── client/                  # 【客户端】
│   ├── bridge.py            # 桥接层：一个页面一条原生 TCP 连接 ↔ 本地 WebSocket，并托管前端静态文件
│   ├── socket_client.py     # TCP 收发（独立线程）+ 命令行交互，被 bridge.py 复用
│   ├── web/                 # 前端工程（Vite + React + TS，构建产物由 bridge.py 托管）
│   │   ├── index.html
│   │   ├── vite.config.ts   # dev 模式把 /ws 代理到本地桥
│   │   ├── package.json
│   │   └── src/
│   │       ├── main.tsx     # 入口
│   │       ├── App.tsx      # 三栏布局与弹层编排
│   │       ├── bridge-client.ts  # WebSocket 客户端（断线重连）
│   │       ├── store.ts     # 消息 reducer：会话分线程、历史分页合并、去重
│   │       ├── rows.ts      # 把消息流切成「日期分隔 / 系统提示 / 消息组」
│   │       ├── rich.tsx     # Agent 回复的轻量 markdown 渲染
│   │       ├── emoji.ts     # 表情表 + "整条只有表情就放大"的判断
│   │       ├── upload.ts    # 图片压缩 + POST /upload
│   │       ├── use-chat.ts  # 状态 + 桥接 + 发送指令的粘合层
│   │       ├── time.ts      # 时间/日期格式化
│   │       ├── styles.css   # 铅印风格样式
│   │       └── components/  # Sidebar / Transcript / Message / Composer / EmojiPicker / SidePanel / AuthGate
│   └── ui/
│       └── mockup-b1-ink.html  # 定稿风格的静态原型（单文件 HTML，浏览器直接打开）
│
├── database/
│   └── chat.db              # SQLite 数据库文件（自动生成，无需手动创建）
│
├── docs/                    # 学习笔记与模块讲解
│   ├── chat_history讲解.md
│   └── ...
│
├── .env.example             # 环境变量模板 → 复制为 .env 后填写
├── requirements.txt
└── README.md
```

### 客户端为什么多一个 bridge.py

浏览器不能直接开 TCP socket（Web 沙箱里只有 HTTP/WebSocket），而服务端只讲「TLV + JSON over TCP」。所以客户端被拆成两半，各自只做自己擅长的事：

```
React 前端 (client/web)          Python 桥 (client/bridge.py)            服务端 (server)
──────────────────────           ────────────────────────────            ──────────────────
DOM 渲染 / 布局 / 滚动           原生 socket + pack_message/try_unpack     TCP + TLV
状态 reducer / 历史分页    ⇄     WS 收发的 JSON 原样透传            ⇄      router → service
                                                                         SQLite / Agent
```

- **一个页面一条 TCP 连接**：`bridge.py` 给每个 WebSocket 连接配一条独立的 `ChatClient`，所以「开两个窗口互相发消息」「切换账号」都跟命令行客户端一样干净，不会出现同一个 socket 上两个身份
- **粘包处理没有被绕开**：桥复用的是 `server/network/protocol.py` 里的 `pack_message()` / `try_unpack()`，客户端这条链路上的缓冲区累积、半包等待、一次 `recv` 多包循环解，和服务端是同一份实现
- **静态托管**：桥在同一个端口上先按路径分发——`/ws` 走 WebSocket 握手，其余当作 `client/web/dist` 里的静态文件，所以生产模式只有一个进程、一个端口、一个窗口

桥自己只懂两条额外指令：`{"type":"reconnect"}`（让桥重新连服务端），以及它主动推送的 `{"type":"link","state":"open|connecting|closed","detail":"…"}`（前端据此显示连接状态）。其余消息体与 TCP 上的完全一致，见[通信协议](#通信协议)。

## 自定义功能（课设第 5 条要求的"至少两个"）

| 功能 | 实现位置 | 说明 |
| --- | --- | --- |
| 聊天记录持久化与检索 | `storage/chat_history.py`、`services/chat_service.py#handle_history` | 全部落 SQLite，按房间+时间建索引；首屏 20 条，滚到顶部按 `before_id` 翻页；Agent 的 `search_chat_history` 也走同一套 DAO |
| 表情与图片消息 | `web/src/emoji.ts`、`web/src/upload.ts`、`network/image_server.py` | 表情是纯文本；图片走 HTTP 上传 + 文件名入消息，支持粘贴截图 |
| Agent 定时总结 | `services/scheduler.py`、`chat_service.py#run_scheduled_summary` | 后台线程按间隔让 Agent 总结群聊并广播，有新消息才总结，间隔可随时改 |
| Agent 真实工具调用记录 | `agent/agent_core.py#execute_tool` | 每次工具调用的名字/参数/耗时/结果预览随回复发到界面，答辩可直接对着讲 |

## 与课设要求的对应关系

| 要求 | 落地情况 | 看哪里 |
| --- | --- | --- |
| 1. TCP 连接、多客户端同时在线、消息收发、断线处理、粘包拆分 | 每条连接一个线程；`TLV` 帧（类型 + 长度 + JSON），缓冲区累积处理半包、一次 `recv` 多包循环解；断开时从在线表摘掉并广播新的 `userlist` | `network/socket_server.py`、`network/protocol.py` |
| 2. 注册登录、在线列表、一对一私聊、多人群聊广播、消息展示、可操作界面 | 全部具备；密码 PBKDF2-SHA256 加盐；Vite + React 三栏界面 | `services/user_service.py`、`client/web/` |
| 3. 接入 Agent 作为虚拟成员，`@Agent` / 指令触发，问答 + 群聊总结 + 待办提取，结果发回聊天室 | `@Agent 问题`（群里公开）、`/agent`（只回我）、右栏快捷按钮；总结/待办走 `save_history_and_todo` 落库 | `services/chat_service.py#handle_agent`、`agent/` |
| 4. 至少一种真实工具调用，服务端函数或 HTTP API 实际执行，展示调用记录 | 5 个工具全部真实执行（SQLite 查询、`datetime.now()`、Tavily HTTP）；`steps` 记录名称/参数/耗时/结果预览，界面逐条展开 | `agent/agent_core.py#execute_tool`、`components/Message.tsx` |
| 5. 自定义两个以上功能 | 聊天记录持久化与检索、表情与图片消息、Agent 定时总结（外加真实工具调用记录展示） | 见上面「自定义功能」 |
| 6. 模型不可用时基本通信仍正常 | Key 留空/接口挂了只影响 Agent：登录、群聊、私聊、历史、图片全部照常；Agent 回一句「暂不可用」 | `agent_core.get_client()` 抛 `AgentUnavailable` → 转成普通回复 |
| 验收：三个客户端同时在线、私聊与群聊、异常断线 | 桥给每个页面一条独立 TCP 连接，开三个窗口就是三个客户端；关掉一个窗口，别人面板里的成员立刻消失 | `client/bridge.py`、`server` 的 `userlist` 推送 |
| 验收：群里 `@Agent` 走完「读授权记录 → 摘要/待办 → 回复群聊」并展示调用记录 | `@Agent 总结一下最近的讨论`：`read_recent_chat_history` → `save_history_and_todo` 两步都会显示在卡片里 | 同上 |

## 快速开始

### 1. 环境要求

- Python 3.12（开发环境）
- Node.js 20+（只在构建/开发前端时需要，跑起来之后的客户端不再依赖 Node）
- 能访问所填 LLM 服务商的网络（Agent 功能需要）

### 2. 安装依赖

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
```

然后在 `.env` 里至少填 `LLM_API_KEY` 和 `LLM_MODEL_ID`。完整字段见下方[环境变量](#环境变量)。

> `.env` 含密钥，不要提交到版本库。

### 4. 初始化数据库

不需要手动建表，首次调用 `init_db()` 会自动建库建表（`database/chat.db` 也会自动创建）。

想先验证存储层是否正常，可以直接跑 `chat_history.py` 里的自测：

```bash
python -m server.storage.chat_history
```

> 必须用 `-m` 模块方式、在项目根目录执行。直接 `python server/storage/chat_history.py` 会因为 `sys.path` 不含项目根而报 `ModuleNotFoundError: No module named 'server'`。

### 5. 启动服务端

```bash
python -m server.main
```

正常输出：

```
数据库就绪：<项目根>\database\chat.db
图片服务启动成功，监听 0.0.0.0:10087
Agent 定时总结默认关闭，客户端可用 /auto 5 开启（每 5 分钟一次）
聊天室 TCP 服务器启动成功，监听 0.0.0.0:10086
```

两个端口的分工：`10086` 是 TCP 聊天协议（自研 TLV 帧），`10087` 只干图片上传/下载两件事。

### 6. 构建前端（只需一次）

```bash
cd client/web
npm install
npm run build
```

### 7. 启动客户端

```bash
python -m client.bridge
```

这会起一个本地桥（默认 `http://127.0.0.1:8765/`），自动连服务端，并用 Edge/Chrome 的 `--app` 无地址栏窗口打开界面。打开后是登录窗口：填用户名和密码，先点「注册」建号，再点「登录」。界面里点左侧会话切群聊/私聊，底部输入框发消息，顶部「总结本群」让 Agent 公开总结，「搜索历史」按关键词检索。

常用参数：

```bash
python -m client.bridge --no-open          # 只起桥，不开窗口
python -m client.bridge --with-server      # 服务端还没起时，顺手把 server/main.py 也拉起来
python -m client.bridge --port 10086       # 指定服务端端口
python -m client.bridge --ws-port 8765     # 指定桥的端口
```

> 客户端是纯 TCP 客户端：服务端没在监听 `10086` 时，界面上会显示「已断开 · 点此重连」，登录窗口里也会提示连不上。要么先开一个终端跑 `python -m server.main`，要么给桥加 `--with-server` 由它代劳（会在同一个控制台里拉起服务端并等端口就绪；按 Ctrl+C 两个一起停）。

前端改动时要热更新，就开两个终端：

```bash
python -m client.bridge --no-open          # 终端 1：桥
cd client/web && npm run dev               # 终端 2：Vite dev server（5173，/ws 自动代理到 8765）
```

然后访问 <http://127.0.0.1:5173/>。

命令行版本（调试用）：

```bash
python -m client.socket_client
```

> 两个客户端都要用 `-m` 方式启动：它们复用了 `server/network/protocol.py` 里的收发包函数，需要项目根在 `sys.path` 上。

可用命令（图形界面和命令行都认，界面上也有对应的按钮/面板）：

| 输入 | 作用 |
| --- | --- |
| `@Agent 问题` | 在群里公开提问，答案发回群聊（图形界面里就是这么用的） |
| `/agent 问题` | 向 Agent 提问，只回给自己 |
| `/agent@group 问题` | 指定在群里公开回答 |
| `/auto 5` / `/auto off` / `/auto now` | 定时总结：每 5 分钟 / 关闭 / 立刻总结一次（`/auto` 不带参数＝查状态） |
| `/pm 目标用户 消息` | 私聊 |
| `/register`、`/login`、`/quit` | 注册 / 登录 / 退出 |
| 其他内容 | 直接作为群聊消息发送（图形界面点「图片」或 Ctrl+V 粘贴截图发图片） |

## 环境变量

全部配置集中在 `server/config.py`，通过 `python-dotenv` 加载。加载顺序：`<项目根>/.env` → `server/.env`，命中第一个就停止。

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `CHAT_HOST` | 否 | `0.0.0.0` | 服务端监听地址。`0.0.0.0` 允许局域网内其他机器连接，只想本机测试填 `127.0.0.1` |
| `CHAT_PORT` | 否 | `10086` | 监听端口。客户端 `socket_client.py` 顶部的 `PORT` 不读 `.env`，改端口要两边一起改 |
| `CHAT_DB_PATH` | 否 | `<项目根>/database/chat.db` | SQLite 文件路径。**不要写成空值**：空字符串会让 sqlite 打开临时库，每个线程一个、重启即丢 |
| `CHAT_IMAGE_PORT` | 否 | `10087` | 图片消息用的 HTTP 服务端口（见下面「图片消息为什么要多一个 HTTP 服务」） |
| `CHAT_IMAGE_DIR` | 否 | `<数据库目录>/images` | 图片落盘目录 |
| `CHAT_IMAGE_MAX_BYTES` | 否 | `8388608` | 单张图片字节上限，超出直接 413 |
| `AGENT_AUTO_SUMMARY_SECONDS` | 否 | `0` | 服务端启动时的定时总结间隔（秒）。`0` = 关闭，客户端可用 `/auto 5` 临时开启 |
| `AGENT_AUTO_SUMMARY_MIN_MESSAGES` | 否 | `3` | 自动总结的门槛：至少积累这么多条**人发的新消息**才总结；手动触发不受限制 |
| `LLM_API_KEY` | 否 | 空 | OpenAI 兼容接口的 Key。**留空也能启动**：聊天室收发完全正常，Agent 回复一句「暂不可用」（课设要求「模型不可用时聊天室基本通信仍正常」） |
| `LLM_BASE_URL` | 否 | OpenAI 官方 | 第三方兼容接口填完整地址（一般带 `/v1`）。用官方接口请把整行**注释掉**，写成空值会导致每次请求 `APIConnectionError` |
| `LLM_MODEL_ID` | 否 | 空 | 模型 ID，必须与服务商名称一致，如 `gpt-4o-mini` / `deepseek-chat` / `qwen-plus`。与 Key 一起缺失时只影响 Agent |
| `TAVILY_API_KEY` | 否 | 空 | 仅 `tavily_search` 工具使用。为空时 Agent 仍可运行，联网搜索会返回工具错误 |
| `AGENT_MAX_STEPS` | 否 | `5` | ReAct 最大循环步数（模型最多几轮「调工具 → 看结果」） |
| `AGENT_TIMEOUT` | 否 | `60` | 仅用于失败提示文案，当前**没有**真正中断模型调用 |
| `MAX_HISTORY` | 否 | `20` | 预留给单次读取历史条数上限，当前**未被任何代码使用** |

`_int()` 会把空值或非法整数（如 `CHAT_PORT=abc`）回退成默认值并打印一行提示，不会让服务起不来。

## 通信协议

### 帧格式（TLV）

```
+--------+--------+-----------------+
| type   | length | body (JSON)     |
| uint16 | uint16 | length 字节      |
|  2B    |  2B    |      N B        |
+--------+--------+-----------------+
```

- `type` / `length` 用 `struct.pack("!HH")`，大端序
- `body` 是 `json.dumps(body, ensure_ascii=False).encode("utf-8")`
- 因为 `length` 是 uint16，单个 body 上限 65535 字节
- 收发统一走 `server/network/protocol.py` 的 `pack_message()` / `try_unpack()`，服务端和客户端共用同一份实现；`try_unpack()` 返回 `(消息字典, 剩余数据)`，`None` 表示半包（等下一批 `recv`），`{}` 表示非法数据（丢弃）
- header 里的 `type` 是数字编码（`TYPE_CODE` 表），body 里也带一份字符串型的 `type` 供路由层使用；解包时若 body 缺 `type`，用 header 的编码补上
- 接收端用缓冲区累积：不足一个完整包就等下一批 `recv`，一次 `recv` 里有多包就循环解完 —— 这就是粘包/拆包的处理点

### 消息体（body）约定

请求统一带 `type` 字段作为路由键；`{"sys": true, ...}` 是心跳/系统消息，路由层直接丢弃不处理。

| type | 方向 | 字段 | 处理函数 |
| --- | --- | --- | --- |
| `register` | C→S | `user_id`, `password`, (`nickname`) | `UserService.handle_register` |
| `login` | C→S | `user_id`, `password` | `UserService.handle_login` |
| `group` | C→S | `msg`；图片消息改填 `image`（文件名） | `ChatService.handle_group` |
| `private` | C→S | `target`, `msg`；图片消息改填 `image` | `ChatService.handle_private` |
| `agent` | C→S | `msg`, `scope`(`private`/`group`) | `ChatService.handle_agent` |
| `todos` | C→S | — | `ChatService.handle_todos` |
| `autosummary` | C→S | `action`(`status`/`on`/`off`/`now`), `minutes` | `ChatService.handle_auto_summary` |
| `history` | C→S | 可选 `target`、`limit`、`before_id` | `ChatService.handle_history`。不填 `target` 读当前群聊，填了读「我」与该用户的私聊房间（房间名由服务端按 `pm:me:target` 算，客户端无法指定 room_id）；带 `before_id` 时取更早的一页 |
| `ping` | C→S | — | 回 `pong` |
| `system` | S→C | `msg` | 回执/系统提示 |
| `group` / `private` | S→C | `sender`, `msg`, (`id`, `target`), (`msg_type`, `image`) | 广播/单播。`private` 会同时回显给发送方（带 `target`），这样自己的私聊会话里也能看到刚发出去的那条。图片消息带 `msg_type="image"` 和文件名 `image` |
| `agent` | S→C | `sender`, `msg`, `status`(`pending`/`done`), `scope`, `steps`, (`scheduled`) | Agent 先推「正在思考」，再推结果。`steps` 是本轮真实工具调用记录（`name`/`args`/`ok`/`ms`/`preview`），`scheduled=true` 表示定时总结 |
| `autosummary` | S→C | `enabled`, `seconds` | 定时总结状态变化时广播给所有人 |
| `userlist` | S→C | `users` | 在线用户列表 |
| `todos` | S→C | `items` | 当前房间待办（`id/assignee/content/status/created_at/done_at`） |
| `history` | S→C | `items`, `target`, `before_id`, `more` | 历史消息（`id/sender/content/msg_type/created_at`），按时间正序；`more=false` 表示没有更早的了 |
| `error` | S→C | `code`, `msg` | 错误码：`NOT_LOGIN` `BAD_FORMAT` `BAD_TYPE` `UNKNOWN_TYPE` `INTERNAL` `BAD_LOGIN` `LOGIN_FAILED` `EMPTY_MSG` `MSG_TOO_LONG` `SAVE_FAILED` `BAD_PARAM` `SELF_PM` `USER_OFFLINE` `BAD_REGISTER` `USER_EXISTS` `NOT_REGISTERED` `BAD_PASSWORD` |

消息处理流程：

```
客户端发送消息
    ↓
network/socket_server.py 收包、拆包
    ↓
services/router.py 按 type 路由到对应 handler（未知 type → UNKNOWN_TYPE）
    ↓
chat_service 组装 Message 对象 → 交给 storage/chat_history.py（DAO）
    ↓
storage/chat_history.py 读写 SQLite
    ↓
（同时）chat_service 通过 user_service 广播/单播给在线客户端
```

路由层对 handler 抛出的异常统一兜底成 `INTERNAL`，不把堆栈细节暴露给客户端。

## 数据库设计

SQLite，WAL 模式 + 每线程一个连接（`threading.local`）+ `busy_timeout=5000`，写操作统一走 `transaction()` 上下文管理器自动 commit/rollback。

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `rooms` | `room_id`(PK), `name`(UNIQUE), `room_type`, `owner_id`, `created_at` | 群聊用 `main`，私聊用 `pm:用户A:用户B`（字典序保证双向一致） |
| `users` | `user_id`(PK), `nickname`, `password_hash`, `status`, `last_login` | `password_hash` 存 `pbkdf2_sha256$轮数$盐$哈希`，注册时写入、登录时用 `hmac.compare_digest` 校验 |
| `room_members` | (`room_id`, `user_id`)(PK), `joined_at` | 成员关系，外键级联删除 |
| `messages` | `id`(PK), `room_id`, `sender`, `content`, `msg_type`, `created_at` | `msg_type`：`group` / `private` / `image` / `agent` / `summary`；`image` 行的 `content` 就是图片文件名（文件本体在 `database/images/`，不进库）；索引 `(room_id, created_at)`、`(sender)` |
| `todos` | `id`(PK), `room_id`, `assignee`, `content`, `status`, `created_at`, `done_at` | `status`：`pending` / `done`；索引 `(room_id, status)` |

DAO 层的几个约定：

- 所有 SQL 参数用 `?` 占位，防注入
- `LIKE` 检索前转义 `%` `_` `\`，防止用户输入被当成通配符
- 读条数统一经 `_clamp()` 限制在 1~100，防止 Agent 一次读上万条拖死服务
- `row_to_message()` 负责 `sqlite3.Row` → `models.Message` 的转换

详细逐行讲解见 [`docs/chat_history讲解.md`](docs/chat_history讲解.md)。

## Agent 与工具层

采用 **Function Calling 版 ReAct 范式**：模型自己决定调哪个工具，`agent_core.run()` 循环「请求模型 → 执行工具 → 把结果塞回 messages」，直到模型不再要求调用工具或达到 `AGENT_MAX_STEPS`。

| 工具 | 作用 | 参数 | 依赖 |
| --- | --- | --- | --- |
| `read_recent_chat_history` | 读当前房间最近消息，按时间正序返回 | `limit` | SQLite |
| `search_chat_history` | 关键词 OR 检索历史消息 | `keywords`, `limit` | SQLite |
| `save_history_and_todo` | 把总结/待办写库（`kind`=`summary`/`todo`） | `content`, `kind` | SQLite |
| `get_current_time` | 读**服务器所在机器的真实系统时间**：日期、星期、时区、Unix 时间戳 | — | 无（`datetime.now()`） |
| `tavily_search` | 联网搜索实时信息 | `query`, `max_results`, `max_content_length` | `TAVILY_API_KEY` |

每次工具调用都会生成一条记录 `{name, args, ok, ms, preview}`，跟着回复的 `steps` 字段发到客户端，卡片里显示成「真实工具调用 N 次」+ 逐条展开，命令行客户端也会打成缩进日志。记录的是**真实执行**（`execute_tool` 里 `time.perf_counter()` 计时、异常也如实标 `ok=false`），不是预设文案。

安全设计（重点，课设要求 Agent 只能碰"授权范围内"的内容）：

1. **`room_id` 不出现在工具 schema 里**。`build_room_tools()` 用闭包把服务端算好的 `room_id` 绑进工具实现，模型看不到也填不了，从根上杜绝「让它去读别人房间」。
2. **Agent 永远只绑群聊房间**。`handle_agent` 无论用户在群聊还是私聊里提问，传给 Agent 的都是 `chat_service.group_room_id()`（`main`），不是 `ctx.room_id`。
3. **工具层再加一道护栏**。`_require_group_room()` 在每次读/写前查 `rooms.room_type`，私聊房间直接返回 `[ToolError] 当前会话是私聊房间，不在 Agent 的授权范围内`，模型只能如实告诉用户看不到。
4. **私聊问答不落群聊历史**。`scope=private` 的回复只单播给提问者，不会写进 `main` 的历史表，否则以后群里的总结会把两个人的私聊问答翻出来。
5. **工具返回内容是数据，不是指令**。system prompt 明确要求模型不执行工具结果里出现的命令式文字，防提示词注入。

其它防护：单次工具结果截断到 4000 字符；工具参数类型错误时把错误信息回给模型让它自我纠正；Agent 调用放在独立线程池（4 worker），不阻塞连接线程；模型没配 Key 时 `AgentUnavailable` 被转成一条普通回复，聊天室照常收发。

### 图片消息为什么要多一个 HTTP 服务

聊天协议的帧长度是 `uint16`（单包上限 65535 字节），一张手机照片塞不进一个包。有两条路：把协议改成流式分片，或者让图片走它最合适的 HTTP、聊天消息里只传文件名。这里选了后者：

```
浏览器 ──压缩到最大边 1280──► POST http://<服务端>:10087/upload  ──► database/images/<32位hex>.jpg
        └── TCP: {"type":"group","msg":"[图片]","image":"<32位hex>.jpg"} ──► 广播给所有人
接收端 <img src="http://<服务端>:10087/img/<32位hex>.jpg">
```

- 文件名由服务端用 `uuid4().hex` 生成，`GET /img/<name>` 只接受 `^[0-9a-f]{32}\.(jpg|jpeg|png|gif|webp)$`，客户端改不了路径
- 服务端收到消息里的 `image` 字段会再校验一次文件是否真实存在（`validate_image`），伪造引用直接回 `BAD_IMAGE`
- 前端从桥的握手消息里拿图片服务地址，所以同一份构建在局域网另一台机器上也能用

## 并发模型

- 服务端每来一个连接 `accept()` 就起一个 daemon 线程（`socket_server._handle`），线程内循环 `recv → 拆包 → dispatch → 回包`
- 一条连接对应一个 `RequestContext`，登录前后复用同一对象，`room_id` 由登录结果覆盖
- 在线用户表 `Dict[user_id, socket]` 用 `threading.Lock` 保护；广播时先复制一份列表再发，避免持锁做 IO
- Agent 调用是阻塞的（要等大模型），单独放 `ThreadPoolExecutor`，不占住连接线程
- 定时总结是独立的一根常驻线程（`AutoSummaryScheduler`），用 `Event.wait(interval)` 等待，改间隔立刻生效；真正执行丢给同一个 Agent 线程池，不会卡住连接线程
- 图片服务是 `ThreadingHTTPServer`，每个上传/下载请求一个短线程，跟聊天协议完全分开
- 客户端一侧有两条线程链：桥给每个页面起一条 `tcp-link` 线程做阻塞 `recv`，前端在自己的主线程里跑 React；两者之间只通过 WebSocket 传 JSON，不共享内存状态

## 已知限制

- `AGENT_TIMEOUT` 只出现在 Agent 失败提示文案里，没有真正给模型调用设超时（`agent_core.py` 里是硬编码的 `timeout=30`）；`MAX_HISTORY` 定义了但没有任何代码读取。
- 历史按 20 条一页向前翻，只有滚到顶部才会请求下一页；消息按天分隔，但每条只显示本地时区的 `HH:MM`，不显示秒和完整日期。
- 前端消息流是普通 DOM 列表（没有虚拟滚动）：几百条以内很稳，单个会话堆到上千条时首屏渲染会变慢。
- 聊天室固定一个 `main` 群，没有建群 / 拉人 / 退群；私聊按 `pm:a:b` 自动建房间（见上面「房间模型」）。
- 图片服务没有做鉴权：局域网内谁都能 `POST /upload`（只限制了类型和 8MB 大小）。课设演示够用，上公网要加 token。
- 私聊里问 Agent 的回答不落库（`scope=private` 只单播给提问者），刷新页面后看不到历史；这是刻意的，避免私聊问答被群聊总结翻出来。
- 定时总结以"群聊新消息条数"为触发门槛，没有做持久化游标，服务端重启后会把最近 40 条重新算一次（`_summary_cursor` 存在内存里）。
- 窗口宽度小于 1180px 时右侧栏隐藏，小于 820px 时侧栏也隐藏，只留会话区；高分屏缩放交给浏览器/系统处理。

## 界面设计与实现

定稿方向是「铅印」：黑白灰打底、直角方块、1px 墨线分隔，荧光青柠只做"荧光笔"式单点强调（未读、自己发的消息、Agent 徽标）。这套样式的单文件原型还留在 `client/ui/mockup-b1-ink.html`，浏览器直接打开就能看，用来对照最终实现。

正式界面在 `client/web/`（Vite + React + TypeScript），没有 UI 框架、没有 CSS 框架，全部手写：

| 文件 | 职责 |
| --- | --- |
| `App.tsx` | 三栏布局与弹层编排 |
| `store.ts` | 消息 reducer：会话分线程、历史分页合并、按 id 去重、未读数 |
| `rows.ts` | 把消息流切成「日期分隔 / 系统提示 / 消息组」，同人 2 分钟内的连续发言并成一组 |
| `use-chat.ts` | 状态 + 桥接 + 指令解析（`@Agent`、`/pm`、`/auto`…）的粘合层 |
| `rich.tsx` | Agent 回复的轻量 markdown（加粗、行内代码、列表、标题） |
| `emoji.ts` / `upload.ts` | 表情表 + "整条只有表情就放大"；图片压缩与上传 |
| `components/` | Sidebar / Transcript / Message / Composer / EmojiPicker / SidePanel / AuthGate |

几个刻意的实现选择：

- **时间不会被挤掉**：头像 28px 网格列 + 内容列，时间用 `margin-left:auto` 占内容列右端，名字过长时截名字而不是压时间；消息流右侧留 padding 给滚动条。
- **系统提示单独成块**：居中、两侧引线 + `SYSTEM` / `ERROR` 标签，相邻系统消息合并成一条，错误单独红棕色调。
- **滚动位置自己管**：向上翻页前记录 `scrollHeight/scrollTop`，插入后补回差值，视口钉在原地；离开底部时出现「回到最新」。
- **不整表重渲染**：新消息只 append，历史只在翻页时合并。

> 早期版本曾把这套界面塞在单个 Tkinter 文件里，用 `Text` 控件的 tab 制表位去模拟「头像 + 名字 + 右侧时间」，窗口一窄就错位、时间被裁、系统提示只能是一行灰字。这也是后来整体换成 Vite + React 的原因。

> `client/web/dist/` 是构建产物，为了让没装 Node 的机器 clone 下来就能跑，特意提交进仓库；改过前端要重新 `npm run build` 再提交。

## 开发约定

- 新增消息类型：在 `services/router.py` 的 `build_default_router()` 注册 `type → handler`，handler 签名 `(ctx: RequestContext, msg: dict) -> Optional[dict]`，返回 `dict` 表示回一个包，返回 `None` 表示自己已经发过了
- 新增 Agent 工具：在 `agent/tools.py` 里写实现 + 往 `TOOLS_SPEC` 加声明 + 在 `TOOLS` 注册（文件末尾的 `assert` 会校验两边一致）；需要房间上下文的工具还要加进 `_ROOM_BOUND`，并且**必须**在实现里调 `_require_group_room()` —— 这是 Agent 看不到私聊的最后一道闸
- 打印聊天内容的地方不用自己处理编码：`server/console.py` 已经把 stdout 设成"编不出的字符替换"，Windows GBK 控制台遇到 emoji 也不会抛 `UnicodeEncodeError`
- 写数据库一律走 `chat_history.py` 里的函数，不要在业务层直接写 SQL
- 改表结构：`db.py` 的 `SCHEMA` 用的是 `CREATE TABLE IF NOT EXISTS`，对已存在的库不会生效，改字段时要么删库重建，要么自己写 `ALTER TABLE` 迁移
