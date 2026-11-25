import { threadOf } from '../store';
import type { State } from '../store';
import { MAIN } from '../types';

const QUICK = [
  { label: '总结最近 30 条消息', question: '总结一下本群最近的讨论，并把待办事项列出来', scope: 'group' as const },
  { label: '按关键词检索历史', question: '列出本群最近聊过的关键话题', scope: 'group' as const },
  { label: '把这轮结论存成待办', question: '把刚才讨论的结论整理成待办事项并保存', scope: 'group' as const },
];

export function SidePanel({
  state,
  askAgent,
  refreshTodos,
  autoSummary,
  setIncludePrivate,
}: {
  state: State;
  askAgent: (question: string, scope: 'private' | 'group') => void;
  refreshTodos: () => void;
  autoSummary: (action: 'status' | 'on' | 'off' | 'now', minutes?: number) => void;
  setIncludePrivate: (value: boolean) => void;
}) {
  const auto = state.autoSummary;
  const members = [...state.online];
  const mainCount = threadOf(state, MAIN).events.filter((e) => e.kind === 'group').length;
  const todos = state.todos.slice(0, 6);

  return (
    <aside className="panel">
      <section>
        <h2>成员 {members.length}</h2>
        {members.length === 0 && <p className="panel-empty">还没有人登录</p>}
        {members.map((user) => (
          <div className="mem" key={user}>
            <span className={`ava${user === state.me ? ' self' : ''}`}>
              {user.slice(0, 1).toUpperCase()}
            </span>
            <span className="nm">{user}</span>
            <span className="st on">{user === state.me ? '我' : 'online'}</span>
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
            让 Agent「把结论存成待办」试试。
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

      <section>
        <h2>问 Agent</h2>
        <label className="opt">
          <input
            type="checkbox"
            checked={state.includePrivate}
            onChange={(e) => setIncludePrivate(e.target.checked)}
          />
          <span>
            总结时把我与 Agent 的私聊也算进去
            <em>勾选后 Agent 能读 <code>agent:{state.me ?? '我'}</code>；群里总结的结果会发到群里</em>
          </span>
        </label>
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
        <h2>定时总结</h2>
        <div className="auto">
          <p className={`auto-state${auto.enabled ? ' on' : ''}`}>
            {auto.enabled ? `每 ${Math.round(auto.seconds / 60)} 分钟自动总结群聊` : '当前关闭'}
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
            <button type="button" onClick={() => autoSummary('off')} disabled={!auto.enabled}>
              关闭
            </button>
          </div>
          <p className="auto-hint">也可以直接发 /auto 5、/auto off、/auto now</p>
        </div>
      </section>

      <section>
        <h2>会话</h2>
        <div className="kv">
          <span>room</span>
          <span>{state.roomId !== null ? `main #${state.roomId}` : 'main #-'}</span>
          <span>msg</span>
          <span>{mainCount}</span>
          <span>link</span>
          <span>ws → tcp 10086</span>
          <span>rtt</span>
          <span className={latencyClass(state)}>
            {state.link !== 'open' ? '-' : state.latency.ms === null ? '超时' : `${state.latency.ms} ms`}
          </span>
          <span>image</span>
          <span>{state.imageBase || '-'}</span>
          <span>queue</span>
          <span>{state.pendingAgent ? 'Agent 正在处理' : 'idle'}</span>
        </div>
      </section>
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
