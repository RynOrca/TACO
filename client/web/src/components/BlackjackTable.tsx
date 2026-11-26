import type { BjCard, GameState } from '../types';

const isRed = (suit: string) => suit === '♥' || suit === '♦';

function Card({ card, faceDown, delay }: { card: BjCard | null; faceDown?: boolean; delay?: number }) {
  if (!card || faceDown) {
    return <span className="bj-card back" style={delay ? { animationDelay: `${delay}ms` } : undefined} />;
  }
  return (
    <span
      className={`bj-card${isRed(card.suit) ? ' red' : ''}`}
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
    >
      <span className="bj-corner">
        {card.rank}
        <br />
        {card.suit}
      </span>
      <span className="bj-pip">
        {card.rank}
        <small>{card.suit}</small>
      </span>
    </span>
  );
}

function resultText(game: GameState): string {
  if (game.result === 'draw') return '平局';
  return game.result === 'win' ? '你赢了' : '庄家赢';
}

/** 21 点牌桌：庄家一行、玩家一行，暗牌用牌背表示 */
export function BlackjackTable({ game, me }: { game: GameState; me: string | null }) {
  const view = game.bj;
  if (!view) return null;
  const isPlayer = Boolean(me) && game.players.X === me;
  const shownPlayerCards = view.player.length ? view.player : Array.from({ length: view.player_count }, () => null);

  return (
    <div className={`bj${game.over ? ' done' : ''}`}>
      <div className="bj-seat">
        <div className="bj-who">
          <span>DEALER</span>
          <b>Agent</b>
          <em>庄家</em>
        </div>
        <div className="bj-cards">
          {view.dealer.map((card, i) => (
            <Card key={i} card={card} faceDown={!card} delay={i * 90} />
          ))}
        </div>
        <div className="bj-total">
          {view.revealed ? view.dealer_score : `${view.dealer_score} + ?`}
        </div>
      </div>

      <div className="bj-pot">
        <span className="bj-chips">
          <i />
          <i />
          <i className="dark" />
        </span>
        <span>底注 {view.bet} 枚</span>
        <span>·</span>
        <span>牌堆剩 {view.deck_left} 张</span>
        <span>·</span>
        <span>第 {view.round} 局</span>
      </div>

      <div className="bj-seat mine">
        <div className="bj-who">
          <span>PLAYER</span>
          <b>{game.players.X}</b>
          <em>{isPlayer ? '你 · 闲家' : '闲家'}</em>
        </div>
        <div className="bj-cards">
          {shownPlayerCards.map((card, i) =>
            isPlayer ? (
              <Card key={i} card={card} delay={i * 90} />
            ) : (
              <span className="bj-card back" key={i} title="只能看到自己的牌" />
            ),
          )}
        </div>
        <div className="bj-total">{isPlayer ? view.player_score ?? 0 : `${view.player_count} 张`}</div>
      </div>

      {game.over && (
        <p className={`bj-result ${game.result}`}>
          {resultText(game)}
          <span className="dim">
            你 {view.player_score} · 庄家 {view.dealer_score}
          </span>
        </p>
      )}
    </div>
  );
}
