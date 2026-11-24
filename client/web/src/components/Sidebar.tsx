import { pmUsersOf, previewOf, threadOf } from '../store';
import type { State } from '../store';
import { MAIN, pmThread, threadUser } from '../types';

const initials = (name: string) => (name || '?').trim().charAt(0).toUpperCase() || '?';

const LINK_TEXT: Record<State['link'], string> = {
  connecting: '连接中',
  open: '已连接',
  closed: '已断开',
};

export function Sidebar({
  state,
  openThread,
  openAuth,
  onReconnect,
}: {
  state: State;
  openThread: (thread: string) => void;
  openAuth: (open: boolean) => void;
  onReconnect: () => void;
}) {
  const mainPreview = previewOf(state, MAIN);
  const mainUnread = threadOf(state, MAIN).unread;
  const pmUsers = pmUsersOf(state);

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="mark">T</div>
        <div className="name">TACO</div>
        <div className="sub">v0.4</div>
      </div>

      <button
        type="button"
        className={`conn ${state.link}`}
        title={state.linkDetail || '与服务端的长连接正常'}
        onClick={() => state.link !== 'open' && onReconnect()}
      >
        <i />
        <span>{LINK_TEXT[state.link]}</span>
        <b>{state.link === 'open' ? '127.0.0.1:10086' : state.link === 'closed' ? '点此重连' : ''}</b>
      </button>

      <div className="sect">群聊</div>
      <div className="list">
        <button
          type="button"
          className={`item${state.active === MAIN ? ' on' : ''}`}
          onClick={() => openThread(MAIN)}
        >
          <span className="ava hash">#</span>
          <span className="t">
            <b>main</b>
            <em>{mainPreview.text || '还没有消息'}</em>
          </span>
          <span className="meta">
            <span className="tm">{mainPreview.time}</span>
            {mainUnread > 0 && <span className="pill">{mainUnread}</span>}
          </span>
        </button>
      </div>

      <div className="sect">私聊</div>
      <div className="list list-scroll">
        {pmUsers.length === 0 && <p className="list-empty">暂时没有其他人在线</p>}
        {pmUsers.map((user) => {
          const key = pmThread(user);
          const preview = previewOf(state, key);
          const unread = threadOf(state, key).unread;
          const online = state.online.includes(user);
          return (
            <button
              type="button"
              key={user}
              className={`item${state.active === key ? ' on' : ''}`}
              onClick={() => openThread(key)}
            >
              <span className={`ava${online ? '' : ' off'}`}>{initials(user)}</span>
              <span className="t">
                <b>{user}</b>
                <em>{preview.text || (online ? '在线上，还没聊过' : '离线')}</em>
              </span>
              <span className="meta">
                <span className="tm">{preview.time}</span>
                {unread > 0 && <span className="pill">{unread}</span>}
              </span>
            </button>
          );
        })}
      </div>

      <div className="me">
        <span className={`ava${state.me ? ' self' : ''}`}>
          {state.me ? initials(state.me) : '?'}
        </span>
        <span className="who">
          {state.me ?? '未登录'}
          <em>
            {state.me
              ? `room #${state.roomId ?? '-'} · ${state.online.length} 人在线`
              : '点右侧按钮登录'}
          </em>
        </span>
        <button type="button" className="switch" onClick={() => openAuth(true)}>
          切换账号
        </button>
      </div>
    </aside>
  );
}

export function ConvHead({
  state,
  onSearch,
  onSummary,
}: {
  state: State;
  onSearch: () => void;
  onSummary: () => void;
}) {
  const isPM = state.active !== MAIN;
  const title = isPM ? `@${threadUser(state.active)}` : 'main';
  const pair = isPM
    ? `pm:${[state.me ?? '', threadUser(state.active)].sort().join(':')}`
    : `room_id ${state.roomId ?? '-'}`;
  const meta = isPM
    ? `私聊 · ${pair}`
    : `群聊 · ${pair} · ${state.online.length} 人在线`;
  return (
    <header className="chead">
      <h1>{title}</h1>
      <div className="meta">{meta}</div>
      <div className="tools">
        <button type="button" className="btn" onClick={onSearch}>
          搜索历史
        </button>
        <button type="button" className="btn primary" onClick={onSummary}>
          总结本群
        </button>
      </div>
    </header>
  );
}
