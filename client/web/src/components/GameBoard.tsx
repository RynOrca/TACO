import type { GameState } from '../types';
import { BlackjackTable } from './BlackjackTable';
import { GomokuBoard } from './GomokuBoard';

export function resultText(game: GameState): string {
  if (game.kind === 'bj') {
    if (game.result === 'draw') return '平局';
    return game.result === 'win' ? '你赢了' : '庄家赢';
  }
  if (game.result === 'draw') return '平局';
  if (game.winner) return `${game.players[game.winner]} 获胜`;
  return '本局结束';
}

export function isPlayerOf(game: GameState, me: string | null): boolean {
  return Boolean(me) && (game.players.X === me || game.players.O === me);
}

export function myTurnOf(game: GameState, me: string | null): boolean {
  if (!me || game.over) return false;
  if (game.kind === 'bj') return game.players.X === me;      // 21 点：玩家决策，庄家按规则补牌
  const myMark = me === game.players.X ? 'X' : me === game.players.O ? 'O' : null;
  return Boolean(myMark) && game.turn === myMark;
}

export function statusText(game: GameState, me: string | null): string {
  const isPlayer = isPlayerOf(game, me);
  const myTurn = myTurnOf(game, me);
  if (game.kind === 'bj') {
    if (game.over) return resultText(game);
    const score = game.bj?.player_score ?? 0;
    if (!isPlayer) return '观战中 · 只能看到明牌';
    return myTurn ? `轮到你决策（${score} 点）` : `等待庄家结算（${score} 点）`;
  }
  if (game.over) return resultText(game);
  const myMark = me === game.players.X ? 'X' : me === game.players.O ? 'O' : null;
  if (myTurn) return `轮到你（${myMark}）`;
  if (isPlayer) return `等待 ${game.players[game.turn]} 落子`;
  return `观战中 · 轮到 ${game.players[game.turn]}`;
}

/** 牌桌舞台：按棋种切换棋盘 / 牌桌 */
export function GameStage({
  game,
  me,
  size = 'normal',
  onMove,
}: {
  game: GameState;
  me: string | null;
  size?: 'normal' | 'large';
  onMove: (cell: number) => void;
}) {
  const myTurn = myTurnOf(game, me);

  if (game.kind === 'bj') {
    return <BlackjackTable game={game} me={me} />;
  }

  if (game.kind === 'gomoku') {
    return <GomokuBoard game={game} myTurn={myTurn} onMove={onMove} />;
  }

  return (
    <div
      className={`game-board${size === 'large' ? ' game-board-lg' : ''}`}
      role="grid"
      aria-label="井字棋棋盘"
    >
      {game.board.map((cell, i) => {
        const taken = cell !== ' ';
        const isPlayer = isPlayerOf(game, me);
        return (
          <button
            key={i}
            type="button"
            role="gridcell"
            className={`game-cell${cell === 'X' ? ' x' : cell === 'O' ? ' o' : ''}${
              isPlayer ? '' : ' spectate'
            }`}
            disabled={!myTurn || taken}
            onClick={() => onMove(i + 1)}
            aria-label={taken ? `第 ${i + 1} 格 ${cell}` : `第 ${i + 1} 格，可落子`}
          >
            {taken ? cell : i + 1}
          </button>
        );
      })}
    </div>
  );
}
