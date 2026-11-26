# TACO

**TCP-Agent Chatroom Online** —— 基于原生 Socket 的多线程聊天室，内置一个会自己查聊天记录、会下井字棋的 AI Agent。

课程设计项目：不依赖任何 Web 框架，从 TCP 粘包处理、消息路由、数据持久化一路写到 Agent 工具调用与定时任务，动手搭建整个链路。

> 本 README 对应「协议 v2 + 心跳超时 + 定时任务 + 井字棋（含点击棋盘）」这一版。
> 下文有 [验收演示脚本](#验收演示脚本15-分钟)、[截图清单](#截图清单写报告用) 和 [报告素材对照](#报告素材对照)，可以直接照着做答辩与报告。

---

## 本版新增（相对原始版本）

| 版本 | 改动 | 解决的问题 | 主要落点 |
| --- | --- | --- | --- |
| v1.1 | **协议 v2**：4 字节头 → 8 字节头（magic + version + type + uint32 length） | 单帧超过 64KB 时 `struct.pack` 抛异常，客户端连错误码都收不到就断线 | `server/network/protocol.py` |
| v1.2 | **心跳与超时回收** | 拔网线/挂起虚拟机/暂停进程这类"半开连接"永远发现不了，用户一直挂在在线列表里 | `keepalive.py`、`user_service.py`、`socket_client.py`、`bridge.py` |
| v1.3 | **定时任务泛化** | 原来只有写死的「定时总结」，间隔在内存里，重启就丢 | `scheduler.py`、`scheduled_tasks` 表、`/task` 指令 |
| v1.4 | **井字棋 + 点击落子** | 新增一个"和 Agent 玩"的扩展功能，棋盘由服务端持有，Agent 必须调工具落子 | `game_service.py`、`GamePanel.tsx`、`game` 消息 |
| v1.5 | **延迟监测 / 离线未读 / 撤回 / @提及 / 禁言 / 通用附件** | 六个实用功能：rtt 可观测、离线回来知道哪些是新的、发错了能撤回、@ 人能补全并高亮、管理员能禁言、图片之外还能传文档 | 见下面「功能总览」扩展行 |

四项改动都单独提交过 commit，可以按功能回滚；前端 `client/web/dist` 已重新构建，不需要装 Node 也能直接跑。

---

## 功能总览

| 分类 | 功能 | 说明 |
| --- | --- | --- |
| 通信 | 注册 / 登录 | `/register 用户名 密码`、`/login 用户名 密码`，密码 PBKDF2-SHA256 加盐；同名重连会踢掉旧连接 |
| 通信 | 群聊 | 直接输入内容发送，服务端广播给所有在线用户 |
| 通信 | 私聊 | `/pm 目标用户 消息`，两人固定映射到 `pm:a:b` 房间，双向一致，第三人收不到 |
| 通信 | 在线列表 | 用户上下线时向所有人推送 `userlist`，客户端实时渲染成员面板 |
| 通信 | 历史消息 | 全部落 SQLite，按房间+时间建索引；首屏最近 20 条，滚到顶部按 `before_id` 向前翻页 |
| 通信 | 异常断线 | FIN/RST（杀进程）立即清理；半开连接（挂起/断网）由应用层心跳在 `CHAT_IDLE_TIMEOUT` 秒内回收 |
| 通信 | 心跳 / RTT | 客户端定时 ping，服务端回 pong 带 seq 与时间戳；桥的终端日志会打 `[Link] ... RTT 1ms` |
| Agent | 提问 / 总结 | 群里 `@Agent 问题` 公开回答，`/agent 问题` 只回自己，`/agent@group` 指定公开；提问本身也会落库并显示 |
| Agent | 真实工具调用 | 读历史、检索、存总结/待办、读服务器时间、联网搜索；每次调用的名字/参数/耗时/结果预览随回复回传，界面按「真实工具调用 N 次」展开 |
| Agent | 定时任务 | `summary`（定时总结）/ `reminder`（定时提醒），任务落 SQLite、可增删启停、重启恢复；`/auto` 保留兼容 |
| Agent | 井字棋（人对 Agent） | 服务端棋盘 + 侧栏可点击棋盘；Agent 通过 `game_move` 工具落子，非法着法被拒绝；模型不可用时本地 minimax 代打 |
| 扩展 | 棋牌室（井字棋 / 五子棋 / 21 点） | `/game start [ttt\|gomoku\|bj]` 对 Agent，`/game invite 用户名 [gomoku]` 对人；15×15 五子棋与 21 点共用同一套邀请 / 观战 / 断线判负 / 再来一局 |
| 扩展 | 21 点的隐藏信息 | 最多 3 人同桌，服务端按连接裁剪视图：每个人只拿到自己的牌与所有人张数，Agent 只拿到自己的牌与张数，观战者只有明牌；别人的牌在 JSON 里根本不存在 |
| 扩展 | 专注游戏 / 剧场布局 | 进对局自动切专注（左栏折叠、聊天压窄、中间大棋盘），`全屏` 进剧场（聊天变浮层），`Esc` 回聊天且对局不中断 |
| 扩展 | 记录持久化与检索 | SQLite + 分页 + 关键词检索，Agent 的 `search_chat_history` 走同一套 DAO |
| 扩展 | 表情与图片 | Unicode 表情（纯表情放大）；图片压到最大边 1280，走 HTTP 上传，消息里只传文件名，支持 Ctrl+V 粘贴截图 |
| 扩展 | 工具调用记录 | `steps` 字段回传 name/args/ok/ms/preview，答辩可直接展开 |
| 扩展 | 定时任务 / 井字棋 | 见上，均超出课设「至少两个扩展」的要求 |
| 扩展 | 延迟监测 | 每 5 秒 ping/pong 算 RTT（页面 → 桥 → TCP → 服务端整条链路），右栏显示 `rtt`，>200ms 标黄、超时标红 |
| 扩展 | 离线消息提醒 | `room_reads` 记已读水位，登录时下发未读；侧栏徽标 + 历史里「离线期间 N 条新消息」虚线 |
| 扩展 | 消息撤回 | 自己 2 分钟内的消息可撤回，按房间类型投递（群播 / 私聊双方 / Agent 房间只通知本人）；撤回内容不进 Agent 检索 |
| 扩展 | @提及 | 服务端只认真实用户名；渲染高亮（@自己荧光色）、输入框补全、被 @ 时徽标变荧光 `@` |
| 扩展 | 禁言 | `ADMIN_USERS` 限定；群聊/私聊/问 Agent 三条通道都拦并提示剩余秒数；成员面板与右栏同步标记 |
| 扩展 | 通用附件 | 图片 + pdf/zip/文档/源码/音视频；落盘名 `<32hex><后缀>`，原名/大小存 `messages.meta`，界面渲染成文件卡片 |
| 界面 | 图形客户端 | Vite + React 三栏界面，经 Python 桥接层走原生 TCP；支持登录、群聊、私聊、成员、待办、Agent 卡片、游戏面板、历史翻页 |

---

## 与课设要求对照

| 课设要求 | 本项目的实现 | 验收时怎么演示 |
| --- | --- | --- |
| 1. Socket TCP 连接、多客户端、断线、粘包/拆包 | 自研 8 字节帧头 + JSON；每连接一个线程；缓冲区累积、半包等待、一次 recv 多包循环解；心跳超时回收 | 3 个客户端同时在线；杀掉一个进程立刻消失；挂起一个客户端，15 秒后被心跳回收（日志可见） |
| 2. 注册登录、在线列表、私聊、群聊、界面 | PBKDF2 加盐、`userlist` 广播、`pm:a:b` 单播、React 三栏界面 | 注册两个新号登录；互相发群聊/私聊；第三人看不到私聊 |
| 3. @Agent 问答、群聊总结、待办提取 | Function Calling 版 ReAct；总结/待办走工具读写 SQLite | 群里 `@Agent 总结一下刚才的讨论并列出待办`，看回复和右栏待办面板 |
| 4. ≥1 种真实工具调用并展示调用记录 | 5 个通用工具 + 井字棋 2 个工具；每次调用记录 `name/args/ok/ms/preview` | 展开 Agent 卡片的「真实工具调用 N 次」；井字棋每一步也是一条 `game_move` |
| 5. ≥2 个自定义功能 | 持久化检索、表情/图片、定时任务、井字棋、工具调用记录（5 个） | 翻历史、发图片、`/task add reminder in:1 ...`、侧栏下一局棋 |
| 6. 模型不可用时聊天室仍正常 | `AgentUnavailable` 转成普通回复；井字棋用 minimax 兜底 | 清空 `.env` 的 `LLM_API_KEY` 重启，聊天照常，棋局也能继续 |

---

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
carol ──socket──►   │   agent:alice / agent:bob（各自与 Agent 的私聊）   │
                    └────────────────────────────────────────────────────┘
Agent 默认只被授权读 main；pm:* 永远读不到；agent:<本人> 只在本人明确授权时才读
```

三个 `room_type='private'` 的房间长得很像，权限完全不同：

| 房间 | 谁能读 | Agent 能不能读 |
| --- | --- | --- |
| `pm:alice:bob` | alice、bob | **永远不能**（不是工具能选的 scope） |
| `agent:alice` | 只有 alice | 只有 alice 自己发起、并且勾了「包含私聊」时，才能用 `scope="agent_private"` 读 |
| `main` | 所有人 | 默认就能读 |

---

## 项目架构

服务端按职责分层：网络接入层、业务逻辑层、Agent 与工具层、数据存储层。客户端负责通信与 UI。

```
├── server/                  # 【服务端】
│   ├── main.py              # 启动入口：初始化数据库、启动监听 / 心跳回收 / 定时任务
│   ├── config.py            # 配置：读取 .env（端口、数据库、心跳、定时、LLM/Tavily Key）
│   ├── console.py           # 让 Windows GBK 控制台遇到 emoji 时不再抛异常
│   ├── models.py            # 数据模型（User / Message / TodoItem）
│   │
│   ├── network/             # 【网络接入层】
│   │   ├── socket_server.py # 连接线程、收包拆包、keepalive、协议错误处理
│   │   ├── protocol.py      # 核心：v2 帧（8 字节头 + JSON）、粘包/拆包、帧上限
│   │   ├── keepalive.py     # IdleReaper：扫描 last_seen，回收半开连接
│   │   ├── image_server.py  # 图片 HTTP 通道：POST /upload、GET /img/<文件名>
│   │   └── asyncio_server（协程）.py   # 早期协程版实现，仅作对照保留
│   │
│   ├── services/            # 【业务逻辑层】
│   │   ├── router.py        # 消息分发：type → handler，ping 应答带 seq/时间戳
│   │   ├── user_service.py  # 登录、在线表、连接活跃时间、单播/广播
│   │   ├── chat_service.py  # 群聊/私聊/图片、Agent 编排、定时总结、井字棋指令
│   │   ├── game_service.py  # 井字棋：棋盘、胜负、minimax、Agent 工具
│   │   ├── scheduler.py     # TaskScheduler：通用定时任务（summary/reminder）
│   │   └── context.py       # RequestContext + Services 容器（避免循环 import）
│   │
│   ├── agent/               # 【Agent 与工具层】
│   │   ├── agent_core.py    # Prompt、模型调用、ReAct 循环、工具执行、调用记录
│   │   └── tools.py         # 通用工具实现 + Function Calling 声明 + 房间授权护栏
│   │
│   └── storage/             # 【数据存储层】
│       ├── db.py            # 连接管理（WAL + 每线程连接 + busy_timeout）、建表
│       └── chat_history.py  # 消息/待办/用户/房间/任务 的 CRUD
│
├── client/                  # 【客户端】
│   ├── bridge.py            # 桥：一个页面一条 TCP ↔ 本地 WebSocket，托管静态文件
│   ├── socket_client.py     # TCP 收发线程 + 心跳线程 + 命令行交互
│   ├── web/                 # Vite + React + TS 前端
│   │   ├── src/
│   │   │   ├── App.tsx / store.ts / use-chat.ts
│   │   │   ├── components/  # Sidebar / Transcript / Message / Composer / SidePanel / GamePanel / HelpDialog …
│   │   │   └── styles.css
│   │   └── dist/            # 构建产物（已提交，不装 Node 也能跑）
│   └── ui/mockup-b1-ink.html  # 定稿风格的静态原型
│
├── database/chat.db         # SQLite（自动生成）
├── docs/                    # 模块讲解与本次改动说明
├── .env.example
└── requirements.txt
```

### 客户端为什么多一个 bridge.py

浏览器不能直接开 TCP socket（Web 沙箱里只有 HTTP/WebSocket），而服务端只讲「JSON over TCP」。所以客户端被拆成两半：

```
React 前端 (client/web)          Python 桥 (client/bridge.py)            服务端 (server)
──────────────────────           ────────────────────────────            ──────────────────
DOM 渲染 / 布局 / 滚动           原生 socket + pack_message/try_unpack     TCP + v2 帧
状态 reducer / 历史分页    ⇄     WS 收发的 JSON 原样透传            ⇄      router → service
                                                                          SQLite / Agent / 定时任务
```

- **一个页面一条 TCP 连接**：桥给每个 WebSocket 连接配一条独立的 `ChatClient`，所以「开两个窗口互相发消息」「切换账号」都跟命令行客户端一样干净
- **粘包处理没有被绕开**：桥复用的是 `protocol.py` 的 `pack_message()` / `try_unpack()`，缓冲区累积、半包等待、一次 `recv` 多包循环解，和服务端是同一份实现
- **静态托管**：桥在同一个端口上按路径分发——`/ws` 走 WebSocket 握手，其余当静态文件，所以生产模式只有一个进程、一个端口、一个窗口
- **心跳在桥里**：连上服务端后桥启动心跳线程，pong 在桥里消费并打印 RTT，不污染前端消息流

桥自己只懂两条额外指令：`{"type":"reconnect"}`（让桥重连服务端），以及它主动推送的 `{"type":"link","state":"open|connecting|closed","detail":"…"}`。

---

## 通信协议

### 帧格式（v2：8 字节定长头）

```
+--------+---------+--------+----------------+-----------------+
| magic  | version | type   | length         | body (JSON)     |
| uint16 | uint8   | uint8  | uint32         | length 字节      |
| 0x5443 | 2       | 0-255  | 上限 2MB        | UTF-8           |
+--------+---------+--------+----------------+-----------------+
```

- `magic` = `"TC"`（0x5443），`version` = 2，`length` 为大端 uint32
- `body` 是 `json.dumps(body, ensure_ascii=False).encode("utf-8")`
- 单帧 body 上限 `MAX_FRAME_BYTES = 2MB`：既装得下 600KB 的历史页，也能挡住"声明 4GB 长度"的恶意包
- 收发统一走 `protocol.py` 的 `pack_message()` / `try_unpack()`；`try_unpack()` 返回 `(消息字典, 剩余数据)`，`None` 表示半包，`{}` 表示非法 JSON，**帧头不合法则抛 `ProtocolError`**（调用方记录后关闭连接）
- header 里的 `type` 是数字编码（`TYPE_CODE` 表），body 里也带一份字符串型 `type` 供路由层使用
- 接收端用缓冲区累积：不足一个完整包就等下一批 `recv`，一次 `recv` 里有多包就循环解完 —— 这就是粘包/拆包的处理点

> **为什么从 v1 升级**：v1 的 `length` 是 uint16，单帧最大 65535 字节。历史分页 20 条长中文约 120KB、Agent 长回复也可能超限，`struct.pack("!HH")` 直接抛异常，客户端连错误码都收不到就被断开。v2 换成 uint32 并加 magic/version：版本不对时服务端明确回"协议不匹配"，而不是靠 JSON 解析失败去猜。
>
> 发送侧还有两道保险：`pack_message()` 超限抛 `FrameTooLarge`，回包处转成 `MSG_TOO_LONG` 错误帧而不切断连接；历史分页按字节收缩（单页 ≤512KB），Agent 回复落库前截断到 32KB。

### 心跳与断线检测

| 环节 | 做法 |
| --- | --- |
| 客户端发 | 桥和命令行客户端每 `CHAT_HEARTBEAT_SECONDS` 秒发 `{"type":"ping","seq":n,"ts":ms}` |
| 服务端回 | 回 `{"type":"pong","seq":n,"server_time":ms}`，桥/命令行用 `seq` 匹配发送时刻算 RTT；Web 前端发 `{"type":"ping","t":ms}`，服务端把 `t` 原样带回，前端用 `t` 算整条链路的 RTT |
| 界面显示 | 右栏「会话」的 `rtt` 每 5 秒刷新，>200ms 标黄、超时/断链标红（前端探测与心跳共用 ping，互不干扰） |
| 服务端记 | 收到**任何**帧都刷新该连接的 `last_seen`（正常聊天也算活着），不只是 ping |
| 超时回收 | `IdleReaper` 每 `CHAT_REAP_INTERVAL` 秒扫一遍，超过 `CHAT_IDLE_TIMEOUT` 秒没数据的连接直接断开、广播 `userlist`，终端打 `[Heartbeat] ... 判定掉线` |
| 内核兜底 | 连接建立时开 `SO_KEEPALIVE`（Windows 用 `SIO_KEEPALIVE_VALS` 设 10s/3s） |

它解决的是"半开连接"：进程被暂停、虚拟机挂起、拔网线、路由中断时，双方内核都不会报错，`recv` 会一直阻塞——只有应用层心跳能发现。杀进程/正常退出属于 FIN/RST，`recv` 直接返回 0 或报错，原本就能处理。

演示"异常断线"时把超时调短：

```bash
set CHAT_IDLE_TIMEOUT=15
set CHAT_REAP_INTERVAL=5
set CHAT_HEARTBEAT_SECONDS=5
python -m server.main
```

然后把某个客户端挂起（或直接不启动它的心跳），15 秒左右它就会从成员列表消失，服务端终端同时打出判定日志；其余客户端收发不受影响。

### 消息体（body）约定

请求统一带 `type` 字段作为路由键；`{"sys": true, ...}` 会被路由层直接丢弃。

| type | 方向 | 字段 | 处理函数 |
| --- | --- | --- | --- |
| `register` | C→S | `user_id`, `password`, (`nickname`) | `UserService.handle_register` |
| `login` | C→S | `user_id`, `password` | `UserService.handle_login` |
| `group` | C→S | `msg`；图片消息改填 `image`（文件名） | `ChatService.handle_group` |
| `private` | C→S | `target`, `msg`；图片消息改填 `image` | `ChatService.handle_private` |
| `agent` | C→S | `msg`, `scope`(`private`/`group`), `include_private` | `ChatService.handle_agent` |
| `todos` | C→S | — | `ChatService.handle_todos` |
| `autosummary` | C→S | `action`(`status`/`on`/`off`/`now`), `minutes` | `ChatService.handle_auto_summary`（`/auto` 快捷方式，内部映射到 summary 任务） |
| `task` | C→S | `text`（`list` / `add summary every:10` / `add reminder in:5 开会` / `del|on|off 编号`） | `ChatService.handle_task` |
| `game` | C→S | `text`（`start [ttt\|gomoku\|bj]` / `invite 用户名 [gomoku]` / `accept` / `decline` / `move N` / `hit` / `stand` / `watch` / `board` / `status` / `quit`） | `ChatService.handle_game` |
| `history` | C→S | 可选 `target`、`agent`、`limit`、`before_id` | `ChatService.handle_history`；客户端不能指定 room_id |
| `ping` | C→S | `seq`, `ts`（桥/CLI）或 `t`（Web 前端） | 回 `pong`，原样带回 `seq` / `t` |
| `read` | C→S | `id`（我看到的最后一条）, 可选 `target`/`agent` | `handle_read` 推进已读水位 |
| `recall` | C→S | `id` | `handle_recall`（2 分钟内、只能撤自己的） |
| `mute` | C→S | `action`(`mute`/`unmute`/`list`), `target`, `minutes` | `handle_mute`（仅 `ADMIN_USERS`） |
| `system` | S→C | `msg` | 回执/系统提示 |
| `group` / `private` | S→C | `sender`, `msg`, (`id`, `target`), (`msg_type`, `image`/`file`, `meta`, `mentions`) | 广播/单播；私聊同时回显给发送方；`meta` 是附件原名/大小，`mentions` 是被 @ 的用户名 |
| `agent` | S→C | `sender`, `msg`, `status`(`pending`/`done`), `scope`, `thread`, `steps`, (`scheduled`) | `thread` 决定落在 `main` 还是 `agent`；`steps` 是本轮真实工具调用记录 |
| `agent_ask` | S→C | `sender`, `msg`, `scope`, `id` | 只发给提问者 |
| `autosummary` | S→C | `enabled`, `seconds` | 定时总结状态广播 |
| `unread` | S→C | `unread_items` | 登录时下发各会话离线未读数、其中多少条 @我、上次读到的 id |
| `recall` | S→C | `id`, `sender`, `room_id` | 撤回通知，按房间类型广播/单播 |
| `muted` | S→C | `mutes` | 当前禁言名单（`user_id`/`until_at`/`by_user`） |
| `game` | S→C | `action`(`state`/`invite`/`closed`), `game_id`, `players`{X,O}, `vs_agent`, `board`(9 格), `turn`, `over`, `result`, `winner`, `legal`, `spectators`, `scores` | `state` 广播给房间内所有人（参与者拿到可点击棋盘，其他人只读观战）；`invite` 只发给被邀请人；`closed` 表示这盘从"进行中"里摘掉 |
| `userlist` | S→C | `users` | 在线用户列表 |
| `todos` | S→C | `items` | 当前房间待办 |
| `history` | S→C | `items`, `target`, `before_id`, `more` | 历史消息，按时间正序 |
| `error` | S→C | `code`, `msg` | 见下方错误码 |

错误码：`NOT_LOGIN` `BAD_FORMAT` `BAD_TYPE` `UNKNOWN_TYPE` `INTERNAL` `BAD_LOGIN` `LOGIN_FAILED` `EMPTY_MSG` `MSG_TOO_LONG` `SAVE_FAILED` `BAD_PARAM` `SELF_PM` `USER_OFFLINE` `BAD_REGISTER` `USER_EXISTS` `NOT_REGISTERED` `BAD_PASSWORD` `BAD_IMAGE` `BAD_ATTACHMENT` `NO_SCHEDULER` `BAD_TASK` `NO_GAME` `BAD_MOVE` `BAD_GAME` `NOT_FOUND` `FORBIDDEN` `BAD_STATE` `TOO_LATE` `MUTED`。

消息处理流程：

```
客户端发送消息
    ↓
network/socket_server.py 收包、拆包、刷新 last_seen
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

---

## 数据库设计

SQLite，WAL 模式 + 每线程一个连接（`threading.local`）+ `busy_timeout=5000`，写操作统一走 `transaction()` 自动 commit/rollback。

| 表 | 关键字段 | 说明 |
| --- | --- | --- |
| `rooms` | `room_id`(PK), `name`(UNIQUE), `room_type`, `owner_id`, `created_at` | 群聊 `main`，私聊 `pm:用户A:用户B`（字典序） |
| `users` | `user_id`(PK), `nickname`, `password_hash`, `status`, `last_login` | `password_hash` 存 `pbkdf2_sha256$轮数$盐$哈希` |
| `room_members` | (`room_id`, `user_id`)(PK), `joined_at` | 成员关系，外键级联删除 |
| `messages` | `id`(PK), `room_id`, `sender`, `content`, `msg_type`, `meta`, `created_at` | `msg_type`：`group` / `private` / `image` / `file` / `agent` / `agent_ask_group` / `agent_ask_private` / `recalled` / `summary`；`meta` 是附件消息的 JSON（原名/大小/类型），老库启动时自动 `ALTER TABLE` 补列；索引 `(room_id, created_at)`、`(sender)` |
| `room_reads` | (`room_id`,`user_id`)(PK), `last_read_id`, `updated_at` | 已读水位，只前进不后退；登录时据此算离线未读 |
| `mutes` | `user_id`(PK), `until_at`, `by_user`, `reason`, `created_at` | 禁言；查询时顺手清掉过期记录 |
| `todos` | `id`(PK), `room_id`, `assignee`, `content`, `status`, `created_at`, `done_at` | `status`：`pending` / `done` |
| `scheduled_tasks` | `id`, `kind`, `payload`, `interval_seconds`, `next_run`, `last_run`, `enabled`, `created_by`, `room_id`, `created_at` | 定时任务；`interval>0` 周期、`=0` 一次性；索引 `(enabled, next_run)` |

DAO 约定：

- 所有 SQL 参数用 `?` 占位，防注入
- `LIKE` 检索前转义 `%` `_` `\`
- 读条数统一经 `_clamp()` 限制在 1~100
- 写数据库一律走 `chat_history.py`，业务层不直接写 SQL

详细逐行讲解见 [`docs/chat_history讲解.md`](docs/chat_history讲解.md)。

---

## Agent 与工具层

采用 **Function Calling 版 ReAct 范式**：模型自己决定调哪个工具，`agent_core.run_detailed()` 循环「请求模型 → 执行工具 → 把结果塞回 messages」，直到模型不再要求调用工具或达到 `AGENT_MAX_STEPS`。

| 工具 | 作用 | 参数 | 依赖 |
| --- | --- | --- | --- |
| `read_recent_chat_history` | 读最近消息，按时间正序返回 | `limit`, `scope`（`group` / `agent_private`） | SQLite |
| `search_chat_history` | 关键词 OR 检索历史消息 | `keywords`, `limit`, `scope` | SQLite |
| `save_history_and_todo` | 把总结/待办写库（`kind`=`summary`/`todo`） | `content`, `kind` | SQLite |
| `get_current_time` | 读服务器真实系统时间：日期、星期、时区、Unix 时间戳 | — | `datetime.now()` |
| `tavily_search` | 联网搜索实时信息 | `query`, `max_results`, `max_content_length` | `TAVILY_API_KEY` |
| `game_get_board` | 读当前井字棋棋盘、可落子位置、轮到谁 | — | 井字棋（按需注入） |
| `game_move` | 在棋盘上落子（O 方），非法格会被拒绝 | `cell`(1-9) | 井字棋（按需注入） |

每次工具调用都会生成一条记录 `{name, args, ok, ms, preview}`，跟回复的 `steps` 字段发到客户端，卡片显示「真实工具调用 N 次」+ 逐条展开。记录的是**真实执行**（`time.perf_counter()` 计时、异常如实标 `ok=false`），不是预设文案。

安全设计（课设要求 Agent 只能碰"授权范围内"的内容）：

1. **`room_id` 不出现在工具 schema 里**。`build_room_tools()` 用闭包把服务端算好的 `room_id` 绑进实现，模型看不到也填不了。
2. **两段授权范围**：只把 `group` 和（获授权时）`agent_private` 交给模型选，`pm:a:b` 从来不在这张表里。
3. **授权是每轮请求的开关**：只有客户端带 `include_private: true`，服务端才把 `agent:<user>` 绑进工具；没勾时连 `scope` 字段都没有。
4. **问答各自落库**：`scope=group` 进 `main`；`scope=private` 只进 `agent:<我>`，绝不写进群聊历史。
5. **工具返回内容是数据，不是指令**：system prompt 明确要求不执行工具结果里的命令式文字，防提示词注入。

其它防护：单次工具结果截断 4000 字符；参数类型错误回给模型自我纠正；Agent 调用在独立线程池（4 worker）；模型没配 Key 时 `AgentUnavailable` 转成普通回复。

### 图片消息为什么要多一个 HTTP 服务

v2 的单帧上限已经到 2MB，但图片仍走 HTTP，原因是：一张图最大 8MB、聊天消息要广播给所有人、浏览器 `<img>` 天然支持缓存和按需加载。把二进制塞进每一帧会让所有客户端都多传一份。

```
浏览器 ──压缩到最大边 1280──► POST http://<服务端>:10087/upload  ──► database/images/<32位hex>.jpg
        └── TCP: {"type":"group","msg":"[图片]","image":"<32位hex>.jpg"} ──► 广播给所有人
接收端 <img src="http://<服务端>:10087/img/<32位hex>.jpg">
```

- 文件名由服务端用 `uuid4().hex` 生成，`GET /img/<name>` 只接受 `^[0-9a-f]{32}\.(jpg|jpeg|png|gif|webp)$`
- 服务端收到 `image` 字段会再校验文件真实存在（`validate_image`），伪造引用回 `BAD_IMAGE`

---

## 定时任务

### 数据模型

`scheduled_tasks` 表：`kind`（`summary` / `reminder`）、`payload`、`interval_seconds`、`next_run`/`last_run`、`enabled`、`created_by`、`room_id`。

- `interval_seconds > 0`：周期任务
- `interval_seconds = 0`：一次性任务，跑完自动 `enabled=0`
- `next_run` / `last_run` 存 UTC ISO 时间，调度线程按 `next_run` 排序取到期任务

### 调度行为

- 线程每 `CHAT_TASK_TICK` 秒（默认 5s）扫一次 `enabled=1 AND next_run<=now`
- **先推进 `next_run` 再执行**，避免任务执行慢导致下一轮重复触发
- `summary` 丢进 Agent 线程池；`reminder` 直接广播 `system` 消息，零外部依赖
- 服务端重启：周期任务错过若干周期只顺延到下一次（不补跑一堆积压）；一次性提醒停机期间到期，启动后补跑一次
- `/auto` 保留为 summary 任务的快捷方式：`/auto 5` = 设置每 5 分钟，`/auto off` = 暂停，`/auto now` = 立即执行一次

### 指令

| 输入 | 作用 |
| --- | --- |
| `/task list` | 列出全部任务（编号 / 类型 / 周期 / 下次时间 / 状态） |
| `/task add summary every:10` | 每 10 分钟让 Agent 总结一次 |
| `/task add reminder in:5 开会` | 5 分钟后广播一次提醒 |
| `/task add reminder every:30 起来活动` | 每 30 分钟提醒一次 |
| `/task del 3` / `/task on 3` / `/task off 3` | 删除 / 开启 / 暂停 |

---

## 井字棋（和 Agent 对弈）

### 玩法

```
/game start        开一局（你执 X，先手）
/game move 5       把棋子下在第 5 格（1-9，左上到右下）
/game board        看当前棋盘
/game status       看战绩
/game quit         退出当前对局
```

也可以直接在右侧「井字棋」面板点格子落子。棋盘用文本渲染，数字是空位：

```
 1 │ 2 │ 3
───┼───┼───
 4 │ X │ 6
───┼───┼───
 7 │ O │ 9
```

### 为什么状态放服务端

如果让模型"记住"棋盘，会出现忘步、重复占格、自己改棋局。所以 `game_service.py` 的 `Game` 持有唯一权威棋盘：

- `move(cell, mark)` 校验轮次、范围、是否为空、是否已结束；8 条连线判胜负、下满判平局
- Agent 工具用**闭包**绑定当前这一盘：`game_get_board` / `game_move`，模型只能看到函数名和参数
- 玩家落子 → 服务端判胜负 → 广播「Agent 思考中」+ 棋盘 → 才把这一轮丢进 Agent 线程池
- Agent 每轮最多 4 步 ReAct，落子后一句话点评；界面显示成一条真实工具调用记录
- 模型不可用/没给出合法着法时，本地 minimax 代打一步并注明，棋局不会卡死

### 前端可点击棋盘

服务端在开局、落子、Agent 落子、看棋盘时，给**下棋本人**发结构化状态：

```json
{"type":"game","action":"state","board":["X","O"," ","..."],"turn":"O",
 "over":false,"result":"","score":{"win":1,"lose":0,"draw":0}}
```

`store.ts` 收进 `state.game`，`GamePanel` 渲染 3×3 按钮：轮到你且格子为空才可点，Agent 思考中整盘禁用，结束后显示结果、战绩和「再来一局」，退出时收 `action:"closed"` 清空。群里其他人只看到文本播报。

---

## 快速开始

### 1. 环境要求

- Python 3.12（开发环境；3.13 也可运行）
- Node.js 20+（只在构建/开发前端时需要，跑起来之后不依赖 Node）
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

至少填 `LLM_API_KEY` 和 `LLM_MODEL_ID`；完整字段见下方[环境变量](#环境变量)。`.env` 含密钥，不要提交。

### 4. 初始化数据库

不需要手动建表，首次 `init_db()` 会自动建库建表（`database/chat.db`）。想先验证存储层：

```bash
python -m server.storage.chat_history
```

> 必须用 `-m` 模块方式、在项目根目录执行。

### 5. 启动服务端

```bash
python -m server.main
```

正常输出：

```
数据库就绪：<项目根>\database\chat.db
图片服务启动成功，监听 0.0.0.0:10087
心跳检测已启动：阈值 60s，扫描间隔 5s
定时任务已启动：/task 管理任务（/auto 仍兼容）
聊天室 TCP 服务器启动成功，监听 0.0.0.0:10086
```

两个端口的分工：`10086` 是 TCP 聊天协议（v2 帧），`10087` 只干图片上传/下载。

### 6. 构建前端（只需一次；仓库里已有 dist 可跳过）

```bash
cd client/web
npm install
npm run build
```

### 7. 启动客户端

```bash
python -m client.bridge
```

会起一个本地桥（默认 `http://127.0.0.1:8765/`），连服务端，并用 Edge/Chrome 的 `--app` 无地址栏窗口打开界面。先点「注册」建号，再点「登录」。

常用参数：

```bash
python -m client.bridge --no-open          # 只起桥，不开窗口
python -m client.bridge --with-server      # 服务端没起时顺手拉起来
python -m client.bridge --port 10086       # 指定服务端端口
python -m client.bridge --ws-port 8765     # 指定桥端口
```

> 开三个客户端：同一个桥地址再开两个浏览器窗口/标签页即可，每个页面一条独立 TCP 连接。

前端改动要热更新时开两个终端：

```bash
python -m client.bridge --no-open          # 终端 1：桥
cd client/web && npm run dev               # 终端 2：Vite dev server（5173）
```

然后访问 <http://127.0.0.1:5173/>。

命令行版本（调试用）：

```bash
python -m client.socket_client
```

> 两个客户端都要用 `-m` 方式启动：它们复用了 `server/network/protocol.py` 里的收发包函数。

---

## 常用指令

| 输入 | 作用 |
| --- | --- |
| `@Agent 问题` | 群里公开提问，答案发回群聊 |
| `/agent 问题` | 向 Agent 提问，只回给自己 |
| `/agent@group 问题` | 指定在群里公开回答 |
| `/auto 5` / `/auto off` / `/auto now` | 定时总结：每 5 分钟 / 关闭 / 立刻总结一次（不带参数＝查状态） |
| `/task list` | 列出全部定时任务 |
| `/task add summary every:10` | 每 10 分钟自动总结 |
| `/task add reminder in:5 开会` | 5 分钟后提醒 |
| `/task del` / `on` / `off` + 编号 | 删除 / 开启 / 暂停任务 |
| `/game start` | 和 Agent 开一局井字棋 |
| `/game move 5` | 下在第 5 格 |
| `/game board` / `/game status` / `/game quit` | 看棋盘 / 看战绩 / 退出 |
| `/pm 目标用户 消息` | 私聊 |
| `/help` | 使用说明弹窗（指令 + 快捷键 + 功能一览） |
| `/register`、`/login`、`/quit` | 注册 / 登录 / 退出 |
| 其他内容 | 直接作为群聊消息发送（界面可点「图片」或 Ctrl+V 粘贴截图） |

---

## 服务端终端日志

只要有人发消息，服务端终端就会打一行，群聊和私聊一个格式：

```
用户 [anna] 登录成功，room=1
[群聊] anna 说：今晚八点联调（room 1 main · 127.0.0.1:55226）
[私聊] ben 对 anna 说：这是界面发的私聊 😀（room 6 pm:anna:ben · 127.0.0.1:51634）
[群聊] anna 说：[图片 ac2b6c57efad4582a0c232e2454f00f4.png]（room 1 main · 127.0.0.1:55226）
[Agent] Agent 说：本群最近讨论了联调时间…（room 1 main）
[Image] 收到图片 ac2b6c57efad4582a0c232e2454f00f4.png（227 字节，image/png）
[Task] #2 触发定时总结
[Task] #3 提醒已广播：开会
[Heartbeat] silent 超过 6s 没有任何数据（阈值 6s），判定掉线并断开
客户端 ('127.0.0.1', 51634) 已断开
```

几个实现细节：

- 统一走 `console.py` 的 `log_line()`：整行一次写出并加锁，多线程打印不会粘成一行
- 单行超过 300 字截断，避免长消息刷屏；入库内容不受影响
- Windows 终端默认 GBK，emoji 会显示成 `?`；用 Windows Terminal 或 `chcp 65001` 即可正常显示
- 输出重定向到文件时自动切 UTF-8

---

## 验收演示脚本（15 分钟）

> 建议按这个顺序演示，正好覆盖课设的验收点。提前开好服务端 + 3 个客户端窗口。

### 0. 准备（1 分钟）

```bash
# 终端 1：服务端（演示异常断线时把超时调短）
set CHAT_IDLE_TIMEOUT=15
set CHAT_REAP_INTERVAL=5
set CHAT_HEARTBEAT_SECONDS=5
python -m server.main

# 终端 2：桥（开三个浏览器窗口登录三个账号）
python -m client.bridge
```

### 1. 三个客户端同时在线 + 群聊（1.5 分钟）

- 三个窗口分别注册登录 `alice` / `bob` / `carol`
- 右栏成员列表显示 3 人
- alice 发群聊，三个窗口同时出现

**讲解点**：每连接一个线程、服务端广播、在线列表推送。

### 2. 私聊隔离（1 分钟）

- alice 输入 `/pm bob 压测报告下午能发吗`
- bob 和 alice 能看到，carol 看不到
- 服务端终端同时打出 `[群聊]` 与 `[私聊]` 两行，房间号不同

**讲解点**：私聊是同一进程里的另一条投递路径，不是另一个服务器。

### 3. 异常断线：FIN 与半开连接（2 分钟）

- carol 直接关闭窗口/杀进程 → 1 秒内从成员列表消失（FIN 路径）
- bob 在任务管理器里「挂起」进程（或断开它的网络）→ 15 秒后从列表消失，服务端打出 `[Heartbeat] ... 判定掉线`
- 其余两人继续聊天不受影响

**讲解点**：FIN/RST 靠内核就能发现；挂起/断网是半开连接，只能靠应用层心跳 + last_seen 回收。

### 4. 大帧与历史翻页（1 分钟）

- 连续发几条长消息（或提前准备好），向上翻历史
- 连接保持正常，不会掉线

**讲解点**：v1 的 uint16 长度上限是 65535，翻一页长中文就会断；v2 换成 uint32（上限 2MB）并在发送侧做了截断/收缩。

### 5. @Agent 完整链路（3 分钟）

- alice 发：`@Agent 总结一下群里刚才聊的，并列出待办`
- 先出现「正在思考」，再出现 Agent 回复
- 展开卡片「真实工具调用 N 次」，逐条展示 `read_recent_chat_history` / `get_current_time` 的名字、参数、耗时、结果预览
- 右栏待办面板出现条目

**讲解点**：工具是真实执行（有耗时、有结果预览），不是预设文案；Agent 只能读群聊，读不到私聊。

### 6. 定时任务（1.5 分钟）

```
/task add reminder in:1 大家准备联调
/task list
```

- 1 分钟后群里出现 `⏰ 定时提醒：大家准备联调`
- `/task list` 显示该任务已「暂停」（一次性任务跑完自动关闭）
- `/task add summary every:2` 可再演示周期任务
- 重启服务端后 `/task list` 任务仍在（落库）

### 7. 井字棋（2 分钟）

- 右栏点「开始一局」，出现 3×3 棋盘
- **点击格子**落子，群里同步文本播报
- 展开 Agent 卡片的工具记录，指出 `game_move(cell=…)`
- 下到分出胜负，面板显示结果、战绩和「再来一局」
- 可选：清空 `LLM_API_KEY` 重启再走一步，展示 minimax 兜底

### 8. 收尾（1 分钟）

- 打开 `README.md` 的架构图/协议表，讲清「网络层 → 路由 → 服务 → 存储」的分层
- 点一下 `/help` 弹窗，展示所有指令

---

## 截图清单（写报告用）

| 编号 | 操作 | 画面要点 | 对应报告章节 |
| --- | --- | --- | --- |
| S1 | 启动服务端 | 数据库/图片/心跳/定时任务/监听 5 行日志 | 开发环境 |
| S2 | 项目目录树（VSCode 资源管理器） | server / client / docs / database 分层 | 实验设计思路 |
| S3 | 三个客户端登录 | 右侧成员列表 3 人 | 运行结果 |
| S4 | 群聊 + 私聊同时存在 | 三个窗口消息差异；服务端终端两行日志 | 运行结果 |
| S5 | @Agent 总结 | Agent 卡片展开「真实工具调用 N 次」+ 待办面板 | 运行结果 / 关键代码 |
| S6 | 挂起一个客户端 | 服务端 `[Heartbeat] ... 判定掉线`，成员列表少一人 | 测试过程 |
| S7 | 长消息历史翻页 | 翻页正常、连接状态仍为在线 | 测试过程 |
| S8 | `/task list` + 提醒触发 | 任务编号/周期/状态，群里 `⏰ 定时提醒` | 运行结果 |
| S9 | 井字棋开局 | 右侧 3×3 棋盘，提示「轮到你（X）」 | 运行结果 |
| S10 | 点击落子 | 棋盘出现 X，Agent 回复，卡片里 `game_move` | 关键代码 / 运行结果 |
| S11 | 对局结束 | 面板显示「你赢了 / Agent 赢了」、战绩、再来一局 | 运行结果 |
| S12 | 用 DB Browser for SQLite 打开 `database/chat.db`（或 `sqlite3 database/chat.db ".tables"`） | rooms/users/messages/todos/scheduled_tasks | 数据库设计 |
| S13 | 旧协议客户端连新服务端（可选） | 服务端日志 `协议错误 ... 魔数不匹配`，服务保持可用 | 测试过程 |

> 截图建议：服务端与客户端并排；关键日志用高亮框；每张图配一句"这证明了什么"。

---

## 测试记录

以下结果均为本地实跑（Windows、Python 3.13、独立测试库；Agent 用 mock LLM 模拟 function calling，保证可重复）：

| 测试集 | 用例数 | 结果 | 覆盖点 |
| --- | --- | --- | --- |
| 协议 v2 + 心跳 | 4 | PASS | 240KB 历史回包、超长消息 `MSG_TOO_LONG`、静默连接回收、旧协议帧头处理 |
| 聊天室回归 | 7 | PASS | 三客户端在线、群聊、私聊隔离、@Agent 工具记录、历史、ping/pong、杀进程清理 |
| 定时任务 | 11 | PASS | 创建/列表/一次性提醒/自动暂停/定时总结/周期排期/`/auto` 兼容/非法参数/删除 |
| 定时任务持久化 | 3 | PASS | 重启后任务仍在、错过周期顺延、启停 |
| 井字棋规则 | 13 | PASS | 抢跑/越界/重复/胜负/平局/minimax 能赢会堵/工具校验/结束后拒绝 |
| 井字棋联调 | 9 | PASS | 开局/落子/Agent `game_move`/非法着法/双人隔离/退出 |
| 井字棋结构化状态 | 8 | PASS | 9 格空盘、只发本人、落子同步、Agent 落子同步、重开恢复、退出关闭 |
| 井字棋前端 | 11 | PASS | reducer 更新/清空、9 格渲染、禁用规则、结束文案、开始按钮 |
| 前端构建 | — | PASS | `tsc --noEmit && vite build` |

> 命令行的会话记录、服务端日志、前端测试输出都可以作为"测试过程"的素材；截图清单里的 S6/S7/S13 尤其适合放在测试章节。
>
> 前端交互（点击棋盘、禁用规则、结束状态）用 Node + `renderToStaticMarkup` 做了 11 条断言；浏览器端请按截图清单实际点一遍，录屏也以浏览器画面为准。

---

## 报告素材对照

| 实验报告章节 | 对应 README 内容 | 建议配图 |
| --- | --- | --- |
| 实验设计思路 | 房间模型、项目架构、通信协议（帧格式/心跳/消息表） | S2 目录树、协议帧示意图（可自己画） |
| 开发环境 | 快速开始、环境变量、requirements.txt | S1 启动日志 |
| 关键代码 | 协议 v2、心跳回收、定时任务、井字棋工具闭包、Agent `execute_tool` | S5 工具卡片、S10 `game_move` |
| 运行结果截图 | 功能总览、验收脚本 1-7 步 | S3-S5、S8-S11 |
| 测试过程 | 测试记录、错误码、常见问题 | S6 心跳日志、S7 大帧翻页、S13 协议错误 |
| 心得体会 | 已知限制（诚实写不足）、常见问题（踩坑） | 无 |

> 写报告时建议把"为什么这样做"讲清楚，例如：为什么用 8 字节帧头而不是分片、为什么棋盘状态放服务端、为什么定时任务要落库——这几点是区分"能跑"和"讲得清"的地方。

---

## 环境变量

`.env.example` 里有完整注释，常用项：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CHAT_HOST` | `0.0.0.0` | 监听地址；只本机测试可填 `127.0.0.1` |
| `CHAT_PORT` | `10086` | TCP 聊天端口 |
| `CHAT_DB_PATH` | `database/chat.db` | SQLite 路径；留空会打开临时库，**不要写成空值** |
| `CHAT_IMAGE_PORT` | `10087` | 图片 HTTP 端口 |
| `CHAT_IMAGE_DIR` | `database/images` | 图片落盘目录 |
| `CHAT_IMAGE_MAX_BYTES` | `8388608` | 单张图片上限（8MB） |
| `CHAT_HEARTBEAT_SECONDS` | `20` | 客户端发 ping 的间隔 |
| `CHAT_IDLE_TIMEOUT` | `60` | 服务端判定掉线的阈值 |
| `CHAT_REAP_INTERVAL` | `5` | 回收线程扫描间隔 |
| `CHAT_TASK_TICK` | `5` | 定时任务扫描间隔（演示可设 1） |
| `LLM_API_KEY` | 空 | OpenAI 兼容接口 Key；留空时 Agent 降级、聊天正常 |
| `LLM_BASE_URL` | 空 | 第三方兼容地址（带 `/v1`）；官方接口注释掉 |
| `LLM_MODEL_ID` | 空 | 模型名，如 `deepseek-chat` |
| `TAVILY_API_KEY` | 空 | 联网搜索工具用；留空只影响该工具 |
| `AGENT_MAX_STEPS` | `5` | ReAct 最大步数 |
| `AGENT_TIMEOUT` | `60` | 目前只用于失败提示文案，未真正中断请求 |
| `AGENT_AUTO_SUMMARY_SECONDS` | `0` | 启动时自动创建的 summary 任务周期（秒），0 关闭 |
| `AGENT_AUTO_SUMMARY_MIN_MESSAGES` | `3` | 定时总结的"新消息条数"门槛 |
| `MAX_HISTORY` | `20` | 定义了但当前未被读取 |
| `CHAT_FILE_MAX_BYTES` | `20971520` | 通用附件单文件上限（20 MB） |
| `CHAT_FILE_EXTS` | 见 `.env.example` | 附件后缀白名单（pdf/zip/文档/源码/音视频…） |
| `ADMIN_USERS` | 空 | 能禁言/解禁的人，逗号分隔；留空则没人有权限 |

---

## 已知限制

- `AGENT_TIMEOUT` 只出现在失败提示文案里，模型调用实际是硬编码 `timeout=30`；`MAX_HISTORY` 未被读取。
- 历史按 20 条一页向前翻，只有滚到顶部才会请求下一页；每条只显示本地时区的 `HH:MM`。
- 前端消息流是普通 DOM 列表（没有虚拟滚动）：几百条以内很稳，单会话上千条时首屏渲染会变慢。
- 聊天室固定一个 `main` 群，没有建群 / 拉人 / 退群；私聊按 `pm:a:b` 自动建房间。
- 图片服务没有鉴权：局域网内谁都能 `POST /upload`（只限制类型和 8MB）。上公网要加 token。
- Agent 提问和回答都会落库；历史里的 Agent 卡片不保存 `steps`，会显示"历史记录 · 工具调用细节未保存"。
- 「包含我与 Agent 的私聊」会公开：勾选后私聊内容可能被写进群总结，界面有提示。
- 定时总结的 `_summary_cursor` 仍在内存里，重启后会重新算最近 40 条；任务本身已落库。
- 井字棋的棋局和战绩在内存里，服务端重启清空；每人同时一盘；刷新页面后要点一次「开始一局」/`/game` 才会恢复面板。
- 窗口宽度小于 1180px 时右侧栏隐藏，小于 820px 时侧栏也隐藏。

---
- 终端里的消息日志单行截断到 300 字；GBK 控制台下 emoji 显示为 `?`（用 Windows Terminal / `chcp 65001` 可正常显示）。
- 附件服务没有鉴权：局域网内谁都能 `POST /upload`（只限制了类型和大小）。上公网要加 token。
- 禁言需要管理员权限，`ADMIN_USERS` 没配时 `/mute` 会提示 `FORBIDDEN`；判断只在这一层，没有更细的角色体系。
- 已读水位按"看到最后一条消息的 id"推进，多端登录会互相覆盖（同一账号只保留一份水位）。
- 被禁言的人还能下井字棋：`/game` 是独立 handler，禁言只拦群聊/私聊/问 Agent 三条通道。
- 井字棋：每人同时只有一盘"自己的棋"，观战不限盘数；棋局和战绩在内存里，服务端重启清空。
- 井字棋的进度会广播给全群（每步一行、不打完整棋谱）；同时开多盘时群里能看到所有对局的进度。

## 还没做的

`docs/待办-语音消息.md`：语音消息（用户录音 + Agent 语音播报）的可行性评估与落地方案。DeepSeek 2026-11-13 上线了官方 TTS（`POST /v1/tools/tts`，`stella`/`tide` 两个音色，`wav`/`pcm` 两种格式，`filter_markdown` 自动去掉 Markdown 再念），这条链路可行；文档里写了接口细节、计费、失败降级和"只念前 N 字"的取舍。

## 界面设计与实现

定稿方向是「铅印」：黑白灰打底、直角方块、1px 墨线分隔，荧光青柠只做"荧光笔"式单点强调（未读、自己发的消息、Agent 徽标）。单文件原型在 `client/ui/mockup-b1-ink.html`。

正式界面在 `client/web/`（Vite + React + TypeScript），没有 UI 框架、没有 CSS 框架，全部手写：

| 文件 | 职责 |
| --- | --- |
| `App.tsx` | 三栏布局与弹层编排 |
| `store.ts` | 消息 reducer：会话分线程、历史分页合并、去重、未读数、井字棋状态 |
| `rows.ts` | 把消息流切成「日期分隔 / 系统提示 / 消息组」 |
| `use-chat.ts` | 状态 + 桥接 + 指令解析（`@Agent`、`/pm`、`/auto`、`/task`、`/game`） |
| `rich.tsx` | Agent 回复的轻量 markdown |
| `emoji.ts` / `upload.ts` | 表情表 + 图片压缩上传 |
| `components/GamePanel.tsx` | 井字棋面板：3×3 可点击棋盘、战绩、开始/退出 |
| `components/` | Sidebar / Transcript / Message / Composer / EmojiPicker / SidePanel / AuthGate / HelpDialog |

几个刻意的实现选择：

- **时间不会被挤掉**：头像 28px 网格列 + 内容列，时间 `margin-left:auto`；名字过长截名字不压时间
- **系统提示单独成块**：居中、两侧引线 + `SYSTEM` / `ERROR` 标签，相邻系统消息合并
- **滚动位置自己管**：翻页前记录 `scrollHeight/scrollTop`，插入后补差值，视口钉在原地
- **不整表重渲染**：新消息只 append，历史只在翻页时合并
- **多行系统提示保留换行**：`/task list` 这类结果用 `white-space: pre-wrap` 渲染

> `client/web/dist/` 是构建产物，为没装 Node 的机器特意提交；改过前端要重新 `npm run build` 再提交。

---

## 开发约定

- 新增消息类型：在 `router.py` 的 `build_default_router()` 注册 `type → handler`，签名 `(ctx, msg) -> Optional[dict]`；返回 `dict` 表示回一个包，`None` 表示自己已经发过
- 新增 Agent 工具：在 `tools.py` 写实现 + 加 `TOOLS_SPEC` 声明 + 在 `TOOLS` 注册（末尾 `assert` 会校验）；需要房间上下文的工具还要加进 `_ROOM_BOUND`，并调 `_require_group_room()`
- 新增定时任务类型：在 `scheduler.py` 的 `_run()` 里按 `kind` 分发，注意**先把 next_run 推好再执行**
- 新增游戏类功能：状态放服务端，Agent 只能通过工具改状态；同时给本人推结构化状态，前端才有点击交互
- 打印聊天内容不用自己处理编码：`console.py` 已把 stdout 设成"编不出的字符替换"
- 改表结构：`SCHEMA` 用 `CREATE TABLE IF NOT EXISTS`，对已存在的库不生效，改字段要写 `ALTER TABLE` 迁移或删库重建

---

## 常见问题

**Q1：Agent 一直回"暂不可用"？**
检查 `.env` 的 `LLM_API_KEY` / `LLM_MODEL_ID`；第三方接口要填 `LLM_BASE_URL`（一般带 `/v1`）。没有 Key 时聊天、定时提醒、井字棋都照常，只有 Agent 问答和总结降级。

**Q2：客户端一登录就提示协议错误？**
服务端和客户端必须是同一版（v2 帧）。用仓库里的 `dist` 和同一份 Python 代码；如果混用了旧版命令行客户端，会出现"帧头魔数不匹配"。

**Q3：历史翻页把连接搞断？**
v1 才会；v2 已把单帧上限提到 2MB 并按字节收缩历史页。若仍断，确认 `server/network/protocol.py` 是新版。

**Q4：成员列表里有人一直不下线？**
确认客户端在发心跳（桥日志应有 `RTT`）。服务端默认 60 秒没数据才回收；演示时按验收脚本把阈值调到 15 秒。

**Q5：端口被占用？**
改 `CHAT_PORT` / `CHAT_IMAGE_PORT`，桥用 `--port` 指过去。

**Q6：改了前端但界面没变？**
`dist` 是构建产物，需要 `cd client/web && npm run build`；开发模式用 `npm run dev` + 桥的 `--no-open`。

**Q7：数据库表少了 `scheduled_tasks`？**
用旧库启动时会自动 `CREATE TABLE IF NOT EXISTS` 建出来；如果没有，确认 `init_db()` 正常执行、没有连到临时库（`CHAT_DB_PATH` 不能是空值）。
