import { useEffect, useRef, useState } from 'react';
import type { State } from '../store';

interface Props {
  state: State;
  onSubmit: (kind: 'login' | 'register', user: string, password: string) => void;
  onUser: (user: string) => void;
  onReconnect: () => void;
  onClose: () => void;
}

export function AuthGate({ state, onSubmit, onUser, onReconnect, onClose }: Props) {
  const { auth, link, linkDetail, me } = state;
  const [user, setUser] = useState(auth.user || me || '');
  const [password, setPassword] = useState('');
  const userRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    userRef.current?.focus();
  }, []);

  useEffect(() => {
    if (auth.error) userRef.current?.focus();
  }, [auth.error]);

  const submit = (kind: 'login' | 'register') => {
    onUser(user.trim());
    onSubmit(kind, user, password);
  };

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="登录 TACO">
      <div className="sheet">
        <div className="sheet-head">
          <span className="mark">T</span>
          <span className="sheet-title">登录 TACO</span>
          <span className="sheet-sub">TCP-Agent Chatroom Online</span>
          {me && (
            <button type="button" className="sheet-close" onClick={onClose} aria-label="关闭">
              ×
            </button>
          )}
        </div>

        <label className="field-row">
          <span>用户名</span>
          <input
            ref={userRef}
            className="field"
            value={user}
            autoComplete="username"
            spellCheck={false}
            onChange={(e) => setUser(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit('login')}
          />
        </label>

        <label className="field-row">
          <span>密码</span>
          <input
            className="field"
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit('login')}
          />
        </label>

        <p className={`sheet-note${auth.error ? ' bad' : ''}`}>
          {auth.error ??
            (auth.busy
              ? '正在跟服务端核对…'
              : '没有账号就点「注册」建一个，密码用 PBKDF2-SHA256 加盐后落在 SQLite')}
        </p>

        <div className="sheet-foot">
          <button
            type="button"
            className="btn primary"
            disabled={auth.busy}
            onClick={() => submit('login')}
          >
            登录
          </button>
          <button
            type="button"
            className="btn"
            disabled={auth.busy}
            onClick={() => submit('register')}
          >
            注册
          </button>
          <button
            type="button"
            className={`btn ghost link-${link}`}
            onClick={onReconnect}
          >
            {link === 'open' ? '链路正常' : '重连服务端'}
          </button>
        </div>

        {link !== 'open' && (
          <p className="sheet-warn">
            {link === 'connecting' ? '正在连接本地桥…' : linkDetail || '本地桥未连接'}
          </p>
        )}
      </div>
    </div>
  );
}
