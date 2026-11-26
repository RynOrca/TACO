import type { GameInvite, GameState } from '../types';
import { GameBoard, isPlayerOf, myTurnOf, statusText } from './GameBoard';
import { RematchBar } from './RematchBar';

/** 大厅：专注游戏模式中间那块大棋盘 + 顶部对局信息 + 底部状态条 */
export function Arena({
  game,
  me,
  invite,
  onMove,
  onRematch,
  onQuit,
  onStart,
  onAccept,
  onDecline,
  onClose,
  onTheater,
}: {
  game: GameState | null;
  me: string | null;
  invite: GameInvite | null;
  onMove: (cell: number) => void;
  onRematch: () => void;
  onQuit: () => void;
  onStart: () => void;
  onAccept: () => void;
  onDecline: () => void;
  onClose: () => void;
  onTheater: () => void;
}) {
  const players = game?.players ?? { X: '-', O: '-' };
  const isPlayer = game ? isPlayerOf(game, me) : false;
  const myTurn = game ? myTurnOf(game, me) : false;
  const waits = game && !game.over && game.turn ? players[game.turn] : '';

  return (
    <main className="arena">
      <div className="arena-top">
        <div>
          <div className="gname">井字棋</div>
          <div className="gsub">
            3 × 3 · 三连获胜
            {game ? ` · ${game.spectators} 人观战` : ''}
          </div>
        </div>
        <div className="vs">
          <div className={`side-tag${myTurn ? '' : ''}${game && !game.over && game.turn === 'X' ? ' turn' : ''}`}>
            <span className="dot" />
            <b>{players.X}</b>
            <span>X</span>
          </div>
          <span className="vs-x">VS</span>
          <div className={`side-tag${game && !game.over && game.turn === 'O' ? ' turn' : ''}`}>
            <span className="dot" />
            <b>{players.O}</b>
            <span>O</span>
          </div>
        </div>
        <div className="arena-tools">
          <button type="button" className="btn" onClick={onTheater} title="隐藏聊天，只留棋盘">
            全屏
          </button>
          <button type="button" className="btn" onClick={onClose} title="回到聊天（对局不中断）">
            收起
          </button>
        </div>
      </div>

      <div className="arena-stage">
        {game ? (
          <GameBoard game={game} me={me} size="large" onMove={onMove} />
        ) : (
          <div className="arena-empty">
            {invite ? (
              <>
                <p>
                  <b>{invite.from}</b> 邀请你对弈
                </p>
                <div className="game-invite-btns">
                  <button type="button" className="btn primary" onClick={onAccept}>
                    接受
                  </button>
                  <button type="button" className="btn" onClick={onDecline}>
                    拒绝
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>当前没有对局</p>
                <button type="button" className="btn primary" onClick={onStart}>
                  和 Agent 开局
                </button>
                <p className="dim">或发 /game invite 用户名 找人对弈</p>
              </>
            )}
          </div>
        )}
      </div>

      {game && (
        <div className="arena-status">
          <span className={`arena-turn${myTurn ? ' mine' : ''}`}>
            {statusText(game, me)}
          </span>
          {game.over && isPlayer && (
            <RematchBar game={game} me={me} onRematch={onRematch} onQuit={onQuit} />
          )}
          {!game.over && !isPlayer && <span className="dim">观战 · 不能落子</span>}
          {!game.over && isPlayer && waits === me && <span className="dim">点格子落子</span>}
        </div>
      )}
    </main>
  );
}
