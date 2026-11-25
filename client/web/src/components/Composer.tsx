import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ComposeMode } from '../use-chat';
import { AGENT } from '../types';
import { EmojiPicker } from './EmojiPicker';

interface Props {
  thread: string;
  target: string;
  isPM: boolean;
  disabled: boolean;
  /** 可以 @ 的对象：在线成员 + Agent */
  members: string[];
  onSend: (text: string, mode: ComposeMode) => void;
  onImage: (file: File) => Promise<void>;
}

const MODES: { key: ComposeMode; label: string; hint: string }[] = [
  { key: 'chat', label: '聊天', hint: 'Enter 发送，Shift+Enter 换行；@Agent 问题 可以让 Agent 在群里回答' },
  { key: 'agent', label: 'Agent 只回我', hint: '这条作为 Agent 提问，结果只推给你自己' },
  { key: 'agent-group', label: 'Agent 群内公开', hint: '这条作为 Agent 提问，结果广播到群里' },
];

export function Composer({
  thread,
  target,
  isPM,
  disabled,
  members,
  onSend,
  onImage,
}: Props) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<ComposeMode>('chat');
  const [uploading, setUploading] = useState(false);
  // @ 补全：query 是 @ 后面已经打出来的部分，index 是候选高亮项
  const [mention, setMention] = useState<{ query: string; start: number; index: number } | null>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  // 换会话时回到"聊天"模式，免得在私聊里误把消息发给 Agent
  useEffect(() => setMode('chat'), [thread]);

  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(136, el.scrollHeight)}px`;
  }, [text]);

  const submit = () => {
    const value = text.trim();
    if (disabled || !value) return;
    onSend(value, mode);
    setText('');
    box.current?.focus();
  };

  const candidates = mention
    ? members
        .filter((name) => name.toLowerCase().startsWith(mention.query.toLowerCase()))
        .slice(0, 6)
    : [];

  const applyMention = (name: string) => {
    if (!mention) return;
    const caret = mention.start + mention.query.length + 1;
    const next = `${text.slice(0, mention.start)}@${name} ${text.slice(caret)}`;
    setText(next);
    setMention(null);
    const pos = mention.start + name.length + 2;
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(pos, pos);
    });
  };

  const syncMention = (value: string, caret: number) => {
    const before = value.slice(0, caret);
    const hit = /@([\w一-龥-]*)$/.exec(before);
    if (!hit) {
      setMention(null);
      return;
    }
    setMention({ query: hit[1], start: caret - hit[0].length, index: 0 });
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention && candidates.length) {
      if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        setMention({ ...mention, index: (mention.index + delta + candidates.length) % candidates.length });
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        applyMention(candidates[mention.index] ?? candidates[0]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setMention(null);
        return;
      }
    }
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  const insertEmoji = (emoji: string) => {
    const el = box.current;
    if (!el) {
      setText((prev) => prev + emoji);
      return;
    }
    const start = el.selectionStart ?? text.length;
    const end = el.selectionEnd ?? text.length;
    setText(text.slice(0, start) + emoji + text.slice(end));
    requestAnimationFrame(() => {
      el.focus();
      const caret = start + emoji.length;
      el.setSelectionRange(caret, caret);
    });
  };

  const pickImage = async (file: File | null | undefined) => {
    if (!file || disabled) return;
    setUploading(true);
    try {
      await onImage(file);
    } finally {
      setUploading(false);
    }
  };

  const isAgentThread = thread === AGENT;
  const active = isAgentThread
    ? { key: 'agent' as ComposeMode, label: 'Agent', hint: '在这个会话里发的每句话都是问 Agent，答案只回给你' }
    : (MODES.find((m) => m.key === mode) ?? MODES[0]);
  const chipLabel = (item: (typeof MODES)[number]) =>
    item.key === 'chat' ? (isPM ? '私聊' : '群聊') : item.label;

  return (
    <div className="composer">
      <div className={`box${disabled ? ' box-off' : ''}`}>
        {mention && candidates.length > 0 && (
          <div className="mention-menu">
            {candidates.map((name, i) => (
              <button
                type="button"
                key={name}
                className={i === mention.index ? 'on' : ''}
                onMouseDown={(e) => {
                  e.preventDefault();
                  applyMention(name);
                }}
              >
                @{name}
              </button>
            ))}
            <span className="mention-hint">↑↓ 选择 · Enter 插入 · Esc 取消</span>
          </div>
        )}
        <textarea
          ref={box}
          className="inp"
          rows={1}
          value={text}
          spellCheck={false}
          disabled={disabled}
          placeholder={
            disabled ? '先登录，登录后这里就能发消息' : isAgentThread ? '问 Agent…' : `发送到 ${target}…`
          }
          onChange={(e) => {
            setText(e.target.value);
            syncMention(e.target.value, e.target.selectionStart ?? e.target.value.length);
          }}
          onKeyDown={onKeyDown}
          onBlur={() => setMention(null)}
          onPaste={(e) => {
            const file = Array.from(e.clipboardData.files)[0];
            if (file && file.type.startsWith('image/')) {
              e.preventDefault();
              void pickImage(file);
            }
          }}
        />
        <div className="box-foot">
          {!isAgentThread && MODES.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`chip${item.key === mode ? ' on' : ''}`}
              onClick={() => setMode(item.key)}
            >
              {chipLabel(item)}
            </button>
          ))}
          <EmojiPicker onPick={insertEmoji} />
          <button
            type="button"
            className="chip"
            disabled={disabled || uploading}
            onClick={() => fileInput.current?.click()}
            title="发送图片（也可以直接 Ctrl+V 粘贴截图）"
          >
            {uploading ? '上传中…' : '图片'}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            hidden
            onChange={(e) => {
              void pickImage(e.target.files?.[0]);
              e.target.value = '';
            }}
          />
          <span className="box-hint">{active.hint}</span>
          <button
            type="button"
            className="btn primary send"
            onClick={submit}
            disabled={disabled || !text.trim()}
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
