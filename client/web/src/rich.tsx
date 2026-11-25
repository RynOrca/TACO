import type { ReactNode } from 'react';

// 行内：**加粗**、`代码`、@某人（用户名允许中英文、数字、下划线、连字符）
const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|@[\w一-龥-]{1,32})/g;
const BULLET = /^\s*[-*+]\s+/;
const ORDERED = /^\s*(\d+)[.)]\s+/;
const HEADING = /^\s*#{1,6}\s+/;

function inline(text: string, prefix = '', me?: string | null): ReactNode[] {
  const out: ReactNode[] = [];
  const parts = text.split(INLINE);
  parts.forEach((part, i) => {
    if (!part) return;
    const key = `${prefix}${i}`;
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
      out.push(<strong key={key}>{part.slice(2, -2)}</strong>);
    } else if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
      out.push(<code key={key}>{part.slice(1, -1)}</code>);
    } else if (part.length > 1 && part.startsWith('@')) {
      const self = Boolean(me) && part.slice(1) === me;
      out.push(
        <span className={`mention${self ? ' me' : ''}`} key={key}>
          {part}
        </span>,
      );
    } else {
      out.push(<span key={key}>{part}</span>);
    }
  });
  return out;
}

/** 只认 Agent 会用的那点轻量 markdown：加粗、行内代码、列表、标题、空行 */
export function RichText({ text, me }: { text: string; me?: string | null }) {
  const lines = text.split('\n');
  const nodes: ReactNode[] = [];

  lines.forEach((line, i) => {
    const key = `l${i}`;
    if (!line.trim()) {
      nodes.push(<div className="blank" key={key} />);
      return;
    }
    const bullet = BULLET.exec(line);
    const ordered = ORDERED.exec(line);
    const heading = HEADING.exec(line);
    if (bullet) {
      nodes.push(
        <div className="ln li" key={key}>
          <span className="bullet">•</span>
          <span>{inline(line.slice(bullet[0].length), key, me)}</span>
        </div>,
      );
    } else if (ordered) {
      nodes.push(
        <div className="ln li" key={key}>
          <span className="bullet">{ordered[1]}.</span>
          <span>{inline(line.slice(ordered[0].length), key, me)}</span>
        </div>,
      );
    } else if (heading) {
      nodes.push(
        <div className="ln h" key={key}>
          {inline(line.slice(heading[0].length), key, me)}
        </div>,
      );
    } else {
      nodes.push(
        <div className="ln" key={key}>
          {inline(line, key, me)}
        </div>,
      );
    }
  });

  return <div className="rt">{nodes}</div>;
}
