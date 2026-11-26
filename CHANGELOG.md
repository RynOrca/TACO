# CHANGELOG

记录每次改动对应的 git 提交，方便回退。

## a9d9354 · fix(game): 结算后能真正再来一局/关闭，重开按钮改成横排居中

**现象**：21 点（以及人机井字棋、人机五子棋）结算后点「再来一局」报
`NO_GAME 没有可重开的对局`，点「关闭」也毫无反应；21 点结算后的两个按钮竖着堆在中间。

**原因**：`_finish_game` 结算后会 `release` 释放玩家名额，此时 `games.current(user)`
已经是 `None`，代码退回到"已结束但还留着"的棋局里找。这个兜底列表原先带
`not g.vs_agent` 过滤（21 点、人机局的 `vs_agent` 都是 `True`），于是找不到任何一盘 →
返回 `NO_GAME`（点「关闭」时返回"当前没有进行中的对局。"，界面上的结果面板也不会清）。

**改动**
- `server/services/chat_service.py`
  - `rematch` / `quit` 的兜底查找不再排除 `vs_agent` 对局
  - 21 点重开走同桌确认逻辑（一个人也要确认，一桌人要等所有人），不再用
    `start_vs_agent` 单开一张桌，免得把同桌的人丢了
  - 21 点中途离开改用已存在的 `GameService.remove_player`，原来的
    `self.games.drop(...)` 并不存在，多人牌桌点退出会直接抛异常
- `client/web/src/components/RematchBar.tsx` + `styles.css`：「再来一局 / 关闭」包进
  `.rematch-actions.center`，横排并居中；`client/web/dist` 已重新构建

**验证**：直接调用 `ChatService.handle_game` 跑通 单人人机（bj/ttt/gomoku）重开、
结算后关闭、三人牌桌依次离开三条路径；`tsc --noEmit && vite build` 通过。
