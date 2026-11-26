import type { GameInvite, GameState } from '../types';
import { GameStage, isPlayerOf, myTurnOf, statusText } from './GameBoard';
import { RematchBar } from './RematchBar';

/** 大厅：专注游戏模式中间那块大棋盘 + 顶部对局信息 + 底部状态条 */
export function Arena({
  game,
  me,
  invite,
  onMove,
  onRematch,
  onQuit,
  onHit,
  onStand,
  onStartKind,
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
  onHit: () => void;
  onStand: () => void;
  onStartKind: (kind: 'ttt' | 'gomoku' | 'bj') => void;
  onAccept: () => void;
  onDecline: () => void;
  onClose: () => void;
  onTheater: () => void;
}) {
  const players = game?.players ?? { X: '-', O: '-' };
  const kind = game?.kind ?? 'ttt';
  const title = kind === 'gomoku' ? '五子棋' : kind === 'bj' ? '21 点' : '井字棋';
  const subtitle =
    kind === 'gomoku'
      ? '15 × 15 · 五连获胜'
      : kind === 'bj'
        ? '庄家 Agent · 你的手牌只有你能看到'
        : '3 × 3 · 三连获胜';
  const isPlayer = game ? isPlayerOf(game, me) : false;
  const myTurn = game ? myTurnOf(game, me) : false;
  const waits = game && !game.over && game.turn ? players[game.turn] : '';

  return (
    <main className="arena">
      <div className="arena-top">
        <div>
          <div className="gname">{title}</div>
          <div className="gsub">
            {subtitle}
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

      {invite && !isPlayer && (
        <div className="arena-invite">
          <span>
            <b>{invite.from}</b> 邀请你玩
            {invite.kind === 'gomoku' ? '五子棋' : invite.kind === 'bj' ? '21 点' : '井字棋'}
          </span>
          <span className="game-invite-btns">
            <button type="button" className="btn primary" onClick={onAccept}>
              接受
            </button>
            <button type="button" className="btn" onClick={onDecline}>
              拒绝
            </button>
          </span>
        </div>
      )}

      <div className="arena-stage">
        {game ? (
          <GameStage game={game} me={me} size="large" onMove={onMove} />
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
                <div className="arena-starts">
                  <button type="button" className="btn primary" onClick={() => onStartKind('ttt')}>
                    井字棋
                  </button>
                  <button type="button" className="btn primary" onClick={() => onStartKind('gomoku')}>
                    五子棋
                  </button>
                  <button type="button" className="btn primary" onClick={() => onStartKind('bj')}>
                    21 点
                  </button>
                </div>
                <p className="dim">或发 /game invite 用户名 [gomoku] 找人对弈</p>
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
          {game.kind === 'bj' && !game.over && game.bj?.current === me && (
            <span className="bj-actions">
              <button type="button" className="btn primary" onClick={onHit}>
                要牌
              </button>
              <button type="button" className="btn" onClick={onStand}>
                停牌
              </button>
            </span>
          )}
          {game.kind !== 'bj' && !game.over && !isPlayer && <span className="dim">观战 · 不能落子</span>}
          {game.kind !== 'bj' && !game.over && isPlayer && waits === me && <span className="dim">点格子落子</span>}
        </div>
      )}
    </main>
  );
}
