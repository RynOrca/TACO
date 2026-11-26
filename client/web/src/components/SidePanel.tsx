import { useEffect, useState } from 'react';
import { threadOf } from '../store';
import type { State } from '../store';
import { MAIN } from '../types';
import { GamePanel } from './GamePanel';

const QUICK = [
  { label: '总结最近 30 条消息', question: '总结一下本群最近的讨论，并把待办事项列出来', scope: 'group' as const },
  { label: '按关键词检索历史', question: '列出本群最近聊过的关键话题', scope: 'group' as const },
  { label: '把这轮结论存成待办', question: '把刚才讨论的结论整理成待办事项并保存', scope: 'group' as const },
];

type Tab = 'room' | 'game' | 'agent';

const TABS: { key: Tab; label: string }[] = [
  { key: 'room', label: '聊天室' },
  { key: 'game', label: '游戏' },
  { key: 'agent', label: 'Agent' },
];

interface Props {
  state: State;
  askAgent: (question: string, scope: 'private' | 'group') => void;
  refreshTodos: () => void;
  autoSummary: (action: 'status' | 'on' | 'off' | 'now', minutes?: number) => void;
  setIncludePrivate: (value: boolean) => void;
  onGameMove: (cell: number) => void;
  onGameStart: () => void;
  onGameQuit: () => void;
  onGameInvite: (target: string) => void;
  onGameAccept: () => void;
  onGameDecline: () => void;
  onGameFocus: (id: string) => void;
  onGameRematch: () => void;
  onEnterArena: () => void;
  onStartKind: (kind: 'ttt' | 'gomoku' | 'bj') => void;
}

export function SidePanel({
  state,
  askAgent,
  refreshTodos,
  autoSummary,
  setIncludePrivate,
  onGameMove,
  onGameStart,
  onGameQuit,
  onGameInvite,
  onGameAccept,
  onGameDecline,
  onGameFocus,
  onGameRematch,
  onEnterArena,
  onStartKind,
}: Props) {
  const [tab, setTab] = useState<Tab>('room');

  const auto = state.autoSummary;
  const members = [...state.online];
  const others = members.filter((u) => u !== state.me);
  const allGames = Object.values(state.games);
  const mineGame =
    allGames.find(
      (g) => state.me && (g.players.X === state.me || g.players.O === state.me),
    ) ?? null;
  const focusedGame = state.gameFocus ? state.games[state.gameFocus] ?? null : null;
  const ongoingGames = allGames.filter((g) => !g.over);
  const mainCount = threadOf(state, MAIN).events.filter((e) => e.kind === 'group').length;
  const todos = state.todos.slice(0, 6);
  const muted = Object.keys(state.mutes);

  // 轮到我落子、或有人来邀请时，游戏标签页上打个标记
  const myTurn = Boolean(
    mineGame &&
      !mineGame.over &&
      state.me &&
      ((mineGame.turn === 'X' && mineGame.players.X === state.me) ||
        (mineGame.turn === 'O' && mineGame.players.O === state.me)),
  );
  const badge =
    state.gameInvite
      ? '邀请'
      : myTurn
        ? '轮到你'
        : ongoingGames.length && tab !== 'game'
          ? String(ongoingGames.length)
          : '';

  // 收到邀请自动切到游戏页，免得错过
  useEffect(() => {
    if (state.gameInvite) setTab('game');
  }, [state.gameInvite?.from]);

  return (
    <aside className="panel">
      <div className="panel-tabs" role="tablist" aria-label="侧栏">
        {TABS.map((item) => (
          <button
            type="button"
            key={item.key}
            role="tab"
            aria-label={item.label}
            aria-selected={tab === item.key}
            className={`panel-tab${tab === item.key ? ' on' : ''}`}
            onClick={() => setTab(item.key)}
          >
            {item.label}
            {item.key === 'room' && state.todos.length > 0 && (
              <em className="tab-count">{state.todos.length}</em>
            )}
            {item.key === 'game' && badge && <em className="tab-badge">{badge}</em>}
          </button>
        ))}
      </div>

      <div className="panel-body">
        {tab === 'room' && (
          <>
            <section>
              <h2>成员 {members.length}</h2>
              {members.length === 0 && <p className="panel-empty">还没有人登录</p>}
              {members.map((user) => (
                <div className="mem" key={user}>
                  <span className={`ava${user === state.me ? ' self' : ''}`}>
                    {user.slice(0, 1).toUpperCase()}
                  </span>
                  <span className="nm">{user}</span>
                  {state.mutes[user] ? (
                    <span className="st mute" title={`到期：${state.mutes[user]}`}>
                      禁言
                    </span>
                  ) : (
                    <span className="st on">{user === state.me ? '我' : 'online'}</span>
                  )}
                </div>
              ))}
              <div className="mem">
                <span className="ava ai">AI</span>
                <span className="nm">Agent</span>
                <span className="st">bot</span>
              </div>
            </section>

            <section>
              <h2>
                待办 {state.todos.length}
                <button type="button" className="link" onClick={refreshTodos}>
                  刷新
                </button>
              </h2>
              {todos.length === 0 && (
                <p className="panel-empty">
                  暂无待办。
                  <br />
                  去 Agent 页让 Agent「把结论存成待办」试试。
                </p>
              )}
              {todos.map((todo, i) => {
                const done = todo.status === 'done';
                return (
                  <div className={`todo${done ? ' done' : ''}`} key={todo.id ?? i}>
                    <span className="cb">{done ? '✓' : ''}</span>
                    <span>
                      <span className="tx">{firstLine(todo.content)}</span>
                      <span className="sub">
                        {todo.assignee || '-'} · {todo.status || 'pending'} · #{todo.id ?? '-'}
                      </span>
                    </span>
                  </div>
                );
              })}
            </section>

            {muted.length > 0 && (
              <section>
                <h2>禁言 {muted.length}</h2>
                {muted.map((user) => (
                  <div className="mem" key={user}>
                    <span className="ava off">{user.slice(0, 1).toUpperCase()}</span>
                    <span className="nm">{user}</span>
                    <span className="st mute">{state.mutes[user].slice(11, 16)} 解除</span>
                  </div>
                ))}
                <p className="auto-hint">
                  <code>/mute 用户名 分钟</code> · <code>/unmute 用户名</code>（需 ADMIN_USERS）
                </p>
              </section>
            )}

            <section>
              <h2>连接</h2>
              <div className="kv">
                <span>room</span>
                <span>{state.roomId !== null ? `main #${state.roomId}` : 'main #-'}</span>
                <span>msg</span>
                <span>{mainCount}</span>
                <span>link</span>
                <span>ws → tcp 10086</span>
                <span>rtt</span>
                <span className={latencyClass(state)}>
                  {state.link !== 'open'
                    ? '-'
                    : state.latency.ms === null
                      ? '超时'
                      : `${state.latency.ms} ms`}
                </span>
                <span>attach</span>
                <span>{state.imageBase || '-'}</span>
              </div>
            </section>
          </>
        )}

        {tab === 'game' && (
          <>
            <GamePanel
              mine={mineGame}
              focused={focusedGame}
              ongoing={ongoingGames}
              invite={state.gameInvite}
              me={state.me}
              onMove={onGameMove}
              onStart={onGameStart}
              onQuit={onGameQuit}
              onFocus={onGameFocus}
              onAccept={onGameAccept}
              onDecline={onGameDecline}
              onRematch={onGameRematch}
            />
            {(mineGame || focusedGame) && (
              <button type="button" className="btn primary enter-arena" onClick={onEnterArena}>
                进入牌桌
              </button>
            )}
            <section>
              <h2>和 Agent 开局</h2>
              <div className="auto-btns">
                <button type="button" onClick={() => onStartKind('ttt')}>井字棋</button>
                <button type="button" onClick={() => onStartKind('gomoku')}>五子棋</button>
                <button type="button" onClick={() => onStartKind('bj')}>21 点</button>
              </div>
            </section>
            <section>
              <h2>邀请对弈</h2>
              {others.length === 0 && <p className="panel-empty">当前没有其他在线成员</p>}
              <div className="auto-btns">
                {others.map((user) => (
                  <button type="button" key={user} onClick={() => onGameInvite(user)}>
                    邀请 {user}
                  </button>
                ))}
              </div>
              <p className="auto-hint">对方接受后即可对弈，其他人打开这一页就能观战</p>
            </section>
          </>
        )}

        {tab === 'agent' && (
          <>
            <section>
              <h2>快捷提问</h2>
              <div className="qa">
                {QUICK.map((item) => (
                  <button
                    type="button"
                    key={item.label}
                    onClick={() => askAgent(item.question, item.scope)}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </section>

            <section>
              <h2>总结范围</h2>
              <label className="opt">
                <input
                  type="checkbox"
                  checked={state.includePrivate}
                  onChange={(e) => setIncludePrivate(e.target.checked)}
                />
                <span>
                  把我与 Agent 的私聊也算进总结
                  <em>
                    勾选后 Agent 能读 <code>agent:{state.me ?? '我'}</code>；群里的总结结果会发到群里
                  </em>
                </span>
              </label>
            </section>

            <section>
              <h2>定时总结</h2>
              <div className="auto">
                <p className={`auto-state${auto.enabled ? ' on' : ''}`}>
                  {auto.enabled
                    ? `每 ${Math.round(auto.seconds / 60)} 分钟自动总结群聊`
                    : '当前关闭'}
                </p>
                <div className="auto-btns">
                  <button type="button" onClick={() => autoSummary('on', 5)}>
                    每5分钟
                  </button>
                  <button type="button" onClick={() => autoSummary('on', 1)}>
                    每1分钟
                  </button>
                  <button type="button" onClick={() => autoSummary('now')}>
                    立即总结
                  </button>
                  <button
                    type="button"
                    onClick={() => autoSummary('off')}
                    disabled={!auto.enabled}
                  >
                    关闭
                  </button>
                </div>
                <p className="auto-hint">
                  也可以发 <code>/auto 5</code>、<code>/auto now</code>、<code>/auto off</code>
                </p>
              </div>
            </section>

            <section>
              <h2>Agent 状态</h2>
              <div className="kv">
                <span>queue</span>
                <span>{state.pendingAgent ? '正在处理' : 'idle'}</span>
                <span>scope</span>
                <span>{state.includePrivate ? '群聊 + 我的私聊' : '仅群聊'}</span>
                <span>timer</span>
                <span>{auto.enabled ? `${Math.round(auto.seconds / 60)} 分钟` : '关闭'}</span>
              </div>
              <p className="auto-hint">
                更多指令发 <code>/help</code> 查看（含 /agent、/auto、/game、/mute）
              </p>
            </section>
          </>
        )}
      </div>
    </aside>
  );
}

function latencyClass(state: State): string {
  if (state.link !== 'open') return 'kv-bad';
  const ms = state.latency.ms;
  if (ms === null) return 'kv-bad';
  if (ms > 200) return 'kv-warn';
  return 'kv-ok';
}

function firstLine(text: string | undefined): string {
  const line = (text || '').split('\n').find((l) => l.trim()) ?? '';
  return line.replace(/^\s*[-*+]\s*/, '').replace(/^\[[ x]\]\s*/, '').slice(0, 26) || '（空）';
}
