import { useEffect, useState } from 'react';
import type { GameInvite, GameState } from '../types';

interface Props {
  /** 自己参与的对局（没有就是 null） */
  mine: GameState | null;
  /** 侧栏当前显示的那盘（可能是别人的，用于观战） */
  focused: GameState | null;
  /** 所有进行中的对局，供观战切换 */
  ongoing: GameState[];
  invite: GameInvite | null;
  me: string | null;
  onMove: (cell: number) => void;
  onStart: () => void;
  onQuit: () => void;
  onFocus: (id: string) => void;
  onAccept: () => void;
  onDecline: () => void;
  onRematch: () => void;
}

function resultText(game: GameState): string {
  if (game.result === 'draw') return '平局';
  if (game.winner) return `${game.players[game.winner]} 获胜`;
  return '本局结束';
}

function countsDown(invite: GameInvite): number {
  const left = invite.ttl * 1000 - (Date.now() - invite.at);
  return Math.max(0, Math.ceil(left / 1000));
}

export function GamePanel({
  mine,
  focused,
  ongoing,
  invite,
  me,
  onMove,
  onStart,
  onQuit,
  onFocus,
  onAccept,
  onDecline,
  onRematch,
}: Props) {
  const game = mine ?? focused;

  // 空状态：没有对局，也没有邀请
  if (!game) {
    return (
      <section className="game">
        <h2>井字棋</h2>
        {invite && countsDown(invite) > 0 && (
          <div className="game-invite">
            <p>
              <b>{invite.from}</b> 邀请你对弈（{countsDown(invite)}s）
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
        )}
        <p className="panel-empty">
          和 Agent 下一局，或 <code>/game invite 用户名</code> 找人对弈；别人下棋时这里会显示观战棋盘。
        </p>
        <button type="button" className="btn primary" onClick={onStart}>
          和 Agent 开局
        </button>
      </section>
    );
  }

  const isPlayer = Boolean(me) && (game.players.X === me || game.players.O === me);
  const myMark = me === game.players.X ? 'X' : me === game.players.O ? 'O' : null;
  const myTurn = isPlayer && !game.over && game.turn === myMark;
  const score = myMark ? game.scores[me ?? ''] : undefined;

  const stateText = game.over
    ? resultText(game)
    : myTurn
      ? `轮到你（${myMark}）`
      : isPlayer
        ? `等待 ${game.players[game.turn]} 落子`
        : `观战中 · 轮到 ${game.players[game.turn]}`;

  return (
    <section className="game">
      <h2>
        <span className="game-title">
          井字棋
          <em>
            {game.players.X} vs {game.players.O}
            {game.spectators > 0 ? ` · ${game.spectators} 人观战` : ''}
          </em>
        </span>
        {isPlayer && (
          <button type="button" className="link" onClick={onQuit}>
            {game.over ? '关闭' : '认输'}
          </button>
        )}
      </h2>

      {invite && countsDown(invite) > 0 && (
        <div className="game-invite">
          <p>
            <b>{invite.from}</b> 邀请你对弈（{countsDown(invite)}s）
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
      )}

      <p
        className={`game-state${game.over ? ' done' : myTurn ? ' mine' : ' wait'}`}
        title={isPlayer ? `你执 ${myMark}` : '观战'}
      >
        {stateText}
        {!isPlayer && <span className="game-spectate">只读</span>}
      </p>

      <div className="game-board" role="grid" aria-label="井字棋棋盘">
        {game.board.map((cell, i) => {
          const taken = cell !== ' ';
          const playable = myTurn && !taken;
          return (
            <button
              key={i}
              type="button"
              role="gridcell"
              className={`game-cell${cell === 'X' ? ' x' : cell === 'O' ? ' o' : ''}${
                !isPlayer ? ' spectate' : ''
              }`}
              disabled={!playable}
              onClick={() => onMove(i + 1)}
              aria-label={taken ? `第 ${i + 1} 格 ${cell}` : `第 ${i + 1} 格，可落子`}
            >
              {taken ? cell : i + 1}
            </button>
          );
        })}
      </div>

      {score && (
        <p className="game-score">
          战绩 {score.win} 胜 / {score.lose} 负 / {score.draw} 平
        </p>
      )}

      {game.over && isPlayer && <RematchBar game={game} me={me} onRematch={onRematch} onQuit={onQuit} />}

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
                {item.players.X} vs {item.players.O}
              </span>
              <em>{item.turn === 'X' ? item.players.X : item.players.O} 落子</em>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

/** 结束后的操作区：人对 Agent 直接重开；人对人要双方在 10 秒内都确认。 */
function RematchBar({
  game,
  me,
  onRematch,
  onQuit,
}: {
  game: GameState;
  me: string | null;
  onRematch: () => void;
  onQuit: () => void;
}) {
  // 每秒重算一次剩余时间，倒计时才会走
  const [, tick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => tick((n) => n + 1), 500);
    return () => window.clearInterval(timer);
  }, []);

  if (game.vs_agent) {
    return (
      <div className="rematch">
        <button type="button" className="btn primary" onClick={onRematch}>
          再来一局
        </button>
        <button type="button" className="btn" onClick={onQuit}>
          关闭
        </button>
      </div>
    );
  }

  const votes = game.rematch?.votes ?? [];
  const both = Boolean(
    game.players.X && votes.includes(game.players.X) &&
    game.players.O && votes.includes(game.players.O),
  );
  const voted = Boolean(me && votes.includes(me));
  const left = game.rematch?.deadline
    ? Math.max(0, Math.ceil((game.rematch.deadline - Date.now()) / 1000))
    : 0;
  const other = me === game.players.X ? game.players.O : game.players.X;
  const otherVoted = Boolean(other && votes.includes(other));

  return (
    <div className="rematch">
      <div className="rematch-state">
        {both ? (
          <span className="ok">双方都确认了，正在开新局…</span>
        ) : voted ? (
          <span>
            已确认 · 等 {other}
            {otherVoted ? '' : `（还要 ${left}s）`}
          </span>
        ) : left > 0 ? (
          <span>
            {otherVoted ? `${other} 想再来一局 · ` : ''}
            还剩 <b>{left}s</b>，两个人都确认才会开新局
          </span>
        ) : (
          <span className="dim">10 秒内双方都点「再来一局」才继续；有人点退出则这局对双方都结束</span>
        )}
        {left > 0 && !both && (
          <span className="rematch-bar">
            <i style={{ width: `${Math.min(100, (left / (game.rematch?.window || 10)) * 100)}%` }} />
          </span>
        )}
      </div>
      <div className="rematch-actions">
        <button
          type="button"
          className="btn primary"
          onClick={onRematch}
          disabled={both}
        >
          {voted ? '已确认，等待对方' : '再来一局'}
        </button>
        <button type="button" className="btn" onClick={onQuit} title="你把这一局关掉，对方也会一起结束">
          退出
        </button>
      </div>
    </div>
  );
}
