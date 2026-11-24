import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import { buildRows } from '../rows';
import type { ChatEvent } from '../types';
import { Message, Note } from './Message';

interface Props {
  events: ChatEvent[];
  me: string | null;
  imageBase: string;
  hasMore: boolean;
  loading: boolean;
  prependToken: number;
  bottomToken: number;
  onLoadOlder: () => void;
}

export function Transcript({
  events,
  me,
  imageBase,
  hasMore,
  loading,
  prependToken,
  bottomToken,
  onLoadOlder,
}: Props) {
  const stream = useRef<HTMLDivElement>(null);
  const stuck = useRef(true);
  const anchor = useRef<{ height: number; top: number } | null>(null);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const rows = useMemo(() => buildRows(events), [events]);

  const toBottom = (smooth = false) => {
    const el = stream.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' });
    stuck.current = true;
    setAwayFromBottom(false);
  };

  useLayoutEffect(() => {
    toBottom();
  }, []);

  useLayoutEffect(() => {
    if (stuck.current) toBottom();
  }, [bottomToken]);

  // 向上补充历史时把视口钉在原地，而不是跳到最上面
  useLayoutEffect(() => {
    const el = stream.current;
    const pinned = anchor.current;
    if (!el || !pinned) return;
    el.scrollTop = pinned.top + (el.scrollHeight - pinned.height);
    anchor.current = null;
  }, [prependToken]);

  const onScroll = () => {
    const el = stream.current;
    if (!el) return;
    const gap = el.scrollHeight - el.scrollTop - el.clientHeight;
    stuck.current = gap < 40;
    setAwayFromBottom(gap >= 40);
    if (el.scrollTop < 48 && hasMore && !loading) {
      anchor.current = { height: el.scrollHeight, top: el.scrollTop };
      onLoadOlder();
    }
  };

  return (
    <div className="stream-wrap">
      <div className="stream" ref={stream} onScroll={onScroll}>
        {events.length > 0 && (loading || hasMore) && (
          <div className="stream-hint">
            {loading ? '正在加载更早的消息…' : '滚到顶部加载更早的消息'}
          </div>
        )}

        {rows.length === 0 ? (
          <div className="empty">
            <p className="empty-t">还没有消息</p>
            <p>直接在下面的输入框说话，会广播到 main 房间。</p>
            <ul>
              <li>
                <code>@Agent 问题</code> 在群里公开回答
              </li>
              <li>
                <code>/agent 问题</code> 只回给自己
              </li>
              <li>
                <code>/pm 用户名 消息</code> 发私聊
              </li>
              <li>
                <code>/help</code> 查看全部指令和功能说明
              </li>
            </ul>
          </div>
        ) : (
          rows.map((row) => {
            if (row.type === 'day') {
              return (
                <div className="day" key={row.key}>
                  <span>{row.label}</span>
                </div>
              );
            }
            if (row.type === 'note') {
              return <Note key={row.key} tone={row.tone} items={row.items} />;
            }
            return (
              <Message
                key={row.key}
                event={row.event}
                cont={row.cont}
                me={me}
                imageBase={imageBase}
              />
            );
          })
        )}
      </div>

      {awayFromBottom && (
        <button className="jump" onClick={() => toBottom(true)}>
          回到最新
        </button>
      )}
    </div>
  );
}
