"""21 点：最多 3 个真人同桌，庄家是 Agent，按视角裁剪手牌。

为什么单独一个文件：
  棋类是"同一份棋盘给所有人看"，21 点相反——**每张牌只能给它的主人看**。
  所以这里的核心不是规则，而是 `view_for(viewer)`：每个连接只拿到自己该看到的
  那几张牌。别人的手牌在 JSON 里就是张数，连牌面都不存在。

视图约定
  自己     自己的牌 + 其他人的张数 + 庄家明牌（停牌后揭示暗牌）
  Agent    庄家的牌 + 每个座位的张数（拿不到任何人的牌面）
  观战者   所有座位的张数 + 庄家明牌
"""

import random
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

SUITS = ("♠", "♥", "♦", "♣")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
REMATCH_WINDOW_SECONDS = 10
MAX_SEATS = 3
DEALER_STAND = 17


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


class Seat:
    """一个真人座位。status: playing / stand / bust。"""

    def __init__(self, user: str, bet: int = 2):
        self.user = user
        self.hand: List[dict] = []
        self.status = "playing"
        self.result = ""       # win / lose / draw
        self.bet = bet

    @property
    def score(self) -> int:
        return hand_score(self.hand)

    def public(self) -> dict:
        return {
            "user": self.user,
            "count": len(self.hand),
            "status": self.status,
            "result": self.result,
            "score": None,          # 牌面分值不外泄，只有主人自己能算
            "bet": self.bet,
        }


class BlackjackGame:
    """一张 21 点牌桌。x_user 是第一个座位，庄家固定是 Agent。"""

    kind = "bj"

    def __init__(self, x_user: str, room_id: Optional[int] = None,
                 game_id: Optional[str] = None, o_user: Optional[str] = None,
                 seats: Optional[List[str]] = None):
        self.id = game_id or uuid.uuid4().hex[:8]
        self.kind = "bj"
        self.room_id = room_id
        self.cancelled = False
        self.created_at = time.time()
        self.updated_at = time.time()
        self.rematch_votes: set = set()
        self.rematch_deadline: Optional[float] = None
        self._lock = threading.Lock()

        users = seats or [x_user]
        self.seats: List[Seat] = [Seat(u) for u in users[:MAX_SEATS]]
        self.deck: List[dict] = []
        self.dealer: List[dict] = []
        self.over = False
        self.revealed = False
        self.round = 0
        self.current = 0
        self._deal()

    # GameService 用到的两个属性
    @property
    def x_user(self) -> str:
        return self.seats[0].user

    @property
    def o_user(self) -> Optional[str]:
        return None

    @property
    def vs_agent(self) -> bool:
        return True

    # ---------------------------------------------------------------- 座位
    def seat_of(self, user_id: Optional[str]) -> Optional[Seat]:
        return next((s for s in self.seats if s.user == user_id), None)

    def players(self) -> Dict[str, Optional[str]]:
        return {"X": self.seats[0].user, "O": "Agent"}

    def involves(self, user_id: str) -> bool:
        return self.seat_of(user_id) is not None

    def mark_of(self, user_id: Optional[str]) -> Optional[str]:
        return "X" if self.seat_of(user_id) else None

    def add_player(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            if self.over:
                return False, "这一局已经结束了"
            if self.seat_of(user_id):
                return True, "你已经在桌上了"
            if len(self.seats) >= MAX_SEATS:
                return False, f"这张桌最多 {MAX_SEATS} 个人"
            seat = Seat(user_id)
            seat.hand = [self.deck.pop(), self.deck.pop()]
            self.seats.append(seat)
            self.updated_at = time.time()
            return True, f"{user_id} 加入了牌桌"

    # ---------------------------------------------------------------- 发牌
    def _deal(self) -> None:
        self.deck = [_card(r, s) for s in SUITS for r in RANKS]
        random.SystemRandom().shuffle(self.deck)
        for seat in self.seats:
            seat.hand = [self.deck.pop(), self.deck.pop()]
            seat.status = "playing"
            seat.result = ""
        self.dealer = [self.deck.pop(), self.deck.pop()]
        self.over = False
        self.revealed = False
        self.round += 1
        self.current = 0
        self._normalise_turn()

    def _normalise_turn(self) -> None:
        """跳过已经停牌/爆牌的座位；全部处理完就进庄家回合。"""
        n = len(self.seats)
        for step in range(n):
            idx = (self.current + step) % n
            if self.seats[idx].status == "playing":
                self.current = idx
                return
        self._dealer_turn()

    def _dealer_turn(self) -> None:
        while hand_score(self.dealer) < DEALER_STAND:
            self.dealer.append(self.deck.pop())
        self.over = True
        self.revealed = True
        dscore = hand_score(self.dealer)
        for seat in self.seats:
            score = seat.score
            if score > 21:
                seat.result = "lose"
            elif dscore > 21 or score > dscore:
                seat.result = "win"
            elif score == dscore:
                seat.result = "draw"
            else:
                seat.result = "lose"
        self.updated_at = time.time()

    # ---------------------------------------------------------------- 视图
    def _public_dealer(self) -> List[Optional[dict]]:
        if self.revealed:
            return list(self.dealer)
        return [self.dealer[0], None]

    def view_for(self, viewer: Optional[str]) -> dict:
        mine = self.seat_of(viewer)
        reveal = self.revealed
        return {
            "type": "game",
            "action": "state",
            "game_id": self.id,
            "kind": "bj",
            "players": self.players(),
            "vs_agent": True,
            "turn": "X",
            "over": self.over,
            "result": mine.result if mine else "",
            "winner": ("X" if mine and mine.result == "win" else None),
            "rematch": {
                "votes": sorted(self.rematch_votes),
                "deadline": int(self.rematch_deadline * 1000) if self.rematch_deadline else 0,
                "window": REMATCH_WINDOW_SECONDS,
            },
            "spectators": 0,
            "scores": {},
            "bj": {
                "seats": [
                    {
                        **seat.public(),
                        # 只有本座位的连接能拿到自己的牌面
                        "hand": list(seat.hand) if seat is mine else None,
                        "score": seat.score if seat is mine else None,
                    }
                    for seat in self.seats
                ],
                "me": mine.user if mine else None,
                "dealer": self._public_dealer(),
                "dealer_score": hand_score(self.dealer) if reveal else _value(self.dealer[0]),
                "revealed": reveal,
                "bet": self.seats[0].bet,
                "deck_left": len(self.deck),
                "round": self.round,
                "current": self.seats[self.current].user if not self.over else None,
            },
        }

    def snapshot(self) -> dict:
        return self.view_for("Agent")

    # ---------------------------------------------------------------- 文本
    def render(self) -> str:
        dealer = f"{self.dealer[0]['rank']}{self.dealer[0]['suit']} ?" if not self.revealed \
            else hand_text(self.dealer)
        lines = [f"庄家：{dealer}（{hand_score(self.dealer)}）"]
        for seat in self.seats:
            lines.append(f"{seat.user}：{hand_text(seat.hand)}（{seat.score}）{seat.status}")
        return "\n".join(lines)

    def status_line(self) -> str:
        if self.over:
            return "、".join(f"{s.user} {s.result or '-'}" for s in self.seats)
        seat = self.seats[self.current]
        return f"轮到 {seat.user} 决策"

    def legal_moves(self) -> List[int]:
        return []

    # ---------------------------------------------------------------- 操作
    def _require_turn(self, user_id: str) -> Tuple[Optional[Seat], str]:
        seat = self.seat_of(user_id)
        if seat is None:
            return None, "你不在这张牌桌上"
        if self.over:
            return None, "这一局已经结束"
        if self.seats[self.current] is not seat:
            return None, f"现在轮到 {self.seats[self.current].user}"
        return seat, ""

    def hit(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            seat, why = self._require_turn(user_id)
            if seat is None:
                return False, why
            seat.hand.append(self.deck.pop())
            self.updated_at = time.time()
            if seat.score > 21:
                seat.status = "bust"
                self.current += 1
                self._normalise_turn()
                return True, "bust"
            return True, "ok"

    def stand(self, user_id: str) -> Tuple[bool, str]:
        with self._lock:
            seat, why = self._require_turn(user_id)
            if seat is None:
                return False, why
            seat.status = "stand"
            self.current += 1
            self._normalise_turn()
            return True, "stand"

    def forfeit(self, loser_user: str) -> bool:
        with self._lock:
            seat = self.seat_of(loser_user)
            if seat is None or self.over:
                return False
            seat.status = "stand"
            seat.result = "lose"
            if all(s.status != "playing" for s in self.seats):
                self._dealer_turn()
            return True

    def auto_move(self) -> Optional[int]:
        return None

    # ---------------------------------------------------------------- 再来一局
    def rematch_remaining(self) -> float:
        if self.rematch_deadline is None:
            return 0.0
        return max(0.0, self.rematch_deadline - time.time())

    def vote_rematch(self, user_id: str) -> Tuple[bool, str]:
        """同桌的人都要确认；庄家是 Agent 不用投票。"""
        with self._lock:
            if not self.over:
                return False, "这一局还没结束"
            if not self.seat_of(user_id):
                return False, "你不在这张牌桌上"
            if self.rematch_deadline is None or time.time() > self.rematch_deadline:
                self.rematch_votes = set()
                self.rematch_deadline = time.time() + REMATCH_WINDOW_SECONDS
            self.rematch_votes.add(user_id)
            both = all(s.user in self.rematch_votes for s in self.seats)
        if both:
            return True, "同桌都确认了，开新一局"
        return False, f"等其他人也确认（还有 {int(self.rematch_remaining())} 秒）"

    def clear_rematch(self) -> None:
        with self._lock:
            self.rematch_votes = set()
            self.rematch_deadline = None


# ---------------------------------------------------------------- Agent 工具
def blackjack_tools(game: BlackjackGame, user_id: str):
    """庄家的工具：只能读自己的牌与各座位张数，读不到任何人的牌面。"""

    def bj_my_hand() -> str:
        return (f"你的手牌：{hand_text(game.dealer)}（{hand_score(game.dealer)} 点）\n"
                f"桌上座位：" + "、".join(f"{s.user}（{s.status}，{len(s.hand)} 张）" for s in game.seats) +
                "\n你只能看到张数与状态，看不到任何人的牌面。")

    spec = [
        {
            "type": "function",
            "function": {
                "name": "bj_my_hand",
                "description": "读取庄家自己的手牌点数与各座位的张数。你看不到玩家的牌面。",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    return spec, {"bj_my_hand": bj_my_hand}
