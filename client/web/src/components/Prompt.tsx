import { useEffect, useRef, useState } from 'react';

export function Prompt({
  title,
  label,
  subtitle,
  initial = '',
  okText = '确定',
  onCancel,
  onOk,
}: {
  title: string;
  label: string;
  subtitle?: string;
  initial?: string;
  okText?: string;
  onCancel: () => void;
  onOk: (value: string) => void;
}) {
  const [value, setValue] = useState(initial);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);

  const ok = () => {
    const text = value.trim();
    if (text) onOk(text);
  };

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="sheet">
        <div className="sheet-head">
          <span className="sheet-title">{title}</span>
        </div>
        {subtitle && <p className="sheet-note">{subtitle}</p>}
        <label className="field-row">
          <span>{label}</span>
          <input
            ref={input}
            className="field"
            value={value}
            spellCheck={false}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && ok()}
          />
        </label>
        <div className="sheet-foot">
          <button type="button" className="btn primary" onClick={ok}>
            {okText}
          </button>
          <button type="button" className="btn" onClick={onCancel}>
            取消
          </button>
        </div>
      </div>
    </div>
  );
}
