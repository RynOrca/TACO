"""21 点：玩家 vs Agent 庄家，按视角裁剪手牌。

为什么单独一个文件：
  棋类是"同一份棋盘给所有人看"，21 点相反——**暗牌不能下发**。
  所以这里的核心不是规则，而是 `view_for(viewer)`：每个连接只拿到
  自己该看到的那几张牌。玩家手牌永远不会出现在 Agent 的视图里。

视图约定
  player  自己的两张牌 + 庄家明牌（停牌后才揭示暗牌）
  Agent   自己的两张牌 + 玩家"要了几张牌"（不含点数与牌面）
  观战者  只有明牌与双方张数
"""

import random
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

SUITS = ("♠", "♥", "♦", "♣")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
EMPTY = " "
REMATCH_WINDOW_SECONDS = 10


def _card(rank: str, suit: str) -> dict:
    return {"rank": rank, "suit": suit}


def _value(card: dict) -> int:
    rank = card["rank"]
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_score(hand: List[dict]) -> int:
    total = sum(_value(c) for c in hand)
    aces = sum(1 for c in hand if c["rank"] == "A")
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


def hand_text(hand: List[dict]) -> str:
    return " ".join(f"{c['rank']}{c['suit']}" for c in hand)


class BlackjackGame:
    """一盘 21 点。x_user 是玩家，庄家固定是 Agent。"""

    kind = "bj"

    def __init__(self, x_user: str, room_id: Optional[int] = None,
                 game_id: Optional[str] = None, o_user: Optional[str] = None):
        self.id = game_id or uuid.uuid4().hex[:8]
        self.kind = "bj"
        self.x_user = x_user
        self.o_user = None            # 庄家是 Agent，没有第二个真人
        self.room_id = room_id
        self.cancelled = False
        self.created_at = time.time()
        self.updated_at = time.time()
        self.rematch_votes: set = set()
        self.rematch_deadline: Optional[float] = None
        self._lock = threading.Lock()

        self.deck: List[dict] = []
        self.player: List[dict] = []
        self.dealer: List[dict] = []
        self.over = False
        self.revealed = False         # 庄家暗牌是否已亮
        self.result = ""              # win / lose / draw（相对玩家）
        self.winner: Optional[str] = None
        self.bet = 2
        self.round = 0
        self._deal()

    # ---------------------------------------------------------------- 基本信息
    def _deal(self) -> None:
        self.deck = [_card(r, s) for s in SUITS for r in RANKS]
        random.SystemRandom().shuffle(self.deck)
        self.player = [self.deck.pop(), self.deck.pop()]
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.over = False
        self.revealed = False
        self.result = ""
        self.winner = None
        self.round += 1
        self.updated_at = time.time()

    @property
    def vs_agent(self) -> bool:
        return True

    def players(self) -> Dict[str, Optional[str]]:
        return {"X": self.x_user, "O": "Agent"}

    def mark_of(self, user_id: Optional[str]) -> Optional[str]:
        return "X" if user_id and user_id == self.x_user else None

    def involves(self, user_id: str) -> bool:
        return user_id == self.x_user

    def legal_moves(self) -> List[int]:
        return []

    def render(self) -> str:
        """给命令行/日志用的文本（玩家视角）。"""
        dealer = f"{self.dealer[0]['rank']}{self.dealer[0]['suit']} ?" if not self.revealed \
            else hand_text(self.dealer)
        return f"庄家：{dealer}（{hand_score(self.dealer)}）\n你：{hand_text(self.player)}（{hand_score(self.player)}）"

    def status_line(self) -> str:
        if self.over:
            if self.result == "draw":
                return "平局"
            return "你赢了" if self.result == "win" else "庄家赢"
        return f"轮到你决策（{hand_score(self.player)} 点）"

    # ---------------------------------------------------------------- 视角裁剪
    def _public_dealer(self, reveal: bool) -> List[Optional[dict]]:
        if reveal or self.revealed:
            return list(self.dealer)
        return [self.dealer[0], None]

    def view_for(self, viewer: Optional[str]) -> dict:
        """每个连接只拿到自己该看的那部分。暗牌在这里就是 None，不发原牌。"""
        is_player = viewer == self.x_user
        reveal = self.revealed or self.over
        dealer_cards = self._public_dealer(reveal)

        if is_player:
            hand = list(self.player)
        elif viewer == "Agent":
            # 庄家（Agent）只能看到自己的牌 + 玩家要牌张数，看不到玩家的牌面
            hand = []
        else:
            hand = []

        return {
            "type": "game",
            "action": "state",
            "game_id": self.id,
            "kind": "bj",
            "players": self.players(),
            "vs_agent": True,
            "turn": "X",
            "over": self.over,
            "result": self.result,
            "winner": self.winner,
            "rematch": {
                "votes": sorted(self.rematch_votes),
                "deadline": int(self.rematch_deadline * 1000) if self.rematch_deadline else 0,
                "window": REMATCH_WINDOW_SECONDS,
            },
            "spectators": 0,
            "scores": {},
            "bj": {
                "player": hand,
                "player_count": len(self.player),
                "player_score": hand_score(self.player) if is_player else None,
                "dealer": dealer_cards,
                "dealer_score": hand_score(self.dealer) if reveal else _value(self.dealer[0]),
                "revealed": reveal,
                "bet": self.bet,
                "deck_left": len(self.deck),
                "round": self.round,
            },
        }

    def snapshot(self) -> dict:
        return self.view_for("Agent")

    # ---------------------------------------------------------------- 操作
    def hit(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            if user_id != self.x_user:
                return False, "这不是你的牌桌"
            if self.over:
                return False, "这一局已经结束"
            self.player.append(self.deck.pop())
            self.updated_at = time.time()
            if hand_score(self.player) > 21:
                self._settle("bust")
                return True, "bust"
            return True, "ok"

    def stand(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            if user_id != self.x_user:
                return False, "这不是你的牌桌"
            if self.over:
                return False, "这一局已经结束"
            while hand_score(self.dealer) < 17:
                self.dealer.append(self.deck.pop())
            self._settle("stand")
            return True, "stand"

    def _settle(self, why: str) -> None:
        self.over = True
        self.revealed = True
        self.updated_at = time.time()
        player, dealer = hand_score(self.player), hand_score(self.dealer)
        if player > 21:
            self.result, self.winner = "lose", "O"
        elif dealer > 21 or player > dealer:
            self.result, self.winner = "win", "X"
        elif player == dealer:
            self.result, self.winner = "draw", None
        else:
            self.result, self.winner = "lose", "O"

    # ---------------------------------------------------------------- 再来一局
    def rematch_remaining(self) -> float:
        if self.rematch_deadline is None:
            return 0.0
        return max(0.0, self.rematch_deadline - time.time())

    def vote_rematch(self, user_id: str) -> Tuple[bool, str]:
        """21 点对手是 Agent，确认一次就算数（不用等第二个人）。"""
        with self._lock:
            if not self.over:
                return False, "这一局还没结束"
            if user_id != self.x_user:
                return False, "这不是你的牌桌"
        return True, "开新一局"

    def clear_rematch(self) -> None:
        with self._lock:
            self.rematch_votes = set()
            self.rematch_deadline = None

    def forfeit(self, loser_user: str) -> bool:
        with self._lock:
            if self.over or loser_user != self.x_user:
                return False
            self.over = True
            self.revealed = True
            self.result, self.winner = "lose", "O"
            self.updated_at = time.time()
            return True

    def auto_move(self) -> Optional[int]:
        return None          # 庄家按规则补牌，不需要"落子"


# ---------------------------------------------------------------- Agent 工具（可选）
def blackjack_tools(game: BlackjackGame, user_id: str):
    """庄家的工具：只能读自己的牌与玩家张数，读不到玩家牌面。"""

    def bj_my_hand() -> str:
        return (f"你的手牌：{hand_text(game.dealer)}（{hand_score(game.dealer)} 点）\n"
                f"这张桌只告诉你玩家已经要了 {len(game.player)} 张牌，看不到牌面。")

    spec = [
        {
            "type": "function",
            "function": {
                "name": "bj_my_hand",
                "description": "读取庄家自己的手牌点数。你无法看到玩家手牌。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    return spec, {"bj_my_hand": bj_my_hand}
