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

function AgentCard({ event }: { event: ChatEvent }) {
  const pending = event.status === 'pending';
  const steps = event.steps ?? [];
  return (
    <div className={`agent${pending ? ' pending' : ''}`}>
      <div className="agent-top">
        <span className="badge">AGENT</span>
        <span className="agent-ttl">
          {pending
            ? event.text
            : event.scheduled
              ? '定时自动总结 · 服务端调度'
              : steps.length
                ? `真实工具调用 ${steps.length} 次`
                : '未调用工具，直接回答'}
        </span>
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
          <RichText text={event.text} />
        </div>
      )}
    </div>
  );
}

function Body({ event, imageBase }: { event: ChatEvent; imageBase: string }) {
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
  if (isEmojiOnly(event.text)) {
    return <div className="body big-emoji">{event.text.trim()}</div>;
  }
  return (
    <div className="body">
      <RichText text={event.text} />
    </div>
  );
}

export function Message({
  event,
  cont,
  me,
  imageBase,
}: {
  event: ChatEvent;
  cont: ChatEvent[];
  me: string | null;
  imageBase: string;
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
          <AgentCard event={event} />
        ) : (
          <Body event={event} imageBase={imageBase} />
        )}

        {cont.map((item, i) => {
          // 同一条消息组里时间没变就不再重复印一遍，避免一列"21:38"堆在右边
          const repeat = (i > 0 ? cont[i - 1].time : event.time) === item.time;
          return (
            <div className="cont" key={item.key}>
              <Body event={item} imageBase={imageBase} />
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
  return (
    <div className={`note ${tone}`}>
      <span className="note-k">{tone === 'error' ? 'ERROR' : 'SYSTEM'}</span>
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
