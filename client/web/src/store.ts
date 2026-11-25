import { AGENT, MAIN, pmThread, threadUser } from './types';
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
  /** 让 Agent 总结时是否允许它读"我和 Agent 的私聊" */
  includePrivate: boolean;
  /** /help 弹窗 */
  help: boolean;
  /** 网络延迟：最近一次 RTT（ms）与探测时刻 */
  latency: { ms: number | null; at: number | null };
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
  | { type: 'include-private'; value: boolean }
  | { type: 'help'; open: boolean }
  | { type: 'latency'; ms: number | null }
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
  if (item.msg_type === 'agent_ask_group' || item.msg_type === 'agent_ask_private') {
    event.kind = 'ask';
    event.agentScope = item.msg_type === 'agent_ask_group' ? 'group' : 'private';
  }
  return event;
}

function mergeHistory(state: State, msg: ServerMsg, older: boolean): State {
  const key = msg.agent ? AGENT : msg.target ? pmThread(msg.target) : MAIN;
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
  // 服务端每轮都会带 steps；历史消息没有这个字段，界面要能区分"没调工具"和"不知道调没调"
  if (msg.steps) event.steps = msg.steps as ToolStep[];
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
      const ask = msg.msg_type === 'agent_ask_group';
      const event = makeEvent(ask ? 'ask' : 'group', msg.sender || '?', msg.msg ?? '', msg.id);
      if (ask) event.agentScope = 'group';
      applyExtras(event, msg);
      return appendEvent(state, MAIN, event, state.active === MAIN);
    }

    case 'agent_ask': {
      // 只有本人收得到：问 Agent 的私聊提问
      const event = makeEvent('ask', msg.sender || '?', msg.msg ?? '', msg.id);
      event.agentScope = 'private';
      return appendEvent(state, AGENT, event, state.active === AGENT);
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
        const key = msg.thread ?? state.pendingAgent?.thread ?? state.active;
        const event = makeEvent('agent', 'Agent', msg.msg ?? '正在思考…');
        event.status = 'pending';
        event.scope = msg.scope ?? state.pendingAgent?.scope ?? 'private';
        return appendEvent(state, key, event, state.active === key);
      }
      const target = msg.thread === 'agent' ? AGENT
        : msg.thread === 'main' ? MAIN
        : state.pendingAgent?.scope === 'private' ? state.pendingAgent.thread : MAIN;
      const event = makeEvent('agent', 'Agent', msg.msg ?? '');
      event.status = 'done';
      event.scope = msg.scope ?? state.pendingAgent?.scope;
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

    case 'pong':
      // 只认自己发出去的那次探测，别被别人（比如心跳）的 pong 搅乱
      return typeof msg.t === 'number'
        ? { ...state, latency: { ms: Math.max(0, Date.now() - msg.t), at: Date.now() } }
        : state;

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

    case 'include-private':
      return { ...state, includePrivate: action.value };

    case 'help':
      return { ...state, help: action.open };

    case 'latency':
      return { ...state, latency: { ms: action.ms, at: Date.now() } };

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
    includePrivate: false,
    help: false,
    latency: { ms: null, at: null },
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
