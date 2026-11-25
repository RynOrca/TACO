import type { GameState } from '../types';

const RESULT_TEXT: Record<string, string> = {
  win: '你赢了',
  lose: 'Agent 赢了',
  draw: '平局',
};

interface Props {
  game: GameState | null;
  onMove: (cell: number) => void;
  onStart: () => void;
  onQuit: () => void;
}

export function GamePanel({ game, onMove, onStart, onQuit }: Props) {
  if (!game) {
    return (
      <section className="game">
        <h2>井字棋</h2>
        <p className="panel-empty">和 Agent 下一局，你执 X 先手，点格子落子。</p>
        <button type="button" className="btn primary" onClick={onStart}>
          开始一局
        </button>
      </section>
    );
  }

  const mine = !game.over && game.turn === 'X';
  const stateText = game.over
    ? RESULT_TEXT[game.result] ?? '本局结束'
    : mine
      ? '轮到你（X）'
      : 'Agent 思考中…';

  return (
    <section className="game">
      <h2>
        井字棋
        <button type="button" className="link" onClick={onQuit}>
          退出
        </button>
      </h2>
      <p className={`game-state${game.over ? ' done' : mine ? ' mine' : ' wait'}`}>{stateText}</p>

      <div className="game-board" role="grid" aria-label="井字棋棋盘">
        {game.board.map((cell, i) => {
          const taken = cell !== ' ';
          return (
            <button
              key={i}
              type="button"
              role="gridcell"
              className={`game-cell${cell === 'X' ? ' x' : cell === 'O' ? ' o' : ''}`}
              disabled={!mine || taken}
              onClick={() => onMove(i + 1)}
              aria-label={taken ? `第 ${i + 1} 格 ${cell}` : `第 ${i + 1} 格，可落子`}
            >
              {taken ? cell : i + 1}
            </button>
          );
        })}
      </div>

      <p className="game-score">
        战绩 {game.score.win} 胜 / {game.score.lose} 负 / {game.score.draw} 平
      </p>
      {game.over && (
        <button type="button" className="btn primary" onClick={onStart}>
          再来一局
        </button>
      )}
    </section>
  );
}
