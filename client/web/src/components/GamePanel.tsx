import type { GameInvite, GameState } from '../types';
import { GameBoard, isPlayerOf, myTurnOf, resultText, statusText } from './GameBoard';
import { RematchBar } from './RematchBar';

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

function countsDown(invite: GameInvite): number {
  const left = invite.ttl * 1000 - (Date.now() - invite.at);
  return Math.max(0, Math.ceil(left / 1000));
}

/** 侧栏里的紧凑版：标题 + 小棋盘 + 邀请 + 进行中列表 */
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
  const myTurn = game ? myTurnOf(game, me) : false;

  const inviteCard = invite && countsDown(invite) > 0 && (
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
  );

  if (!game) {
    return (
      <section className="game">
        <h2>井字棋</h2>
        {inviteCard}
        <p className="panel-empty">
          和 Agent 下一局，或 <code>/game invite 用户名</code> 找人对弈。
        </p>
        <button type="button" className="btn primary" onClick={onStart}>
          和 Agent 开局
        </button>
      </section>
    );
  }

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
      </h2>

      {inviteCard}

      <p
        className={`game-state${game.over ? ' done' : myTurn ? ' mine' : ' wait'}`}
        title={isPlayerOf(game, me) ? '你是这盘的玩家' : '观战'}
      >
        {statusText(game, me)}
        {!isPlayerOf(game, me) && <span className="game-spectate">只读</span>}
      </p>

      <GameBoard game={game} me={me} onMove={onMove} />

      {game.over && isPlayerOf(game, me) && (
        <RematchBar game={game} me={me} onRematch={onRematch} onQuit={onQuit} />
      )}

      {game.over && !game.vs_agent && <p className="game-score">{resultText(game)}</p>}

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
