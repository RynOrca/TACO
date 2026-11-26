import { useEffect, useState } from 'react';
import { RichText } from '../rich';
import { fullStamp } from '../time';
import type { ChatEvent, ToolStep } from '../types';
import { isEmojiOnly } from '../emoji';

const initials = (name: string) => (name || '?').trim().charAt(0).toUpperCase() || '?';

const stampTitle = (event: ChatEvent) => fullStamp(new Date(event.stamp));

function ScopeBadge({ scope }: { scope?: 'private' | 'group' }) {
  if (!scope) return <span className="tag">Agent</span>;
  return <span className="tag">{scope === 'group' ? '群内公开' : '只回我'}</span>;
}

function StepRow({ step, index }: { step: ToolStep; index: number }) {
  const argText = Object.entries(step.args)
    .map(([k, v]) => `${k}=${v}`)
    .join(', ');
  return (
    <div className="step">
      <span className={`step-i${step.ok ? '' : ' bad'}`}>{index + 1}</span>
      <code className="step-name">
        {step.name}({argText})
      </code>
      <span className={`step-r${step.ok ? '' : ' bad'}`}>{step.ms} ms</span>
      {step.preview && <p className="step-out">{step.preview}</p>}
    </div>
  );
}

function AgentCard({ event, me }: { event: ChatEvent; me: string | null }) {
  const pending = event.status === 'pending';
  const steps = event.steps ?? [];
  const known = event.steps !== undefined;
  // 等待时长：超过 45 秒就提示可能超时，别让人对着「正在思考」发呆
  const [, tick] = useState(0);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(timer);
  }, [pending]);
  const waited = pending ? Math.max(0, Math.round((Date.now() - event.stamp) / 1000)) : 0;
  const title = pending
    ? waited >= 45
      ? `${event.text} · 已等 ${waited}s，可能超时了，可以再问一次`
      : `${event.text} · ${waited}s`
    : event.scheduled
      ? '定时自动总结 · 服务端调度'
      : !known
        ? '历史记录 · 工具调用细节未保存'
        : steps.length
          ? `真实工具调用 ${steps.length} 次`
          : '未调用工具，直接回答';
  return (
    <div className={`agent${pending ? ' pending' : ''}`}>
      <div className="agent-top">
        <span className="badge">AGENT</span>
        <span className="agent-ttl">{title}</span>
      </div>
      {pending && (
        <div className="sk">
          <i />
          <i />
        </div>
      )}
      {!pending && steps.length > 0 && (
        <div className="steps">
          {steps.map((step, i) => (
            <StepRow key={`${step.name}-${i}`} step={step} index={i} />
          ))}
        </div>
      )}
      {!pending && (
        <div className="agent-out">
          <RichText text={event.text} me={me} />
        </div>
      )}
    </div>
  );
}

const KIB = 1024;

function humanSize(bytes: number): string {
  if (!bytes) return '';
  if (bytes < KIB) return `${bytes} B`;
  if (bytes < KIB * KIB) return `${(bytes / KIB).toFixed(0)} KB`;
  return `${(bytes / KIB / KIB).toFixed(1)} MB`;
}

const EXT_ICON: Record<string, string> = {
  '.pdf': 'PDF',
  '.zip': 'ZIP',
  '.doc': 'DOC',
  '.docx': 'DOC',
  '.xls': 'XLS',
  '.xlsx': 'XLS',
  '.ppt': 'PPT',
  '.pptx': 'PPT',
  '.mp3': 'AUD',
  '.wav': 'AUD',
  '.mp4': 'VID',
};

function fileBadge(name: string): string {
  const dot = name.lastIndexOf('.');
  const ext = dot >= 0 ? name.slice(dot).toLowerCase() : '';
  return EXT_ICON[ext] ?? (ext ? ext.slice(1, 4).toUpperCase() : 'FILE');
}

function FileCard({
  attachment,
  imageBase,
}: {
  attachment: NonNullable<ChatEvent['attachment']>;
  imageBase: string;
}) {
  const href = `${imageBase}/file/${attachment.ref}`;
  return (
    <a className="filecard" href={href} target="_blank" rel="noreferrer" download={attachment.name}>
      <span className="filecard-ico">{fileBadge(attachment.name)}</span>
      <span className="filecard-main">
        <span className="filecard-name">{attachment.name}</span>
        <span className="filecard-meta">
          {humanSize(attachment.size) || '点击下载'}
        </span>
      </span>
    </a>
  );
}

function Body({
  event,
  imageBase,
  me,
}: {
  event: ChatEvent;
  imageBase: string;
  me: string | null;
}) {
  if (event.image) {
    return (
      <figure className="pic">
        <img
          src={`${imageBase}/img/${event.image}`}
          alt="图片消息"
          loading="lazy"
          onClick={() => window.open(`${imageBase}/img/${event.image}`, '_blank')}
        />
      </figure>
    );
  }
  if (event.attachment) {
    return <FileCard attachment={event.attachment} imageBase={imageBase} />;
  }
  if (isEmojiOnly(event.text)) {
    return <div className="body big-emoji">{event.text.trim()}</div>;
  }
  return (
    <div className="body">
      <RichText text={event.text} me={me} />
    </div>
  );
}

const RECALL_WINDOW = 120_000;

export function Message({
  event,
  cont,
  me,
  imageBase,
  onRecall,
}: {
  event: ChatEvent;
  cont: ChatEvent[];
  me: string | null;
  imageBase: string;
  onRecall: (id: number) => void;
}) {
  const agent = event.kind === 'agent';
  const mine = !agent && event.sender === me;
  const cls = [
    'msg',
    mine ? 'mine' : '',
    agent ? 'is-agent' : '',
    event.kind === 'private' ? 'is-pm' : '',
    event.image ? 'has-image' : '',
  ]
    .filter(Boolean)
    .join(' ');

  return (
    <article className={cls}>
      <div className={`ava${agent ? ' ai' : mine ? ' self' : ''}`}>
        {agent ? 'AI' : initials(event.sender)}
      </div>
      <div className="msg-main">
        <header className="head">
          <b className="who">{agent ? 'Agent' : event.sender}</b>
          {agent && <ScopeBadge scope={event.scope} />}
          {agent && event.scheduled && <span className="tag">定时总结</span>}
          {event.kind === 'private' && <span className="tag">私聊</span>}
          {mine && <span className="tag">我</span>}
          {mine && typeof event.id === 'number' && Date.now() - event.stamp < RECALL_WINDOW && (
            <button
              type="button"
              className="recall"
              title="撤回这条消息（2 分钟内）"
              onClick={() => onRecall(event.id!)}
            >
              撤回
            </button>
          )}
          {event.agentScope && (
            <span className="tag soft">
              (Agent {event.agentScope === 'group' ? '群内公开' : '只回我'})
            </span>
          )}
          <time className="tm" title={stampTitle(event)}>
            {event.time}
          </time>
        </header>

        {agent ? (
          <AgentCard event={event} me={me} />
        ) : (
          <Body event={event} imageBase={imageBase} me={me} />
        )}

        {cont.map((item, i) => {
          // 同一条消息组里时间没变就不再重复印一遍，避免一列"21:38"堆在右边
          const repeat = (i > 0 ? cont[i - 1].time : event.time) === item.time;
          return (
            <div className="cont" key={item.key}>
              <Body event={item} imageBase={imageBase} me={me} />
              <time className="tm" title={stampTitle(item)} data-repeat={repeat || undefined}>
                {repeat ? '' : item.time}
              </time>
            </div>
          );
        })}
      </div>
    </article>
  );
}

export function Note({
  tone,
  items,
}: {
  tone: 'system' | 'error';
  items: { key: string; code?: string; text: string }[];
}) {
  // 左对齐的窄栏 + 左侧标签：每条系统提示单独一行，多行内容（/game 帮助）保持原有缩进
  return (
    <div className={`note ${tone}`}>
      <span className="note-k" aria-hidden="true">
        {tone === 'error' ? 'ERR' : 'SYS'}
      </span>
      <div className="note-lines">
        {items.map((item) => (
          <p key={item.key}>
            {item.code && <code>{item.code}</code>}
            {item.text}
          </p>
        ))}
      </div>
    </div>
  );
}
