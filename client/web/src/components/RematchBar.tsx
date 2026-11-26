import { useEffect, useState } from 'react';
import type { GameState } from '../types';

/** 结束后的操作区：人对 Agent 直接重开；人对人要双方在 10 秒内都确认。 */
export function RematchBar({
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
  // 每 0.5 秒重算一次，倒计时才会走
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
          <span className="dim">
            10 秒内双方都点「再来一局」才继续；有人点退出则这局对双方都结束
          </span>
        )}
        {left > 0 && !both && (
          <span className="rematch-bar">
            <i style={{ width: `${Math.min(100, (left / (game.rematch?.window || 10)) * 100)}%` }} />
          </span>
        )}
      </div>
      <div className="rematch-actions">
        <button type="button" className="btn primary" onClick={onRematch} disabled={both}>
          {voted ? '已确认，等待对方' : '再来一局'}
        </button>
        <button
          type="button"
          className="btn"
          onClick={onQuit}
          title="你把这一局关掉，对方也会一起结束"
        >
          退出
        </button>
      </div>
    </div>
  );
}
