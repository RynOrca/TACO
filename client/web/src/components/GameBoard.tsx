import type { GameState } from '../types';

export function resultText(game: GameState): string {
  if (game.result === 'draw') return '平局';
  if (game.winner) return `${game.players[game.winner]} 获胜`;
  return '本局结束';
}

export function statusText(game: GameState, me: string | null): string {
  const isPlayer = Boolean(me) && (game.players.X === me || game.players.O === me);
  const myMark = me === game.players.X ? 'X' : me === game.players.O ? 'O' : null;
  const myTurn = isPlayer && !game.over && game.turn === myMark;
  if (game.over) return resultText(game);
  if (myTurn) return `轮到你（${myMark}）`;
  if (isPlayer) return `等待 ${game.players[game.turn]} 落子`;
  return `观战中 · 轮到 ${game.players[game.turn]}`;
}

export function myTurnOf(game: GameState, me: string | null): boolean {
  if (!me || game.over) return false;
  const myMark = me === game.players.X ? 'X' : me === game.players.O ? 'O' : null;
  return Boolean(myMark) && game.turn === myMark;
}

export function isPlayerOf(game: GameState, me: string | null): boolean {
  return Boolean(me) && (game.players.X === me || game.players.O === me);
}

/** 棋盘本身：侧栏的小棋盘和大厅里的大棋盘共用这一份 */
export function GameBoard({
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
  const isPlayer = isPlayerOf(game, me);

  return (
    <div
      className={`game-board${size === 'large' ? ' game-board-lg' : ''}`}
      role="grid"
      aria-label="井字棋棋盘"
    >
      {game.board.map((cell, i) => {
        const taken = cell !== ' ';
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
