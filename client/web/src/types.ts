export type LinkState = 'connecting' | 'open' | 'closed';

/** 服务端 / 桥发来的消息；字段按 protocol.TYPE_CODE 里的类型各自可选 */
export interface ToolStep {
  name: string;
  args: Record<string, string>;
  ok: boolean;
  ms: number;
  preview: string;
}

export interface ServerMsg {
  type: string;
  sender?: string;
  msg?: string;
  id?: number;
  target?: string | null;
  users?: string[];
  status?: 'pending' | 'done';
  items?: unknown[];
  code?: string;
  before_id?: number;
  more?: boolean;
  state?: LinkState;
  detail?: string;
  /* 图片消息 */
  image?: string;
  msg_type?: string;
  /* Agent 工具调用记录 */
  steps?: ToolStep[];
  scheduled?: boolean;
  scope?: 'private' | 'group';
  /** 'main' | 'agent'：这条 Agent 消息该落在哪个会话里 */
  thread?: string;
  /** history 消息专用：读的是不是我与 Agent 的私聊 */
  agent?: boolean;
  /* 定时总结状态 */
  enabled?: boolean;
  seconds?: number;
  /* 桥握手：图片服务地址 */
  image_base?: string;
  /** pong 回显的发起时间戳（ms），用于算 RTT */
  t?: number;
  /** unread 回执：每个会话离线期间攒了多少条、上次读到哪（与 todos 的 items 共用字段） */
  unread_items?: UnreadItem[];
  /** recall 撤回：id 指向被撤回的那条消息 */
  room_id?: number;
  /** group 消息里的 @提及（只含真实存在的用户名） */
  mentions?: string[];
}

export interface HistoryItem {
  id: number;
  sender: string;
  content: string;
  msg_type: string;
  created_at: string | null;
}

export interface TodoItem {
  id?: number;
  content?: string;
  status?: string;
  assignee?: string | null;
}

export type SendMsg =
  | { type: 'login' | 'register'; user_id: string; password: string }
  | { type: 'group'; msg: string; image?: string }
  | { type: 'private'; target: string; msg: string; image?: string }
  | { type: 'agent'; msg: string; scope: 'private' | 'group'; include_private?: boolean }
  | { type: 'history'; limit?: number; before_id?: number; target?: string; agent?: boolean }
  | { type: 'todos' }
  | { type: 'ping'; t: number }
  | { type: 'read'; id?: number; target?: string; agent?: boolean }
  | { type: 'recall'; id: number }
  | { type: 'autosummary'; action: 'status' | 'on' | 'off' | 'now'; minutes?: number }
  | { type: 'reconnect' };

export type EventKind = 'group' | 'private' | 'agent' | 'ask' | 'recall' | 'system' | 'error';

/** 一条渲染单元：聊天记录、系统提示或错误提示 */
export interface ChatEvent {
  key: string;
  kind: EventKind;
  sender: string;
  text: string;
  time: string;
  date: string;
  stamp: number;
  id?: number;
  status?: 'pending' | 'done';
  scope?: 'private' | 'group';
  code?: string;
  /** 图片消息：图片服务上的文件名 */
  image?: string;
  /** Agent 本轮真实执行的工具调用 */
  steps?: ToolStep[];
  scheduled?: boolean;
  /** 这条是自己发给 Agent 的提问，界面上加一条灰色备注 */
  agentScope?: 'private' | 'group';
  /** 这条消息 @了谁 */
  mentions?: string[];
}

export interface UnreadItem {
  /** 其中有多少条 @了我 */
  mentions?: number;
  /** 房间名：main / agent:alice / pm:a:b */
  room: string;
  room_id: number;
  unread: number;
  last_read_id: number;
  max_id: number;
}

export interface ThreadState {
  events: ChatEvent[];
  /** 已请求过首屏历史 */
  loaded: boolean;
  /** 服务端说还有更早的 */
  more: boolean;
  loading: boolean;
  unread: number;
  /** 未读里有没有 @我：徽标显示成 @ 而不是数字 */
  mentioned: boolean;
  /** 离线未读：登录时服务端告诉我"上次读到 id"，历史里在这之后插一条分界线 */
  offline?: { count: number; sinceId: number; mentions?: number };
}

export const MAIN = 'main';
/** 我和 Agent 的私聊会话 */
export const AGENT = 'agent';

export const pmThread = (user: string) => `pm:${user}`;

export const threadUser = (thread: string) => thread.slice('pm:'.length);

export const PAGE_SIZE = 20;
