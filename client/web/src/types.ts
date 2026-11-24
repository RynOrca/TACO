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
  /* 定时总结状态 */
  enabled?: boolean;
  seconds?: number;
  /* 桥握手：图片服务地址 */
  image_base?: string;
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
  | { type: 'agent'; msg: string; scope: 'private' | 'group' }
  | { type: 'history'; limit?: number; before_id?: number; target?: string }
  | { type: 'todos' }
  | { type: 'autosummary'; action: 'status' | 'on' | 'off' | 'now'; minutes?: number }
  | { type: 'reconnect' };

export type EventKind = 'group' | 'private' | 'agent' | 'system' | 'error';

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
}

export interface ThreadState {
  events: ChatEvent[];
  /** 已请求过首屏历史 */
  loaded: boolean;
  /** 服务端说还有更早的 */
  more: boolean;
  loading: boolean;
  unread: number;
}

export const MAIN = 'main';

export const pmThread = (user: string) => `pm:${user}`;

export const threadUser = (thread: string) => thread.slice('pm:'.length);

export const PAGE_SIZE = 20;
