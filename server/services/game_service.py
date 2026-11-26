"""服务端权威棋牌：井字棋、五子棋、21 点。

为什么状态不放在模型里：
  - 模型会"忘记"棋盘、前后矛盾，答辩时说不清谁在维护状态；
  - 放在服务端后，非法着法、抢跑、重复落子都能被拒绝，Agent 只能通过
    game_move 工具改棋盘，界面上每次落子也都会留下一条真实工具调用记录。

三种牌桌共用一套"房间"语义（id / 两个玩家 / 观战 / 断线判负 / 再来一局）：

  Game(kind="ttt"|"gomoku")  棋盘类，X 先手；o_user 为空时对手是 Agent
  BlackjackGame              21 点，玩家 vs Agent 庄家，按视角裁剪手牌（见 blackjack.py）
"""

import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

EMPTY = " "
# 各棋种：棋盘边长、连成几子算赢
BOARD_SPECS = {
    "ttt": {"name": "井字棋", "size": 3, "win": 3},
    "gomoku": {"name": "五子棋", "size": 15, "win": 5},
}
# 结果文案（相对玩家 X）
RESULT_CN = {"win": "你赢了", "lose": "Agent 赢了", "draw": "平局"}
# 邀请有效期：超过就作废，免得一小时后突然冒出个邀请
INVITE_TTL_SECONDS = 120
# 人对人结束后"再来一局"的确认窗口：双方都要在这么长时间内点确认
REMATCH_WINDOW_SECONDS = 10
# 五子棋候选点只看已有棋子两格以内，避免每步扫全盘
GOMOKU_NEAR = 2


def game_name(kind: str) -> str:
    if kind == "bj":
        return "21 点"
    return BOARD_SPECS.get(kind, BOARD_SPECS["ttt"])["name"]


def render_board(board: List[str], size: int = 3) -> str:
    """文本棋盘（命令行客户端与 Agent 提示词用）。空位显示编号。"""
    head = "   " + " ".join(f"{x + 1:>2}" for x in range(size))
    lines = [head]
    for y in range(size):
        row = []
        for x in range(size):
            i = y * size + x
            cell = board[i]
            row.append(" ." if cell == EMPTY else f" {cell}")
        lines.append(f"{y + 1:>2} " + " ".join(row))
    return "\n".join(lines)


def _line_cells(size: int, x: int, y: int, dx: int, dy: int, length: int) -> Optional[List[int]]:
    """从 (x,y) 出发沿 (dx,dy) 取 length 个格子，越界返回 None。"""
    ex, ey = x + dx * (length - 1), y + dy * (length - 1)
    if not (0 <= ex < size and 0 <= ey < size):
        return None
    return [(y + dy * k) * size + (x + dx * k) for k in range(length)]


DIRECTIONS = ((1, 0), (0, 1), (1, 1), (1, -1))


def find_win(board: List[str], size: int, win_len: int) -> Optional[Tuple[str, List[int]]]:
    """全盘扫描（只在落子后调用一次）：返回 (获胜方, 连成一线的格子)。"""
    for y in range(size):
        for x in range(size):
            mark = board[y * size + x]
            if mark == EMPTY:
                continue
            for dx, dy in DIRECTIONS:
                cells = _line_cells(size, x, y, dx, dy, win_len)
                if cells and all(board[i] == mark for i in cells):
                    return mark, cells
    return None


def _minimax(board: List[str], player: str) -> int:
    found = find_win(board, 3, 3)
    if found:
        return 10 if found[0] == "O" else -10
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


def best_ttt_move(board: List[str], mark: str = "O") -> Optional[int]:
    """井字棋兜底：完全搜索，必不败。"""
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


# ---------------------------------------------------------------- 五子棋启发式
def _pattern_score(board: List[str], size: int, x: int, y: int, mark: str) -> int:
    """某个空点上，mark 落子后在四个方向形成的威胁分（越大越好）。"""
    total = 0
    for dx, dy in DIRECTIONS:
        count = 1
        open_ends = 0
        for sign in (1, -1):
            step = 1
            while True:
                nx, ny = x + dx * step * sign, y + dy * step * sign
                if not (0 <= nx < size and 0 <= ny < size):
                    break
                cell = board[ny * size + nx]
                if cell == mark:
                    count += 1
                    step += 1
                    continue
                if cell == EMPTY:
                    open_ends += 1
                break
        if count >= 5:
            total += 100_000
        elif count == 4:
            total += 12_000 if open_ends == 2 else 4_000
        elif count == 3:
            total += 800 if open_ends == 2 else 220
        elif count == 2:
            total += 90 if open_ends == 2 else 20
        elif open_ends == 2:
            total += 6
    return total


def best_gomoku_move(board: List[str], size: int, mark: str) -> Optional[int]:
    """只看已有棋子附近的空点：先算自己的成杀点，再算挡对方的点。"""
    opponent = "O" if mark == "X" else "X"
    candidates: List[int] = []
    for y in range(size):
        for x in range(size):
            if board[y * size + x] != EMPTY:
                continue
            near = False
            for dy in range(-GOMOKU_NEAR, GOMOKU_NEAR + 1):
                for dx in range(-GOMOKU_NEAR, GOMOKU_NEAR + 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < size and 0 <= ny < size and board[ny * size + nx] != EMPTY:
                        near = True
                        break
                if near:
                    break
            if near:
                candidates.append(y * size + x)

    if not candidates:                      # 空盘：下天元
        center = size // 2
        return center * size + center + 1

    best_cell, best_score = None, -1
    for idx in candidates:
        attack = _pattern_score(board, size, idx % size, idx // size, mark)
        defence = _pattern_score(board, size, idx % size, idx // size, opponent)
        score = attack + int(defence * 0.9)
        if score > best_score:
            best_score, best_cell = score, idx + 1
    return best_cell


class Game:
    """棋盘类对局（井字棋 / 五子棋共用）。"""

    kind = "ttt"

    def __init__(self, x_user: str, o_user: Optional[str] = None,
                 room_id: Optional[int] = None, game_id: Optional[str] = None,
                 kind: str = "ttt"):
        spec = BOARD_SPECS.get(kind, BOARD_SPECS["ttt"])
        self.kind = kind if kind in BOARD_SPECS else "ttt"
        self.size: int = spec["size"]
        self.win_len: int = spec["win"]
        self.id = game_id or uuid.uuid4().hex[:8]
        self.x_user = x_user
        self.o_user = o_user
        self.room_id = room_id
        self.board: List[str] = [EMPTY] * (self.size * self.size)
        self.turn = "X"
        self.over = False
        self.result = ""            # win（X 胜）/ lose（O 胜）/ draw
        self.winner: Optional[str] = None
        self.win_cells: List[int] = []
        self.last_move: Optional[int] = None
        self.cancelled = False
        self.created_at = time.time()
        self.updated_at = time.time()
        self.rematch_votes: set = set()
        self.rematch_deadline: Optional[float] = None
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

    def involves(self, user_id: str) -> bool:
        return self.mark_of(user_id) is not None

    def legal_moves(self) -> List[int]:
        return [i + 1 for i, c in enumerate(self.board) if c == EMPTY]

    def render(self) -> str:
        return render_board(self.board, self.size)

    def status_line(self) -> str:
        whose = "轮到 " + (self.players()[self.turn] or self.turn)
        if self.over:
            if self.result == "draw":
                return "平局"
            return f"{self.players()[self.winner]} 获胜"
        return whose

    def snapshot(self, viewer: Optional[str] = None) -> dict:
        return {
            "kind": self.kind,
            "size": self.size,
            "win_len": self.win_len,
            "players": self.players(),
            "vs_agent": self.vs_agent,
            "board": list(self.board),
            "turn": self.turn,
            "over": self.over,
            "result": self.result,
            "winner": self.winner,
            "win_cells": list(self.win_cells),
            "last_move": self.last_move,
            "legal": self.legal_moves() if self.size <= 3 else [],
            "rematch": {
                "votes": sorted(self.rematch_votes),
                "deadline": int(self.rematch_deadline * 1000) if self.rematch_deadline else 0,
                "window": REMATCH_WINDOW_SECONDS,
            },
        }

    def view_for(self, viewer: Optional[str]) -> dict:
        """棋盘类没有隐藏信息，所有人看到同一份。"""
        return self.snapshot(viewer)

    # ---------------------------------------------------------------- 落子
    def move(self, cell, user_id: Optional[str] = None,
             mark: Optional[str] = None) -> Tuple[bool, str]:
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
                return False, "格子编号必须是整数"
            if not 1 <= cell <= len(self.board):
                return False, f"格子编号必须在 1-{len(self.board)} 之间"
            idx = cell - 1
            if self.board[idx] != EMPTY:
                return False, f"格子 {cell} 已经有棋子了"

            self.board[idx] = mark
            self.last_move = idx
            self.updated_at = time.time()

            found = find_win(self.board, self.size, self.win_len)
            if found:
                self.over = True
                self.winner, self.win_cells = found
                self.result = "win" if self.winner == "X" else "lose"
                return True, self.result
            if EMPTY not in self.board:
                self.over = True
                self.result = "draw"
                return True, "draw"
            self.turn = "O" if mark == "X" else "X"
            return True, "ok"

    # ---------------------------------------------------------------- 再来一局
    def rematch_remaining(self) -> float:
        if self.rematch_deadline is None:
            return 0.0
        return max(0.0, self.rematch_deadline - time.time())

    def vote_rematch(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            if not self.over:
                return False, "这一局还没结束"
            if self.mark_of(user_id) is None:
                return False, "这盘棋不是你参与的"
            if self.rematch_deadline is None or time.time() > self.rematch_deadline:
                self.rematch_votes = set()
                self.rematch_deadline = time.time() + REMATCH_WINDOW_SECONDS
            self.rematch_votes.add(user_id)
            both = all(
                u in self.rematch_votes for u in (self.x_user, self.o_user) if u
            )
        if both:
            return True, "双方都确认了，开新局"
        other = self.o_user if user_id == self.x_user else self.x_user
        return False, f"等你和 {other} 都确认（还有 {int(self.rematch_remaining())} 秒）"

    def clear_rematch(self) -> None:
        with self._lock:
            self.rematch_votes = set()
            self.rematch_deadline = None

    def forfeit(self, loser_user: str) -> bool:
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
        """Agent 兜底落子：井字棋完全搜索，五子棋走启发式。"""
        with self._lock:
            if self.over or self.turn != "O":
                return None
            if self.kind == "gomoku":
                cell = best_gomoku_move(list(self.board), self.size, "O")
            else:
                cell = best_ttt_move(list(self.board), "O")
        if cell is None:
            return None
        ok, _ = self.move(cell, mark="O")
        return cell if ok else None


class GameService:
    """对局与战绩管理。一人同时只在一局里；观战不占名额。"""

    def __init__(self, users):
        self.users = users
        self._games: Dict[str, object] = {}
        self._by_user: Dict[str, str] = {}
        self._invites: Dict[str, dict] = {}
        self._scores: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 查询
    def get(self, game_id: str):
        with self._lock:
            return self._games.get(game_id)

    def current(self, user_id: str):
        with self._lock:
            gid = self._by_user.get(user_id)
            return self._games.get(gid) if gid else None

    def finished_for(self, user_id: str) -> List[object]:
        with self._lock:
            return [g for g in self._games.values()
                    if g.over and g.involves(user_id)]

    def ongoing(self) -> List[object]:
        with self._lock:
            return [g for g in self._games.values() if not g.over]

    # ---------------------------------------------------------------- 开局
    @staticmethod
    def _players_of(game) -> List[str]:
        """一局涉及的所有真人（21 点是一桌人）。"""
        if getattr(game, "kind", "ttt") == "bj":
            return [s.user for s in getattr(game, "seats", [])]
        return [p for p in (game.x_user, getattr(game, "o_user", None)) if p]

    def _register(self, game):
        with self._lock:
            self._games[game.id] = game
            for player in self._players_of(game):
                self._by_user[player] = game.id
        return game

    def start_vs_agent(self, user_id: str, room_id=None, kind: str = "ttt"):
        if kind == "bj":
            from server.services.blackjack import BlackjackGame
            return self._register(BlackjackGame(user_id, room_id))
        return self._register(Game(user_id, None, room_id, kind=kind))

    def invite(self, inviter: str, invitee: str, kind: str = "ttt") -> Tuple[bool, str]:
        if inviter == invitee:
            return False, "不能邀请自己"
        with self._lock:
            mine = self._games.get(self._by_user.get(inviter) or "")
            if kind == "bj":
                # 21 点：已经有牌桌就把人拉上桌，否则新开一张
                if mine is not None and not mine.over and getattr(mine, "kind", "") == "bj":
                    if len(getattr(mine, "seats", [])) >= 3:
                        return False, "这张桌已经坐满了（最多 3 人）"
                    table_id = mine.id
                else:
                    table_id = ""
            else:
                if mine is not None:
                    return False, "你已经有进行中的对局了"
                table_id = ""
            if self._by_user.get(invitee):
                return False, f"{invitee} 正在对局中"
            self._invites[invitee] = {
                "from": inviter, "ts": time.time(), "kind": kind, "table": table_id,
            }
        return True, f"已邀请 {invitee} 玩{game_name(kind)}，等对方回复（{INVITE_TTL_SECONDS} 秒内有效）"

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

    def accept(self, invitee: str) -> Tuple[bool, str, Optional[object]]:
        invite = self._take_invite(invitee)
        if invite is None:
            return False, "没有待接受的邀请（可能已过期）", None
        inviter = invite["from"]
        kind = invite.get("kind", "ttt")
        if kind == "bj":
            # 21 点：邀请人本来就在桌上，这里只检查被邀请人
            from server.services.blackjack import BlackjackGame
            if self._by_user.get(invitee):
                return False, "你已经在别的对局里了", None
            table = self.get(invite.get("table") or "")
            if table is not None and not table.over and getattr(table, "kind", "") == "bj":
                ok, detail = table.add_player(invitee)
                if not ok:
                    return False, detail, None
                with self._lock:
                    self._by_user[invitee] = table.id
                return True, detail, table
            game = BlackjackGame(inviter, None, seats=[inviter, invitee])
            return True, f"{inviter} 和 {invitee} 同桌开一局 21 点", self._register(game)
        with self._lock:
            if self._by_user.get(inviter) or self._by_user.get(invitee):
                return False, "有一方已经在别的对局里了", None
        game = Game(inviter, invitee, None, kind=kind)
        return True, f"{inviter} 和 {invitee} 开局（{game_name(kind)}），{inviter} 执 X 先手", self._register(game)

    def decline(self, invitee: str) -> Tuple[bool, Optional[str]]:
        invite = self._take_invite(invitee)
        if invite is None:
            return False, None
        return True, invite["from"]

    def remove_player(self, game, user_id: str) -> bool:
        """把一个人从 21 点牌桌摘掉；返回桌上还剩不剩人。"""
        if getattr(game, "kind", "") == "bj":
            game.seats = [seat for seat in game.seats if seat.user != user_id]
            game._normalise_turn()
        with self._lock:
            if self._by_user.get(user_id) == game.id:
                self._by_user.pop(user_id, None)
        return bool(getattr(game, "seats", [user_id]))

    def close(self, game) -> None:
        with self._lock:
            self._games.pop(game.id, None)
            for player in self._players_of(game):
                if player and self._by_user.get(player) == game.id:
                    self._by_user.pop(player, None)
        game.cancelled = True

    def rematch(self, game):
        """同一对玩家开新局：棋盘类交换先手，21 点换一副新牌。"""
        if getattr(game, "kind", "ttt") == "bj":
            from server.services.blackjack import BlackjackGame
            seats = [s.user for s in getattr(game, "seats", [])] or [game.x_user]
            return self._register(BlackjackGame(seats[0], game.room_id, seats=seats))
        new_game = Game(game.o_user, game.x_user, game.room_id, kind=game.kind)
        return self._register(new_game)

    def release(self, game) -> None:
        """结算后释放玩家名额：他们可以马上开新局，但棋局快照还留着给双方看结果。"""
        with self._lock:
            for player in self._players_of(game):
                if player and self._by_user.get(player) == game.id:
                    self._by_user.pop(player, None)

    def prune(self, max_age: float = 300.0) -> None:
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
    def record(self, game) -> None:
        kind = getattr(game, "kind", "ttt")
        if kind == "bj":
            with self._lock:
                for seat in getattr(game, "seats", []):
                    score = self._scores.setdefault(
                        f"bj:{seat.user}", {"win": 0, "lose": 0, "draw": 0})
                    if seat.result in score:
                        score[seat.result] += 1
            return
        with self._lock:
            for user, mark in ((game.x_user, "X"), (getattr(game, "o_user", None), "O")):
                if not user:
                    continue
                key = f"{kind}:{user}"
                score = self._scores.setdefault(key, {"win": 0, "lose": 0, "draw": 0})
                if game.result == "draw":
                    score["draw"] += 1
                elif getattr(game, "winner", None) == mark or (
                        kind == "bj" and game.result == "win" and mark == "X"):
                    score["win"] += 1
                else:
                    score["lose"] += 1

    def score(self, user_id: str, kind: str = "ttt") -> Dict[str, int]:
        with self._lock:
            return dict(self._scores.get(f"{kind}:{user_id}", {"win": 0, "lose": 0, "draw": 0}))

    def score_text(self, user_id: str, kind: str = "ttt") -> str:
        score = self.score(user_id, kind)
        return f"战绩：胜 {score['win']} / 负 {score['lose']} / 平 {score['draw']}"


# ---------------------------------------------------------------- Agent 工具
def game_tools(game, user_id: str):
    """把当前这盘棋绑进工具闭包：模型只能看到/操作这一盘。"""
    size = getattr(game, "size", 3)

    def game_get_board() -> str:
        players = game.players()
        extra = f"棋盘 {size}×{size}，{game.win_len} 连获胜。\n" if size > 3 else ""
        return (
            f"{extra}当前棋盘（数字是空位）：\n{game.render()}\n"
            f"可落子位置：{game.legal_moves()}\n"
            f"轮到：{game.turn}（X={players['X']}，O={players['O']}）"
        )

    def game_move(cell) -> str:
        try:
            cell = int(cell)
        except (TypeError, ValueError):
            return "[ToolError] cell 必须是整数，例如 game_move(cell=5)。"
        ok, msg = game.move(cell, mark="O")
        if not ok:
            return (f"[ToolError] {msg}。可落子位置：{game.legal_moves()[:40]}，"
                    f"请重新选择。")
        if game.over:
            return f"落子成功：O 下在 {cell}，本局结束（{game.status_line()}）。\n{game.render()}"
        return f"落子成功：O 下在 {cell}。\n{game.render()}"

    spec = [
        {
            "type": "function",
            "function": {
                "name": "game_get_board",
                "description": "读取当前棋盘、可落子位置和轮到谁。落子前可以调用一次确认局面。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "game_move",
                "description": (
                    f"在棋盘上落子。cell 是格子编号 1-{size * size}（从上到下、从左到右）。\n"
                    "你执 O，玩家执 X；每轮只能调用一次。"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cell": {"type": "integer", "description": f"1-{size * size} 的格子编号"},
                    },
                    "required": ["cell"],
                },
            },
        },
    ]
    return spec, {"game_get_board": game_get_board, "game_move": game_move}
