const pad = (n: number) => String(n).padStart(2, '0');

export const timeOf = (d: Date) => `${pad(d.getHours())}:${pad(d.getMinutes())}`;

export const dateKeyOf = (d: Date) =>
  `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export const fullStamp = (d: Date) =>
  `${dateKeyOf(d)} ${timeOf(d)}:${pad(d.getSeconds())}`;

const WEEKDAY = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

/** 今天 / 昨天 / 3月4日 周三 */
export function dateLabel(key: string): string {
  const now = new Date();
  if (key === dateKeyOf(now)) return '今天';
  const yesterday = new Date(now.getTime() - 86400000);
  if (key === dateKeyOf(yesterday)) return '昨天';
  const [y, m, d] = key.split('-').map(Number);
  const date = new Date(y, m - 1, d);
  const suffix = y === now.getFullYear() ? '' : `${y}年`;
  return `${suffix}${m}月${d}日 ${WEEKDAY[date.getDay()]}`;
}

/** 服务端给的是不带时区的本地时间字符串，直接交给 Date 解析 */
export function parseStamp(value: string | null | undefined): number {
  if (!value) return Date.now();
  const t = new Date(value).getTime();
  return Number.isNaN(t) ? Date.now() : t;
}
