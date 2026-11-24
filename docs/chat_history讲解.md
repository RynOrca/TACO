`chat_history.py` 本质上是聊天室里的“档案管理员”（也就是常说的 **DAO**，**数据访问层**）。

核心任务：**把复杂的 SQL 数据库操作包装成极其简单的 Python 函数，让上层（Agent 工具、聊天业务）只需要调用 `chat_history.save_message()` 就能存数据，完全不需要碰 SQL 语句。**

## 一、“保安”模块（内部工具与安全防漏）

```python
def _clamp(limit: int, default: int = 20) -> int:
    # 1. 安全上限拦截：防止 Agent 疯了一上来就读/写 10000 条，导致服务器卡死
    try: limit = int(limit)
    except: limit = default
    return max(1, min(limit, MAX_LIMIT))  # 限制在 1~100 之间
```

```python
def _like(keyword: str) -> str:
    # 2. 防 SQL 注入 + 特殊字符转义
    # 数据库里 LIKE 语句用 % 代表通配符。如果用户搜 "100%"，数据库会崩溃。
    # 所以把 % 换成 \%，保证数据库只找字面意义上的 %。
    kw = (keyword or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{kw}%"
```

```python
def _require_room(room_id: int) -> int:
    # 3. 房间存在性检查：存消息前，先看这个房间是不是真的存在
    if not room_exists(room_id):
        raise ValueError(f"聊天室不存在：room_id={room_id}")
    return int(room_id)
```

## 二、档案存储模块（存消息、存总结、存待办）

### 1. 基础写入：`save_message`

```python
def save_message(room_id, sender, content, msg_type="group"):
    # 1. 确认房间存在
    _require_room(room_id)
    # 2. 开启数据库事务（保证要么完全写入，要么出错回滚，不会只写一半）
    with transaction() as tx:
        cur = tx.execute(
            """INSERT INTO messages (room_id, sender, content, msg_type, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            # 3. 自动填入当前时间（UTC 字符串）
            (room_id, sender, content.strip(), msg_type, now_iso()),
        )
        # 4. 返回新消息的数据库 ID
        return cur.lastrowid
```

### 2. 特化写入：`save_history` 与 `save_todo` 

这是专门为 Agent 工具 服务的。
- `save_history`：把 Agent 写好的总结存起来。它本质上也是调用 `save_message`，但把类型 `msg_type` 强制写死为 "summary"。这样以后在聊天界面就可以把总结和普通聊天区分开。
- `save_todo`：把待办事项存到另一张表 todos 里。因为待办后续还需要“标记为已完成”（update_todo），所以它不能塞进普通聊天记录。


## 三、档案检索模块（读历史、搜历史）

- `get_recent_history`

```python
def get_recent_history(room_id, limit=20):
    limit = _clamp(limit) # 限制读取条数
    # 1. 从数据库倒序读取（DESC），也就是最新消息在前
    rows = get_conn().execute("""... ORDER BY created_at DESC ... LIMIT ?""", (room_id, limit)).fetchall()
    # 2. row_to_message：把冰冷的数据库行（Row对象）转换为代码里定义的 Message 数据模型
    return [row_to_message(r) for r in rows]
```

- `search_history`：**多个关键字，只要命中其中任意一个就算匹配（OR 逻辑），且命中关键字越多的消息，排在越前面。**

```python
def search_history(room_id, keywords, limit=20):
    # ... 参数清洗 ...
    
    # 1. 构造 SQL 占位符
    # 如果关键词是 ["性能", "压测"]：
    # where 变成: content LIKE ? ESCAPE '\' OR content LIKE ? ESCAPE '\'
    # rank 变成: CASE WHEN content LIKE ? THEN 1 ELSE 0 END + CASE WHEN ... THEN 1 ELSE 0 END
    like_params = [_like(k) for k in kws]
    where = " OR ".join(["content LIKE ? ESCAPE '\\'"] * len(kws))
    rank = " + ".join(["CASE WHEN content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END"] * len(kws))

    # 2. 执行搜索并排序
    # 排序逻辑：(rank) DESC（命中关键字越多的排前面） -> created_at DESC（新消息排前面）
    rows = get_conn().execute(f"""
        SELECT ...
        WHERE room_id = ? AND ({where})
        ORDER BY ({rank}) DESC, created_at DESC 
        LIMIT ?
    """, [room_id] + like_params + like_params + [limit]).fetchall()
    
    return [row_to_message(r) for r in rows]
```