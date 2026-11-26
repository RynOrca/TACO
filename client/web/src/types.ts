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
  /** muted 回执：当前被禁言的人和到期时间（与 userlist 的 users 共用字段，类型按 type 区分） */
  mutes?: MuteInfo[];
  /** 附件消息：文件名（附件服务上的存储名） */
  file?: string;
  /** 附件附加信息 */
  meta?: AttachmentMeta | null;
  /* 井字棋结构化状态 */
  action?: string;
  board?: string[];
  turn?: 'X' | 'O';
  over?: boolean;
  result?: string;
  score?: { win: number; lose: number; draw: number };
  /** game 消息：对局 id（字符串，和消息的 id 不是一回事）、玩家、观战数、双方战绩 */
  game_id?: string;
  players?: { X: string; O: string };
  vs_agent?: boolean;
  winner?: 'X' | 'O' | null;
  legal?: number[];
  spectators?: number;
  scores?: Record<string, { win: number; lose: number; draw: number }>;
  rematch?: { votes: string[]; deadline: number; window: number };
  from?: string;
  ttl?: number;
}

export interface HistoryItem {
  meta?: AttachmentMeta | null;
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

/** 井字棋面板状态（只发给下棋的本人） */
export interface GameState {
  /** 对局 id：一人一局，观战靠它区分 */
  id: string;
  players: { X: string; O: string };
  /** 对手是不是 Agent（决定了提示文案和是否需要等模型） */
  vs_agent: boolean;
  board: string[];               // 9 格：" " / "X" / "O"
  turn: 'X' | 'O';
  over: boolean;
  result: '' | 'win' | 'lose' | 'draw';
  winner: 'X' | 'O' | null;
  legal: number[];
  spectators: number;
  scores: Record<string, { win: number; lose: number; draw: number }>;
  /** 结束后的"再来一局"投票：双方都在窗口内确认才开新局 */
  rematch: { votes: string[]; deadline: number; window: number };
}

export interface GameInvite {
  from: string;
  at: number;
  ttl: number;
}

export type SendMsg =
  | { type: 'login' | 'register'; user_id: string; password: string }
  | {
      type: 'group';
      msg: string;
      image?: string;
      file?: string;
      name?: string;
      size?: number;
      mime?: string;
    }
  | {
      type: 'private';
      target: string;
      msg: string;
      image?: string;
      file?: string;
      name?: string;
      size?: number;
      mime?: string;
    }
  | { type: 'agent'; msg: string; scope: 'private' | 'group'; include_private?: boolean }
  | { type: 'history'; limit?: number; before_id?: number; target?: string; agent?: boolean }
  | { type: 'todos' }
  | { type: 'ping'; t: number }
  | { type: 'read'; id?: number; target?: string; agent?: boolean }
  | { type: 'recall'; id: number }
  | { type: 'mute'; action: 'mute' | 'unmute' | 'list'; target?: string; minutes?: number }
  | { type: 'autosummary'; action: 'status' | 'on' | 'off' | 'now'; minutes?: number }
  | { type: 'task'; text: string }
  | { type: 'game'; text: string }
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
  /** 附件（图片或文件）的存储名 + 原名/大小 */
  attachment?: { ref: string; kind: 'image' | 'file'; name: string; size: number; mime?: string };
}

export interface AttachmentMeta {
  name?: string;
  size?: number;
  mime?: string;
}

export interface MuteInfo {
  user_id: string;
  until_at: string;
  by_user?: string | null;
  reason?: string | null;
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
