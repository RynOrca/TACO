import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { ComposeMode } from '../use-chat';
import { AGENT } from '../types';
import { EmojiPicker } from './EmojiPicker';

interface Props {
  thread: string;
  target: string;
  isPM: boolean;
  disabled: boolean;
  onSend: (text: string, mode: ComposeMode) => void;
  onImage: (file: File) => Promise<void>;
}

const MODES: { key: ComposeMode; label: string; hint: string }[] = [
  { key: 'chat', label: '聊天', hint: 'Enter 发送，Shift+Enter 换行；@Agent 问题 可以让 Agent 在群里回答' },
  { key: 'agent', label: 'Agent 只回我', hint: '这条作为 Agent 提问，结果只推给你自己' },
  { key: 'agent-group', label: 'Agent 群内公开', hint: '这条作为 Agent 提问，结果广播到群里' },
];

export function Composer({ thread, target, isPM, disabled, onSend, onImage }: Props) {
  const [text, setText] = useState('');
  const [mode, setMode] = useState<ComposeMode>('chat');
  const [uploading, setUploading] = useState(false);
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

  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
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
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDown}
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
