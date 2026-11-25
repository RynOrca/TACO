"""井字棋：服务端权威棋盘，支持「人对 Agent」与「人对人」，其他人可以观战。

为什么状态不放在模型里：
  - 模型会"忘记"棋盘、前后矛盾，答辩时说不清谁在维护状态；
  - 放在服务端后，非法着法、抢跑、重复落子都能被拒绝，Agent 只能通过
    game_move 工具改棋盘，界面上每次落子也都会留下一条真实工具调用记录。

一局棋的两种形态：
  - `o_user is None`：人 vs Agent，Agent 执 O（模型不可用时本地 minimax 代打）
  - `o_user` 有值：人对人，双方各执一色，服务端按 `turn` 校验"轮到你才能动"
"""

import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

EMPTY = " "
WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)
# Agent 局的文案（相对玩家 X）
RESULT_CN = {"win": "你赢了", "lose": "Agent 赢了", "draw": "平局"}
# 邀请有效期：超过就作废，免得一小时后突然冒出个邀请
INVITE_TTL_SECONDS = 120


def render_board(board: List[str]) -> str:
    cells = [c if c != EMPTY else str(i + 1) for i, c in enumerate(board)]
    return (
        f" {cells[0]} │ {cells[1]} │ {cells[2]}\n"
        "───┼───┼───\n"
        f" {cells[3]} │ {cells[4]} │ {cells[5]}\n"
        "───┼───┼───\n"
        f" {cells[6]} │ {cells[7]} │ {cells[8]}"
    )


def _winner_of(board: List[str]) -> Optional[str]:
    for a, b, c in WIN_LINES:
        if board[a] != EMPTY and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _minimax(board: List[str], player: str) -> int:
    winner = _winner_of(board)
    if winner == "O":
        return 10
    if winner == "X":
        return -10
    if EMPTY not in board:
        return 0

    scores = []
    for i, cell in enumerate(board):
        if cell != EMPTY:
            continue
        board[i] = player
        scores.append(_minimax(board, "X" if player == "O" else "O"))
        board[i] = EMPTY
    return max(scores) if player == "O" else min(scores)


def best_move(board: List[str], mark: str = "O") -> Optional[int]:
    """本地兜底：选一个对当前执子方最优的格子（1-9）。"""
    best_score, best_cell = -100, None
    for i, cell in enumerate(board):
        if cell != EMPTY:
            continue
        board[i] = mark
        score = _minimax(board, "X" if mark == "O" else "O")
        board[i] = EMPTY
        if score > best_score:
            best_score, best_cell = score, i + 1
    return best_cell


class Game:
    """一盘棋。`x_user` 先手，`o_user` 为空表示对手是 Agent。"""

    def __init__(self, x_user: str, o_user: Optional[str] = None,
                 room_id: Optional[int] = None, game_id: Optional[str] = None):
        self.id = game_id or uuid.uuid4().hex[:8]
        self.x_user = x_user
        self.o_user = o_user
        self.room_id = room_id
        self.board: List[str] = [EMPTY] * 9
        self.turn = "X"
        self.over = False
        self.result = ""            # win（X 胜）/ lose（O 胜）/ draw
        self.winner: Optional[str] = None   # "X" / "O" / None
        self.cancelled = False
        self.created_at = time.time()
        self.updated_at = time.time()
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 基本信息
    @property
    def vs_agent(self) -> bool:
        return self.o_user is None

    def players(self) -> Dict[str, Optional[str]]:
        return {"X": self.x_user, "O": self.o_user or "Agent"}

    def mark_of(self, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        if user_id == self.x_user:
            return "X"
        if self.o_user and user_id == self.o_user:
            return "O"
        return None

    def user_of(self, mark: str) -> Optional[str]:
        return self.x_user if mark == "X" else self.o_user

    def involves(self, user_id: str) -> bool:
        return self.mark_of(user_id) is not None

    def legal_moves(self) -> List[int]:
        return [i + 1 for i, c in enumerate(self.board) if c == EMPTY]

    def render(self) -> str:
        return render_board(self.board)

    def snapshot(self) -> dict:
        return {
            "id": self.id,
            "players": self.players(),
            "vs_agent": self.vs_agent,
            "board": list(self.board),
            "turn": self.turn,
            "over": self.over,
            "result": self.result,
            "winner": self.winner,
            "legal": self.legal_moves(),
        }

    # ---------------------------------------------------------------- 落子
    def move(self, cell, user_id: Optional[str] = None,
             mark: Optional[str] = None) -> Tuple[bool, str]:
        """落子。user_id 给定时按"轮到你才能动"校验；mark 留给 Agent 工具直接指定。"""
        with self._lock:
            if self.over:
                return False, "这盘已经结束了"
            if user_id is not None:
                mine = self.mark_of(user_id)
                if mine is None:
                    return False, "这盘棋不是你参与的"
                mark = mine
            if mark is None:
                return False, "缺少执子方"
            if self.turn != mark:
                who = self.players().get(self.turn) or self.turn
                return False, f"还没轮到你，现在轮到 {who}"

            try:
                cell = int(cell)
            except (TypeError, ValueError):
                return False, "格子编号必须是 1-9 的整数"
            if not 1 <= cell <= 9:
                return False, "格子编号必须在 1-9 之间"
            idx = cell - 1
            if self.board[idx] != EMPTY:
                return False, f"格子 {cell} 已经有棋子了"

            self.board[idx] = mark
            self.updated_at = time.time()
            if _winner_of(self.board) == mark:
                self.over = True
                self.winner = mark
                self.result = "win" if mark == "X" else "lose"
                return True, self.result
            if EMPTY not in self.board:
                self.over = True
                self.result = "draw"
                return True, "draw"
            self.turn = "O" if mark == "X" else "X"
            return True, "ok"

    def forfeit(self, loser_user: str) -> bool:
        """一方掉线/退出：判对方胜。返回是否真的改动了棋局。"""
        with self._lock:
            if self.over:
                return False
            loser = self.mark_of(loser_user)
            if loser is None:
                return False
            self.over = True
            self.winner = "O" if loser == "X" else "X"
            self.result = "lose" if self.winner == "O" else "win"
            self.updated_at = time.time()
            return True

    def auto_move(self) -> Optional[int]:
        """Agent 兜底落子（本地 minimax），返回落子格。"""
        with self._lock:
            if self.over or self.turn != "O":
                return None
            cell = best_move(list(self.board), "O")
        if cell is None:
            return None
        ok, _ = self.move(cell, mark="O")
        return cell if ok else None


class GameService:
    """对局与战绩管理。一人同时只在一局里；观战不占用对局名额。"""

    def __init__(self, users):
        self.users = users
        self._games: Dict[str, Game] = {}
        self._by_user: Dict[str, str] = {}
        self._invites: Dict[str, dict] = {}     # 被邀请人 -> {from, ts}
        self._scores: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 查询
    def get(self, game_id: str) -> Optional[Game]:
        with self._lock:
            return self._games.get(game_id)

    def current(self, user_id: str) -> Optional[Game]:
        with self._lock:
            gid = self._by_user.get(user_id)
            return self._games.get(gid) if gid else None

    def finished_for(self, user_id: str) -> List[Game]:
        """我参与过、已经结束、快照还留着的棋局（开新局前要清掉）。"""
        with self._lock:
            return [g for g in self._games.values()
                    if g.over and g.involves(user_id)]

    def ongoing(self) -> List[Game]:
        with self._lock:
            return [g for g in self._games.values() if not g.over]

    # ---------------------------------------------------------------- 开局
    def _register(self, game: Game) -> Game:
        with self._lock:
            self._games[game.id] = game
            self._by_user[game.x_user] = game.id
            if game.o_user:
                self._by_user[game.o_user] = game.id
        return game

    def start_vs_agent(self, user_id: str, room_id=None) -> Game:
        game = Game(user_id, None, room_id)
        return self._register(game)

    def invite(self, inviter: str, invitee: str) -> Tuple[bool, str]:
        if inviter == invitee:
            return False, "不能邀请自己"
        with self._lock:
            if self._by_user.get(inviter):
                return False, "你已经有进行中的对局了"
            if self._by_user.get(invitee):
                return False, f"{invitee} 正在对局中"
            self._invites[invitee] = {"from": inviter, "ts": time.time()}
        return True, f"已邀请 {invitee}，等对方回复（{INVITE_TTL_SECONDS} 秒内有效）"

    def pending_invite(self, user_id: str) -> Optional[dict]:
        with self._lock:
            invite = self._invites.get(user_id)
            if invite is None:
                return None
            if time.time() - invite["ts"] > INVITE_TTL_SECONDS:
                self._invites.pop(user_id, None)
                return None
            return dict(invite)

    def _take_invite(self, user_id: str) -> Optional[dict]:
        with self._lock:
            invite = self._invites.pop(user_id, None)
        if invite is None:
            return None
        if time.time() - invite["ts"] > INVITE_TTL_SECONDS:
            return None
        return invite

    def accept(self, invitee: str) -> Tuple[bool, str, Optional[Game]]:
        invite = self._take_invite(invitee)
        if invite is None:
            return False, "没有待接受的邀请（可能已过期）", None
        inviter = invite["from"]
        with self._lock:
            if self._by_user.get(inviter) or self._by_user.get(invitee):
                return False, "有一方已经在别的对局里了", None
        game = Game(inviter, invitee, None)
        return True, f"{inviter} 和 {invitee} 开局，{inviter} 执 X 先手", self._register(game)

    def decline(self, invitee: str) -> Tuple[bool, Optional[str]]:
        invite = self._take_invite(invitee)
        if invite is None:
            return False, None
        return True, invite["from"]

    def drop(self, user_id: str) -> Optional[Game]:
        with self._lock:
            gid = self._by_user.pop(user_id, None)
            game = self._games.pop(gid, None) if gid else None
            if game is not None:
                # 把对手也从这个对局里摘掉
                for player in (game.x_user, game.o_user):
                    if player and self._by_user.get(player) == gid:
                        self._by_user.pop(player, None)
        if game is not None:
            game.cancelled = True
        return game

    def release(self, game: Game) -> None:
        """结算后释放玩家名额：他们可以马上开新局，但棋局快照还留着给双方看结果。"""
        with self._lock:
            for player in (game.x_user, game.o_user):
                if player and self._by_user.get(player) == game.id:
                    self._by_user.pop(player, None)

    def prune(self, max_age: float = 300.0) -> None:
        """清掉早就结束、也没人再看的老棋局，避免 _games 无限增长。"""
        now = time.time()
        with self._lock:
            stale = [gid for gid, g in self._games.items()
                     if g.over and now - g.updated_at > max_age]
            for gid in stale:
                self._games.pop(gid, None)

    def clear_invites(self, user_id: str) -> None:
        with self._lock:
            self._invites.pop(user_id, None)

    # ---------------------------------------------------------------- 战绩
    def record(self, game: Game) -> None:
        with self._lock:
            for user, mark in ((game.x_user, "X"), (game.o_user, "O")):
                if not user:
                    continue
                score = self._scores.setdefault(user, {"win": 0, "lose": 0, "draw": 0})
                if game.result == "draw":
                    score["draw"] += 1
                elif game.winner == mark:
                    score["win"] += 1
                else:
                    score["lose"] += 1

    def score_text(self, user_id: str) -> str:
        score = self.score(user_id)
        return f"战绩：胜 {score['win']} / 负 {score['lose']} / 平 {score['draw']}"

    def score(self, user_id: str) -> Dict[str, int]:
        with self._lock:
            return dict(self._scores.get(user_id, {"win": 0, "lose": 0, "draw": 0}))


# ---------------------------------------------------------------- Agent 工具
def game_tools(game: Game, user_id: str):
    """把当前这盘棋绑进工具闭包：模型只能看到/操作这一盘。"""

    def game_get_board() -> str:
        players = game.players()
        return (
            f"当前棋盘（数字是空位）：\n{game.render()}\n"
            f"可落子位置：{game.legal_moves()}\n"
            f"轮到：{game.turn}（X={players['X']}，O={players['O']}）"
        )

    def game_move(cell) -> str:
        try:
            cell = int(cell)
        except (TypeError, ValueError):
            return "[ToolError] cell 必须是 1-9 的整数，例如 game_move(cell=5)。"
        ok, msg = game.move(cell, mark="O")
        if not ok:
            return (f"[ToolError] {msg}。可落子位置：{game.legal_moves()}，"
                    f"请重新选择。")
        if game.over:
            return f"落子成功：O 下在 {cell}，本局结束（{RESULT_CN[game.result]}）。\n{game.render()}"
        return f"落子成功：O 下在 {cell}。\n{game.render()}"

    spec = [
        {
            "type": "function",
            "function": {
                "name": "game_get_board",
                "description": "读取当前井字棋棋盘、可落子位置和轮到谁。落子前可以调用一次确认局面。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "game_move",
                "description": (
                    "在井字棋棋盘上落子。cell 取 1-9，只能选可落子位置。\n"
                    "你执 O，玩家执 X；每轮只能调用一次。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cell": {"type": "integer", "description": "1-9 的格子编号"},
                    },
                    "required": ["cell"],
                },
            },
        },
    ]
    return spec, {"game_get_board": game_get_board, "game_move": game_move}
