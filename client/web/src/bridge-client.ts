import type { LinkState, SendMsg, ServerMsg } from './types';

interface Handlers {
  onServer: (msg: ServerMsg) => void;
  onLink: (state: LinkState, detail: string) => void;
  onHello: (imageBase: string) => void;
}

function bridgeUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/ws`;
}

/**
 * 与 Python 桥之间的 WebSocket 连接。
 * 断线自动重连（指数退避，最长 4s），重连成功后由上层重新拉历史。
 */
export class Bridge {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private timer: number | null = null;
  private disposed = false;
  private readonly url = bridgeUrl();

  constructor(private readonly handlers: Handlers) {}

  connect(): void {
    if (this.disposed) return;
    this.handlers.onLink('connecting', this.attempt ? '正在重连…' : '正在连接本地桥…');
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.handlers.onLink('open', '');
    };
    ws.onmessage = (ev) => {
      let msg: ServerMsg;
      try {
        msg = JSON.parse(ev.data as string) as ServerMsg;
      } catch {
        return;
      }
      if (msg.type === 'link') {
        this.handlers.onLink(msg.state ?? 'closed', msg.detail ?? '');
        return;
      }
      if (msg.type === 'hello') {
        this.handlers.onHello(msg.image_base ?? '');
        return;
      }
      this.handlers.onServer(msg);
    };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      if (this.disposed) return;
      this.handlers.onLink('closed', '本地桥已断开');
      this.scheduleRetry();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleRetry(): void {
    if (this.timer !== null) return;
    const delay = Math.min(4000, 400 * 2 ** this.attempt++);
    this.timer = window.setTimeout(() => {
      this.timer = null;
      this.connect();
    }, delay);
  }

  send(msg: SendMsg): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    this.ws.send(JSON.stringify(msg));
    return true;
  }

  dispose(): void {
    this.disposed = true;
    if (this.timer !== null) window.clearTimeout(this.timer);
    this.ws?.close();
  }
}
