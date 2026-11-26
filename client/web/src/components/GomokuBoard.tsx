import type { GameState } from '../types';

/** 15×15 交叉线棋盘：棋子落在交叉点上（不是格子中心） */
export function GomokuBoard({
  game,
  myTurn,
  onMove,
}: {
  game: GameState;
  myTurn: boolean;
  onMove: (cell: number) => void;
}) {
  const size = game.size ?? 15;
  const winSet = new Set(game.win_cells ?? []);
  const last = game.last_move ?? null;

  const cells = [];
  for (let i = 0; i < size * size; i += 1) {
    const x = i % size;
    const y = Math.floor(i / size);
    const mark = game.board[i] ?? ' ';
    const isLast = last === i;
    const isWin = winSet.has(i);
    cells.push(
      <button
        key={i}
        type="button"
        className={`go-point${mark !== ' ' ? ' taken' : ''}`}
        style={{ left: `calc(var(--cell) * (${x} + 0.5))`, top: `calc(var(--cell) * (${y} + 0.5))` }}
        disabled={!myTurn || mark !== ' '}
        onClick={() => onMove(i + 1)}
        aria-label={mark === ' ' ? `第 ${x + 1} 列第 ${y + 1} 行，可落子` : `第 ${x + 1} 列第 ${y + 1} 行 ${mark}`}
      >
        {mark !== ' ' && (
          <span className={`go-stone ${mark === 'X' ? 'black' : 'white'}${isLast ? ' last' : ''}${isWin ? ' win' : ''}`} />
        )}
      </button>,
    );
  }

  return (
    <div className="gomoku" style={{ ['--n' as string]: size }}>
      <div className="go-grid" />
      {[
        [3, 3], [11, 3], [3, 11], [11, 11], [7, 7],
      ]
        .filter(([x, y]) => x < size && y < size)
        .map(([x, y]) => (
          <span
            key={`star-${x}-${y}`}
            className="go-star"
            style={{ left: `calc(var(--cell) * (${x} + 0.5))`, top: `calc(var(--cell) * (${y} + 0.5))` }}
          />
        ))}
      {cells}
    </div>
  );
}
