"""井字棋：服务端权威棋盘 + Agent 用工具落子。

为什么状态不放在模型里：
  - 模型会"忘记"棋盘、前后矛盾，答辩时说不清谁在维护状态；
  - 放在服务端后，非法着法、抢跑、重复落子都能被拒绝，Agent 只能通过
    game_move 工具改棋盘，界面上每次落子也都会留下一条真实工具调用记录。

玩家固定执 X 先手，Agent 执 O。模型不可用时用本地 minimax 自动代打，
保证聊天室里这局棋不会因为 LLM 挂了而卡住。
"""

import threading
from typing import Dict, List, Optional, Tuple

EMPTY = " "
WIN_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)
RESULT_CN = {"win": "你赢了", "lose": "Agent 赢了", "draw": "平局"}


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
    """返回 0-based 最优格子；空格优先中心/角，避免同分时下得难看。"""
    order = [4, 0, 2, 6, 8, 1, 3, 5, 7]
    best, best_score = None, None
    for i in order:
        if board[i] != EMPTY:
            continue
        board[i] = mark
        score = _minimax(board, "X" if mark == "O" else "O")
        board[i] = EMPTY
        if best_score is None or (mark == "O" and score > best_score) \
                or (mark == "X" and score < best_score):
            best, best_score = i, score
    return best


class Game:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.board: List[str] = [EMPTY] * 9
        self.turn = "X"            # 玩家先手
        self.over = False
        self.result = ""           # win / lose / draw
        self.cancelled = False
        self._lock = threading.Lock()

    def legal_moves(self) -> List[int]:
        return [i + 1 for i, c in enumerate(self.board) if c == EMPTY]

    def render(self) -> str:
        return render_board(self.board)

    def move(self, cell: int, mark: str) -> Tuple[bool, str]:
        """落子并判定胜负。返回 (是否成功, 说明/结果)。"""
        with self._lock:
            if self.over:
                return False, "这盘已经结束了"
            if self.turn != mark:
                return False, "还没轮到这一方"
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
            if _winner_of(self.board) == mark:
                self.over = True
                self.result = "win" if mark == "X" else "lose"
                return True, self.result
            if EMPTY not in self.board:
                self.over = True
                self.result = "draw"
                return True, "draw"
            self.turn = "O" if mark == "X" else "X"
            return True, "ok"

    def auto_move(self) -> Optional[int]:
        """本地兜底：模型没给出合法落子时，用 minimax 替 Agent 走一步。"""
        if self.over or self.turn != "O":
            return None
        with self._lock:
            snapshot = list(self.board)
        idx = best_move(snapshot, "O")
        if idx is None:
            return None
        cell = idx + 1
        ok, _ = self.move(cell, "O")
        return cell if ok else None


class GameService:
    """每个用户一盘棋，互不影响；战绩存在内存里，进程重启清空。"""

    def __init__(self, users):
        self.users = users
        self._games: Dict[str, Game] = {}
        self._scores: Dict[str, Dict[str, int]] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str) -> Optional[Game]:
        with self._lock:
            return self._games.get(user_id)

    def start(self, user_id: str) -> Game:
        game = Game(user_id)
        with self._lock:
            self._games[user_id] = game
        return game

    def drop(self, user_id: str) -> Optional[Game]:
        with self._lock:
            game = self._games.pop(user_id, None)
        if game is not None:
            game.cancelled = True
        return game

    def record(self, game: Game) -> None:
        with self._lock:
            score = self._scores.setdefault(game.user_id, {"win": 0, "lose": 0, "draw": 0})
            if game.result in score:
                score[game.result] += 1

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
        return (
            f"当前棋盘（数字是空位）：\n{game.render()}\n"
            f"可落子位置：{game.legal_moves()}\n"
            f"轮到：{game.turn}（X=玩家 {user_id}，O=你）"
        )

    def game_move(cell) -> str:
        try:
            cell = int(cell)
        except (TypeError, ValueError):
            return "[ToolError] cell 必须是 1-9 的整数，例如 game_move(cell=5)。"
        ok, msg = game.move(cell, "O")
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
