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

export interface MsgRow {
  type: 'msg';
  key: string;
  event: ChatEvent;
  cont: ChatEvent[];
}

export type Row = DayRow | NoteRow | MsgRow;

/** 同一个人 2 分钟内连着发的消息并成一组，靠头像和名字只出现一次来降噪 */
const GROUP_WINDOW = 120_000;

export function buildRows(events: ChatEvent[]): Row[] {
  const rows: Row[] = [];
  let day = '';
  let last: MsgRow | null = null;

  for (const event of events) {
    if (event.date !== day) {
      day = event.date;
      rows.push({ type: 'day', key: `day:${day}`, label: dateLabel(day) });
      last = null;
    }

    if (event.kind === 'system' || event.kind === 'error') {
      const tone = event.kind === 'error' ? 'error' : 'system';
      const prev = rows[rows.length - 1];
      const item = { key: event.key, code: event.code, text: event.text };
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
