import { useCallback, useEffect, useReducer, useRef } from 'react';
import { Bridge } from './bridge-client';
import { initialState, reducer } from './store';
import type { State } from './store';
import { AGENT, MAIN, PAGE_SIZE, threadUser } from './types';
import type { SendMsg } from './types';
import { uploadImage } from './upload';

export type ComposeMode = 'chat' | 'agent' | 'agent-group';

export interface Chat {
  state: State;
  openThread: (thread: string) => void;
  loadOlder: () => void;
  sendText: (text: string, mode: ComposeMode) => void;
  askAgent: (question: string, scope: 'private' | 'group') => void;
  sendImage: (file: File) => Promise<void>;
  autoSummary: (action: 'status' | 'on' | 'off' | 'now', minutes?: number) => void;
  setIncludePrivate: (value: boolean) => void;
  setHelp: (open: boolean) => void;
  submitAuth: (kind: 'login' | 'register', user: string, password: string) => void;
  setAuthUser: (user: string) => void;
  openAuth: (open: boolean) => void;
  reconnect: () => void;
  refreshTodos: () => void;
}

export function useChat(): Chat {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const bridge = useRef<Bridge | null>(null);
  const latest = useRef(state);
  latest.current = state;

  useEffect(() => {
    const link = new Bridge({
      onLink: (linkState, detail) => dispatch({ type: 'link', state: linkState, detail }),
      onServer: (msg) => dispatch({ type: 'server', msg }),
      onHello: (imageBase) => dispatch({ type: 'hello', imageBase }),
    });
    bridge.current = link;
    link.connect();
    return () => {
      link.dispose();
      bridge.current = null;
    };
  }, []);

  const send = useCallback((msg: SendMsg) => bridge.current?.send(msg) ?? false, []);

  const requestHistory = useCallback(
    (thread: string, older: boolean) => {
      const current = latest.current.threads[thread];
      const payload: SendMsg = { type: 'history', limit: PAGE_SIZE };
      if (thread === AGENT) payload.agent = true;
      else if (thread.startsWith('pm:')) payload.target = threadUser(thread);
      if (older) {
        const ids = (current?.events ?? [])
          .map((e) => e.id)
          .filter((id): id is number => typeof id === 'number');
        if (!ids.length) return;
        payload.before_id = Math.min(...ids);
      }
      dispatch({ type: 'need-history', thread, older });
      if (!send(payload)) dispatch({ type: 'history-failed', thread });
    },
    [send],
  );

  const openThread = useCallback(
    (thread: string) => {
      dispatch({ type: 'switch', thread });
      const current = latest.current.threads[thread];
      if (!current?.loaded && !current?.loading) requestHistory(thread, false);
    },
    [requestHistory],
  );

  const loadOlder = useCallback(() => {
    const { active, threads } = latest.current;
    const thread = threads[active];
    if (!thread || !thread.loaded || !thread.more || thread.loading) return;
    requestHistory(active, true);
  }, [requestHistory]);

  const askAgent = useCallback(
    (question: string, scope: 'private' | 'group') => {
      const text = question.trim();
      if (!text) return;
      const { me, active } = latest.current;
      if (!me) {
        dispatch({ type: 'auth-open', open: true });
        return;
      }
      // 群里问 → 答案回群里；私下问 → 进"我和 Agent"的会话
      const thread = scope === 'group' ? MAIN : AGENT;
      if (thread === AGENT) openThread(AGENT);   // 顺带把之前的私聊历史拉出来
      dispatch({ type: 'agent-request', thread, scope });
      const includePrivate = latest.current.includePrivate;
      if (!send({ type: 'agent', msg: text, scope, include_private: includePrivate })) {
        dispatch({ type: 'local', kind: 'error', text: '本地桥未连接，Agent 请求没有发出去' });
      }
      void active;
    },
    [send],
  );

  const submitAuth = useCallback(
    (kind: 'login' | 'register', user: string, password: string) => {
      const name = user.trim();
      if (!name) {
        dispatch({ type: 'auth-form', error: '用户名不能为空' });
        return;
      }
      dispatch({ type: 'auth-submit', user: name });
      if (!send({ type: kind, user_id: name, password })) {
        dispatch({ type: 'auth-busy', busy: false });
        dispatch({ type: 'auth-form', error: '本地桥未连接：先运行 python -m client.bridge' });
      }
    },
    [send],
  );

  const submitAuthRef = useRef(submitAuth);
  submitAuthRef.current = submitAuth;

  const sendText = useCallback(
    (raw: string, mode: ComposeMode) => {
      const text = raw.trim();
      if (!text) return;
      if (/^\/(help|\?)$/i.test(text)) {
        dispatch({ type: 'help', open: true });
        return;
      }
      const { me, active } = latest.current;
      if (!me) {
        dispatch({ type: 'auth-open', open: true });
        return;
      }

      if (/^@agent(?=\s|$)/i.test(text)) {
        const question = text.replace(/^@agent\s*/i, '').trim();
        if (!question) {
          dispatch({ type: 'local', kind: 'error', text: '用法：@Agent 你的问题' });
          return;
        }
        // 群里 @Agent 就把答案发回群里，私聊里 @Agent 就只回给自己
        askAgent(question, active === MAIN ? 'group' : 'private');
        return;
      }

      if (text.startsWith('/')) {
        const [cmd, ...rest] = text.split(/\s+/);
        const body = rest.join(' ');
        if (cmd === '/agent' || cmd === '/agent@group') {
          askAgent(body, cmd === '/agent@group' ? 'group' : 'private');
          return;
        }
        if (cmd === '/pm') {
          const [target, ...msg] = rest;
          if (!target || !msg.length) {
            dispatch({ type: 'local', kind: 'error', text: '用法：/pm 用户名 消息' });
            return;
          }
          send({ type: 'private', target, msg: msg.join(' ') });
          return;
        }
        if (cmd === '/auto') {
          const arg = (rest[0] || '').toLowerCase();
          if (!arg) send({ type: 'autosummary', action: 'status' });
          else if (arg === 'off') send({ type: 'autosummary', action: 'off' });
          else if (arg === 'now') send({ type: 'autosummary', action: 'now' });
          else if (/^\d+$/.test(arg)) send({ type: 'autosummary', action: 'on', minutes: Number(arg) });
          else dispatch({ type: 'local', kind: 'error', text: '用法：/auto [分钟 | off | now]' });
          return;
        }
        if (cmd === '/login' || cmd === '/register') {
          const [user, password = ''] = rest;
          if (user) submitAuthRef.current(cmd === '/login' ? 'login' : 'register', user, password);
          return;
        }
        dispatch({ type: 'local', kind: 'error', text: `不认识的命令 ${cmd}，试试 /agent、/pm、/login` });
        return;
      }

      if (mode !== 'chat') {
        askAgent(text, mode === 'agent-group' ? 'group' : 'private');
        return;
      }
      if (active === MAIN) {
        send({ type: 'group', msg: text });
      } else if (active === AGENT) {
        // 在"我和 Agent"的会话里打字，就是在问 Agent
        askAgent(text, 'private');
      } else {
        send({ type: 'private', target: threadUser(active), msg: text });
      }
    },
    [askAgent, send],
  );

  const sendImage = useCallback(
    async (file: File) => {
      const { me, active, imageBase } = latest.current;
      if (!me) {
        dispatch({ type: 'auth-open', open: true });
        return;
      }
      try {
        const uploaded = await uploadImage(file, imageBase);
        const payload =
          active === MAIN
            ? { type: 'group' as const, msg: '[图片]', image: uploaded.file }
            : { type: 'private' as const, target: threadUser(active), msg: '[图片]', image: uploaded.file };
        if (!send(payload)) {
          dispatch({ type: 'local', kind: 'error', text: '本地桥未连接，图片没有发出去' });
        }
      } catch (error) {
        dispatch({ type: 'local', kind: 'error', text: `图片发送失败：${(error as Error).message}` });
      }
    },
    [send],
  );

  const autoSummary = useCallback(
    (action: 'status' | 'on' | 'off' | 'now', minutes?: number) => {
      send(minutes ? { type: 'autosummary', action, minutes } : { type: 'autosummary', action });
    },
    [send],
  );

  const setHelp = useCallback((open: boolean) => dispatch({ type: 'help', open }), []);

  const setIncludePrivate = useCallback(
    (value: boolean) => dispatch({ type: 'include-private', value }),
    [],
  );

  const setAuthUser = useCallback((user: string) => dispatch({ type: 'auth-form', user }), []);
  const openAuth = useCallback((open: boolean) => dispatch({ type: 'auth-open', open }), []);
  const reconnect = useCallback(() => {
    if (!send({ type: 'reconnect' })) window.location.reload();
  }, [send]);
  const refreshTodos = useCallback(() => {
    send({ type: 'todos' });
  }, [send]);

  // 登录成功后拉一次待办、定时总结状态与首屏历史
  useEffect(() => {
    if (!state.me) return;
    send({ type: 'todos' });
    send({ type: 'autosummary', action: 'status' });
    requestHistory(state.active, false);
  }, [state.me, send, requestHistory]);

  // 延迟监测：每 5 秒 ping 一次，15 秒没有 pong 就当超时
  useEffect(() => {
    if (state.link !== 'open') {
      dispatch({ type: 'latency', ms: null });
      return;
    }
    let alive = true;
    const probe = () => {
      if (!alive) return;
      const sent = Date.now();
      send({ type: 'ping', t: sent });
      window.setTimeout(() => {
        const last = latest.current.latency.at;
        // 这一轮没有任何 pong（at 没被刷新）→ 判定超时
        if (alive && (last === null || last < sent)) dispatch({ type: 'latency', ms: null });
      }, 3000);
    };
    probe();
    const timer = window.setInterval(probe, 5000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [state.link, send]);

  // 链路（重新）连通时探一下身份：桥重启后 TCP 连接是新的，服务端会回 NOT_LOGIN
  const lastLink = useRef(state.link);
  useEffect(() => {
    if (lastLink.current !== 'open' && state.link === 'open' && state.me) send({ type: 'todos' });
    lastLink.current = state.link;
  }, [state.link, state.me, send]);

  // Agent 每回复一次，待办可能被改写
  useEffect(() => {
    if (!state.me || !state.todosDirty) return;
    send({ type: 'todos' });
  }, [state.todosDirty, state.me, send]);

  return {
    state,
    openThread,
    loadOlder,
    sendText,
    askAgent,
    sendImage,
    autoSummary,
    setIncludePrivate,
    setHelp,
    submitAuth,
    setAuthUser,
    openAuth,
    reconnect,
    refreshTodos,
  };
}

