import { MAIN, pmThread, threadUser } from './types';
import type {
  ChatEvent,
  HistoryItem,
  LinkState,
  ServerMsg,
  ThreadState,
  TodoItem,
  ToolStep,
  EventKind,
} from './types';
import { dateKeyOf, parseStamp, timeOf } from './time';

export interface State {
  link: LinkState;
  linkDetail: string;
  online: string[];
  me: string | null;
  roomId: number | null;
  active: string;
  threads: Record<string, ThreadState>;
  todos: TodoItem[];
  auth: { open: boolean; busy: boolean; error: string | null; user: string; pending: string | null };
  pendingAgent: { thread: string; scope: 'private' | 'group' } | null;
  /** 图片服务地址（由桥在握手时告知） */
  imageBase: string;
  /** Agent 定时总结 */
  autoSummary: { enabled: boolean; seconds: number };
  /** 有更早的历史被插到前面，Transcript 要保住滚动位置 */
  prependToken: number;
  /** 需要滚到底部 */
  bottomToken: number;
  /** 每次 +1 表示该重新拉一次待办 */
  todosDirty: number;
}

export type Action =
  | { type: 'link'; state: LinkState; detail: string }
  | { type: 'server'; msg: ServerMsg }
  | { type: 'switch'; thread: string }
  | { type: 'auth-open'; open: boolean }
  | { type: 'auth-form'; user?: string; error?: string | null }
  | { type: 'auth-busy'; busy: boolean }
  | { type: 'auth-submit'; user: string }
  | { type: 'need-history'; thread: string; older: boolean }
  | { type: 'history-failed'; thread: string }
  | { type: 'agent-request'; thread: string; scope: 'private' | 'group' }
  | { type: 'hello'; imageBase: string }
  | { type: 'agent-ask'; thread: string; text: string; scope: 'private' | 'group' }
  | { type: 'local'; kind: 'system' | 'error'; text: string };

const emptyThread = (): ThreadState => ({
  events: [],
  loaded: false,
  more: false,
  loading: false,
  unread: 0,
});

let seq = 0;
const nextKey = () => `e${++seq}`;

const AUTH_CODES = new Set([
  'BAD_PASSWORD',
  'NOT_REGISTERED',
  'USER_EXISTS',
  'BAD_REGISTER',
  'BAD_LOGIN',
  'LOGIN_FAILED',
]);

function makeEvent(kind: EventKind, sender: string, text: string, id?: number): ChatEvent {
  const now = new Date();
  return {
    key: id ? `m${id}` : nextKey(),
    kind,
    sender,
    text,
    time: timeOf(now),
    date: dateKeyOf(now),
    stamp: now.getTime(),
    id,
  };
}

function withThread(
  state: State,
  key: string,
  patch: (thread: ThreadState) => ThreadState,
): State {
  const thread = state.threads[key] ?? emptyThread();
  const next = patch(thread);
  if (next === thread) return state;
  return { ...state, threads: { ...state.threads, [key]: next } };
}

function appendEvent(state: State, key: string, event: ChatEvent, active: boolean): State {
  const next = withThread(state, key, (thread) => ({
    ...thread,
    unread: active ? thread.unread : thread.unread + 1,
    events: [...thread.events, event],
  }));
  return active ? { ...next, bottomToken: next.bottomToken + 1 } : next;
}

/** 客户端渲染用的时间戳来自收到的时刻；历史消息用 created_at */
function eventFromHistory(item: HistoryItem): ChatEvent {
  const kind: EventKind =
    item.msg_type === 'group' || item.msg_type === 'private' || item.msg_type === 'agent'
      ? item.msg_type
      : 'system';
  const stamp = parseStamp(item.created_at);
  const date = new Date(stamp);
  const event: ChatEvent = {
    key: item.id ? `m${item.id}` : nextKey(),
    kind,
    sender: item.sender || '?',
    text: item.content || '',
    time: timeOf(date),
    date: dateKeyOf(date),
    stamp,
    id: item.id,
  };
  if (kind === 'agent') event.status = 'done';
  if (item.msg_type === 'image') {
    event.image = item.content;
    event.text = '[图片]';
  }
  return event;
}

function mergeHistory(state: State, msg: ServerMsg, older: boolean): State {
  const key = msg.target ? pmThread(msg.target) : MAIN;
  const items = (msg.items ?? []) as HistoryItem[];
  const incoming = items.map(eventFromHistory);
  const thread = state.threads[key] ?? emptyThread();
  const known = new Set(thread.events.map((e) => e.id).filter((id): id is number => !!id));
  const fresh = incoming.filter((e) => !e.id || !known.has(e.id));
  const events = [...fresh, ...thread.events].sort((a, b) => a.stamp - b.stamp);

  const next = withThread(state, key, () => ({
    ...thread,
    events,
    loaded: true,
    loading: false,
    more: Boolean(msg.more),
  }));
  if (!fresh.length) return next;
  return older
    ? { ...next, prependToken: next.prependToken + 1 }
    : { ...next, bottomToken: next.bottomToken + 1 };
}

function applyExtras(event: ChatEvent, msg: ServerMsg): void {
  if (msg.msg_type === 'image' && msg.image) {
    event.image = msg.image;
    event.text = '[图片]';
  }
  if (msg.steps?.length) event.steps = msg.steps as ToolStep[];
}

function dropPending(threads: Record<string, ThreadState>): Record<string, ThreadState> {
  const out: Record<string, ThreadState> = {};
  for (const [key, thread] of Object.entries(threads)) {
    const events = thread.events.filter((e) => e.status !== 'pending');
    out[key] = events.length === thread.events.length ? thread : { ...thread, events };
  }
  return out;
}

function onServer(state: State, msg: ServerMsg): State {
  switch (msg.type) {
    case 'userlist':
      return {
        ...state,
        online: [...new Set(msg.users ?? [])],
      };

    case 'system': {
      const text = msg.msg ?? '';
      let next = appendEvent(state, MAIN, makeEvent('system', '系统', text), state.active === MAIN);
      const room = /room_id=(\d+)/.exec(text);
      if (room) next = { ...next, roomId: Number(room[1]) };
      if (text.includes('登录成功') && state.auth.pending) {
        next = {
          ...next,
          me: state.auth.pending,
          auth: { ...state.auth, open: false, busy: false, error: null, pending: null },
        };
      } else if (next.auth.busy) {
        // 注册成功之类的系统回执也算一次应答，别让按钮一直转圈
        next = { ...next, auth: { ...next.auth, busy: false } };
      }
      return next;
    }

    case 'group': {
      const event = makeEvent('group', msg.sender || '?', msg.msg ?? '', msg.id);
      applyExtras(event, msg);
      return appendEvent(state, MAIN, event, state.active === MAIN);
    }

    case 'private': {
      const mine = msg.sender === state.me;
      const other = mine ? msg.target || '' : msg.sender || '';
      if (!other) return state;
      const key = pmThread(other);
      const event = makeEvent('private', msg.sender || '?', msg.msg ?? '', msg.id);
      applyExtras(event, msg);
      return appendEvent(state, key, event, state.active === key);
    }

    case 'agent': {
      if (msg.status === 'pending') {
        const key = state.pendingAgent?.thread ?? state.active;
        const event = makeEvent('agent', 'Agent', msg.msg ?? '正在思考…');
        event.status = 'pending';
        event.scope = state.pendingAgent?.scope ?? 'private';
        return appendEvent(state, key, event, state.active === key);
      }
      const request = state.pendingAgent;
      const target = request && request.scope === 'private' ? request.thread : MAIN;
      const event = makeEvent('agent', 'Agent', msg.msg ?? '');
      event.status = 'done';
      event.scope = msg.scope ?? request?.scope;
      event.steps = msg.steps ?? [];
      event.scheduled = msg.scheduled;
      const stripped: State = {
        ...state,
        threads: dropPending(state.threads),
        pendingAgent: null,
        todosDirty: state.todosDirty + 1,
      };
      return appendEvent(stripped, target, event, stripped.active === target);
    }

    case 'history':
      return mergeHistory(state, msg, Boolean(msg.before_id));

    case 'todos':
      return { ...state, todos: (msg.items ?? []) as TodoItem[] };

    case 'autosummary':
      return {
        ...state,
        autoSummary: {
          enabled: Boolean(msg.enabled),
          seconds: Number(msg.seconds ?? 0),
        },
      };

    case 'hello':
      return { ...state, imageBase: msg.image_base ?? '' };

    case 'error': {
      // 桥/页面重连后是一条新的 TCP 连接，服务端已经没有我这个身份了
      if (msg.code === 'NOT_LOGIN' && state.me) {
        const event = makeEvent('error', '错误', msg.msg ?? '');
        event.code = msg.code;
        const next = appendEvent(state, state.active, event, true);
        return {
          ...next,
          me: null,
          auth: {
            open: true,
            busy: false,
            error: '跟服务端的连接重建过，请重新登录',
            user: state.me,
            pending: null,
          },
        };
      }
      if (AUTH_CODES.has(msg.code ?? '')) {
        return {
          ...state,
          auth: { ...state.auth, busy: false, error: `${msg.code} · ${msg.msg ?? ''}` },
        };
      }
      const event = makeEvent('error', '错误', msg.msg ?? '', undefined);
      event.code = msg.code ?? 'ERROR';
      return appendEvent(state, state.active, event, true);
    }

    default:
      return state;
  }
}

export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'link':
      return { ...state, link: action.state, linkDetail: action.detail };

    case 'hello':
      return { ...state, imageBase: action.imageBase };

    case 'server':
      return onServer(state, action.msg);

    case 'switch': {
      if (action.thread === state.active) return state;
      const thread = state.threads[action.thread];
      const threads = thread && thread.unread
        ? { ...state.threads, [action.thread]: { ...thread, unread: 0 } }
        : state.threads;
      return { ...state, active: action.thread, threads, bottomToken: state.bottomToken + 1 };
    }

    case 'auth-open':
      return {
        ...state,
        auth: {
          ...state.auth,
          open: action.open,
          busy: false,
          error: action.open ? null : state.auth.error,
          user: action.open && state.me ? state.me : state.auth.user,
        },
      };

    case 'auth-form':
      return {
        ...state,
        auth: {
          ...state.auth,
          user: action.user ?? state.auth.user,
          error: action.error === undefined ? state.auth.error : action.error,
        },
      };

    case 'auth-busy':
      return { ...state, auth: { ...state.auth, busy: action.busy } };

    case 'auth-submit':
      return {
        ...state,
        auth: { ...state.auth, busy: true, error: null, pending: action.user },
      };

    case 'need-history':
      return withThread(state, action.thread, (thread) => {
        if (!action.older && (thread.loaded || thread.loading)) return thread;
        return { ...thread, loading: true, loaded: !action.older || thread.loaded };
      });

    case 'history-failed':
      return withThread(state, action.thread, (thread) => ({
        ...thread,
        loading: false,
        loaded: thread.events.length > 0,
      }));

    case 'local': {
      const event = makeEvent(action.kind, action.kind === 'system' ? '系统' : '错误', action.text);
      return appendEvent(state, state.active, event, true);
    }

    case 'agent-ask': {
      // 提问在本地回显成一条自己的消息（服务端不保存 Agent 提问，私聊提问更不能进群聊历史）
      const kind = action.thread === MAIN ? 'group' : 'private';
      const event = makeEvent(kind, state.me ?? '我', action.text);
      event.agentScope = action.scope;
      return appendEvent(state, action.thread, event, state.active === action.thread);
    }

    case 'agent-request':
      return {
        ...state,
        pendingAgent: { thread: action.thread, scope: action.scope },
        auth: { ...state.auth, error: null },
      };

    default:
      return state;
  }
}

export function initialState(): State {
  return {
    link: 'connecting',
    linkDetail: '',
    online: [],
    me: null,
    roomId: null,
    active: MAIN,
    threads: {},
    todos: [],
    auth: { open: true, busy: false, error: null, user: '', pending: null },
    pendingAgent: null,
    imageBase: '',
    autoSummary: { enabled: false, seconds: 0 },
    prependToken: 0,
    bottomToken: 0,
    todosDirty: 0,
  };
}

export function threadOf(state: State, key: string): ThreadState {
  return state.threads[key] ?? emptyThread();
}

/** 侧栏预览：最后一条可读消息 */
export function previewOf(state: State, key: string): { text: string; time: string } {
  const events = threadOf(state, key).events;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (event.kind === 'system' || event.kind === 'error') continue;
    const line = (event.text.split('\n').find((l) => l.trim()) ?? '')
      .replace(/^[#>\s]+/, '')
      .replace(/\*\*/g, '')
      .replace(/`/g, '');
    const who = event.kind === 'agent' ? 'Agent' : event.sender;
    return {
      text: event.kind === 'group' || event.kind === 'private' ? `${who}: ${line}` : line,
      time: event.time,
    };
  }
  return { text: '', time: '' };
}

export function pmUsersOf(state: State): string[] {
  const seen = new Set<string>();
  for (const [key] of Object.entries(state.threads)) {
    if (key.startsWith('pm:')) seen.add(threadUser(key));
  }
  for (const user of state.online) {
    if (user !== state.me) seen.add(user);
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}
