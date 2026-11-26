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
  return game.result === 'win' ? '你赢了' : '你输了';
}

const STATUS_CN: Record<string, string> = {
  playing: '待行动',
  stand: '已停牌',
  bust: '爆牌',
};

/** 21 点牌桌：最多 3 个真人同桌，别人的牌只显示张数 */
export function BlackjackTable({ game, me }: { game: GameState; me: string | null }) {
  const view = game.bj;
  if (!view) return null;
  const seats = view.seats ?? [];
  const mine = seats.find((s) => s.user === me);
  const isPlayer = Boolean(mine);

  return (
    <div className={`bj${game.over ? ' done' : ''}`}>
      <div className="bj-seat dealer">
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
        <span>·</span>
        <span>{seats.length} 人同桌</span>
      </div>

      {seats.map((seat) => {
        const active = view.current === seat.user && !game.over;
        const own = seat.user === me;
        const cards = own && seat.hand
          ? seat.hand.map((c, i) => <Card key={i} card={c} delay={i * 90} />)
          : Array.from({ length: seat.count }, (_, i) => (
              <span className="bj-card back" key={i} title="只有本人能看到自己的牌" />
            ));
        return (
          <div className={`bj-seat mine${active ? ' active' : ''}${own ? ' own' : ''}`} key={seat.user}>
            <div className="bj-who">
              <span>PLAYER</span>
              <b>{seat.user}</b>
              <em>{own ? '你 · 闲家' : '闲家'}</em>
            </div>
            <div className="bj-cards">{cards}</div>
            <div className="bj-total">
              {own && seat.score !== null ? seat.score : `${seat.count} 张`}
            </div>
            <span className={`bj-status ${seat.status}${seat.result ? ` ${seat.result}` : ''}`}>
              {seat.result
                ? seat.result === 'win'
                  ? '赢'
                  : seat.result === 'draw'
                    ? '平'
                    : '输'
                : STATUS_CN[seat.status] ?? ''}
            </span>
          </div>
        );
      })}

      {!isPlayer && !game.over && (
        <p className="bj-note">你在观战：只能看到庄家明牌和各家的张数。</p>
      )}

      {game.over && (
        <p className={`bj-result ${game.result}`}>
          {isPlayer ? resultText(game) : '本局结束'}
          <span className="dim">
            {isPlayer && mine?.score !== null && `你 ${mine?.score} · `}
            庄家 {view.dealer_score}
          </span>
        </p>
      )}
    </div>
  );
}
