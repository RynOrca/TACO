import type { ChatEvent } from './types';
import { dateLabel } from './time';

export interface DayRow {
  type: 'day';
  key: string;
  label: string;
}

export interface NoteRow {
  type: 'note';
  key: string;
  tone: 'system' | 'error';
  items: { key: string; code?: string; text: string }[];
}

export interface DividerRow {
  type: 'divider';
  key: string;
  label: string;
}

export interface MsgRow {
  type: 'msg';
  key: string;
  event: ChatEvent;
  cont: ChatEvent[];
}

export type Row = DayRow | NoteRow | MsgRow | DividerRow;

/** 同一个人 2 分钟内连着发的消息并成一组，靠头像和名字只出现一次来降噪 */
const GROUP_WINDOW = 120_000;

export function buildRows(
  events: ChatEvent[],
  offlineSince?: number,
  offlineCount = 0,
): Row[] {
  const rows: Row[] = [];
  let day = '';
  let last: MsgRow | null = null;
  let dividerDrawn = typeof offlineSince !== 'number';

  for (const event of events) {
    // 离线分界线只插一次：第一条"上次读过之后"的消息前面
    if (!dividerDrawn && typeof event.id === 'number' && event.id > offlineSince!) {
      dividerDrawn = true;
      rows.push({
        type: 'divider',
        key: `offline:${offlineSince}`,
        label: `离线期间 ${offlineCount} 条新消息`,
      });
      last = null;
    }

    if (event.date !== day) {
      day = event.date;
      rows.push({ type: 'day', key: `day:${day}`, label: dateLabel(day) });
      last = null;
    }

    if (event.kind === 'system' || event.kind === 'error' || event.kind === 'recall') {
      const tone = event.kind === 'error' ? 'error' : 'system';
      const prev = rows[rows.length - 1];
      const item = {
        key: event.key,
        code: event.code,
        text: event.kind === 'recall' ? event.text || '一条消息被撤回' : event.text,
      };
      if (prev && prev.type === 'note' && prev.tone === tone) {
        prev.items.push(item);
      } else {
        rows.push({ type: 'note', key: `note:${event.key}`, tone, items: [item] });
      }
      last = null;
      continue;
    }

    if (
      last &&
      event.kind !== 'agent' &&
      !event.agentScope &&
      !last.event.agentScope &&
      last.event.kind === event.kind &&
      last.event.sender === event.sender &&
      event.stamp - last.event.stamp <= GROUP_WINDOW &&
      last.event.status !== 'pending'
    ) {
      last.cont.push(event);
      continue;
    }

    last = { type: 'msg', key: event.key, event, cont: [] };
    rows.push(last);
  }

  return rows;
}
