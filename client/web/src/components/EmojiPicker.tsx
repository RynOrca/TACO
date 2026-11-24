import { useEffect, useRef, useState } from 'react';
import { EMOJI_GROUPS } from '../emoji';

export function EmojiPicker({ onPick }: { onPick: (emoji: string) => void }) {
  const [open, setOpen] = useState(false);
  const [group, setGroup] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className="emoji" ref={box}>
      <button
        type="button"
        className={`chip${open ? ' on' : ''}`}
        onClick={() => setOpen((v) => !v)}
        title="表情"
        aria-expanded={open}
      >
        表情
      </button>
      {open && (
        <div className="emoji-panel">
          <div className="emoji-tabs">
            {EMOJI_GROUPS.map((item, i) => (
              <button
                type="button"
                key={item.label}
                className={i === group ? 'on' : ''}
                onClick={() => setGroup(i)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="emoji-grid">
            {EMOJI_GROUPS[group].items.map((emoji) => (
              <button
                type="button"
                key={emoji}
                onClick={() => {
                  onPick(emoji);
                  setOpen(false);
                }}
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
