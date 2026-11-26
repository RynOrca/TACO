import type { GameInvite, GameState } from '../types';
import { involvesMe, isPlayerOf, statusText } from './GameBoard';

interface Props {
  /** 自己参与的对局（没有就是 null） */
  mine: GameState | null;
  /** 侧栏当前显示的那盘（可能是别人的，用于观战） */
  focused: GameState | null;
  /** 所有进行中的对局，供观战切换 */
  ongoing: GameState[];
  invite: GameInvite | null;
  me: string | null;
  onFocus: (id: string) => void;
  onAccept: () => void;
  onDecline: () => void;
  /** 进入专注模式看棋盘 */
  onEnter: (id: string) => void;
}

const KIND_NAME: Record<string, string> = {
  ttt: '井字棋',
  gomoku: '五子棋',
  bj: '21 点',
};

function countsDown(invite: GameInvite): number {
  const left = invite.ttl * 1000 - (Date.now() - invite.at);
  return Math.max(0, Math.ceil(left / 1000));
}

/** 侧栏里的"对局入口"：只放摘要和按钮，棋盘留给专注模式 */
export function GamePanel({
  mine,
  focused,
  ongoing,
  invite,
  me,
  onFocus,
  onAccept,
  onDecline,
  onEnter,
}: Props) {
  const game = mine ?? focused;

  const inviteCard = invite && countsDown(invite) > 0 && (
    <div className="game-invite">
      <p>
        <b>{invite.from}</b> 邀请你玩{KIND_NAME[invite.kind ?? 'ttt'] ?? '井字棋'}（{countsDown(invite)}s）
      </p>
      <div className="game-invite-btns">
        <button type="button" className="btn primary" onClick={onAccept}>
          接受
        </button>
        <button type="button" className="btn" onClick={onDecline}>
          拒绝
        </button>
      </div>
    </div>
  );

  if (!game) {
    return (
      <section className="game">
        <h2>当前对局</h2>
        {inviteCard}
        <p className="panel-empty">还没有进行中的对局，在下面开一局或邀请别人。</p>
      </section>
    );
  }

  const isPlayer = isPlayerOf(game, me);
  const opponent = game.kind === 'bj'
    ? `${game.bj?.seats.length ?? 1} 人同桌 · 庄家 Agent`
    : `对手 ${game.players.O === 'Agent' ? 'Agent' : game.players.O}`;

  return (
    <section className="game">
      <h2>
        当前对局
        {!isPlayer && <span className="tag soft">(观战)</span>}
      </h2>

      <div className={`game-card${game.over ? ' over' : ''}`}>
        <div className="game-card-top">
          <b>{KIND_NAME[game.kind] ?? '棋局'}</b>
          <em>{opponent}</em>
        </div>
        <p className={`game-card-state${game.over ? ' done' : ''}`}>
          {statusText(game, me)}
          {!isPlayer && <span className="game-spectate">只读</span>}
        </p>
        <button type="button" className="btn primary game-card-enter" onClick={() => onEnter(game.id)}>
          {game.over ? '查看结果' : '进入牌桌'}
        </button>
      </div>

      {inviteCard}

      {ongoing.length > 1 && (
        <div className="game-list">
          <p className="game-list-title">进行中 {ongoing.length} 盘</p>
          {ongoing.map((item) => (
            <button
              type="button"
              key={item.id}
              className={`game-list-item${item.id === game.id ? ' on' : ''}`}
              onClick={() => onFocus(item.id)}
            >
              <span>
                {KIND_NAME[item.kind] ?? '棋局'} · {item.players.X} vs {item.players.O}
              </span>
              <em>{item.turn === 'X' ? item.players.X : item.players.O} 落子</em>
            </button>
          ))}
        </div>
      )}

      {!involvesMe(game, me) && <p className="auto-hint">你正在观战，点「进入牌桌」看完整棋盘。</p>}
    </section>
  );
}
