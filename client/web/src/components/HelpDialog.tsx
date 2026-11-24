import { useEffect } from 'react';

const COMMANDS: { key: string; desc: string }[] = [
  { key: '@Agent 问题', desc: '在群里公开提问，答案发回群里（所有人可见）' },
  { key: '/agent 问题', desc: '只回给我，问答会进左侧「Agent」会话，只有我能看到' },
  { key: '/agent@group 问题', desc: '指定在群里公开回答' },
  { key: '/auto 5', desc: '让 Agent 每 5 分钟自动总结一次群聊（1-120 分钟）' },
  { key: '/auto now', desc: '立刻总结一次（不受"新消息条数"门槛限制）' },
  { key: '/auto off', desc: '关闭定时总结；只发 /auto 可以查当前状态' },
  { key: '/pm 用户名 消息', desc: '发私聊，只有对方能看到，Agent 读不到' },
  { key: '/register 用户名 密码', desc: '注册新账号（密码用 PBKDF2-SHA256 加盐后存 SQLite）' },
  { key: '/login 用户名 密码', desc: '登录；同一个账号重复登录会踢掉旧连接' },
  { key: '/help', desc: '打开这个说明' },
];

const SHORTCUTS: { key: string; desc: string }[] = [
  { key: 'Enter', desc: '发送消息' },
  { key: 'Shift + Enter', desc: '在输入框里换行' },
  { key: '群聊 / 私聊 / Agent 只回我 / Agent 群内公开', desc: '输入框上方的模式切换，决定这条消息发给谁' },
  { key: '表情', desc: '插入 emoji；整条消息只有 1-3 个表情时会放大显示' },
  { key: '图片 / Ctrl + V', desc: '选图或直接粘贴截图（自动压到最大边 1280 再上传）' },
  { key: '回到最新', desc: '往上翻历史后，右下角出现这个按钮' },
];

const FEATURES: { key: string; desc: string }[] = [
  { key: '群聊广播', desc: '一个 main 房间，一条消息发给所有在线成员' },
  { key: '私聊隔离', desc: '两人一对一的房间；Agent 永远读不到两个人的私聊' },
  {
    key: 'Agent 能力',
    desc: '读群聊原文、按关键词检索、读服务器当前时间、联网搜索、把结论存成总结/待办；每次调用都会在回答卡片里逐条列出（名字、参数、耗时、结果预览）',
  },
  {
    key: '包含私聊的总结',
    desc: '右栏勾选「总结时把我与 Agent 的私聊也算进去」后，Agent 才能读 agent:<我> 这一份记录一起总结；不勾就只总结群聊',
  },
  { key: '历史翻页', desc: '首屏 20 条，滚到顶部自动加载更早的一页，视口位置不会跳' },
  { key: '定时总结', desc: '到点自动总结群聊并广播；有新消息才会总结' },
];

function Row({ item }: { item: { key: string; desc: string } }) {
  return (
    <div className="help-row">
      <code className="kbd">{item.key}</code>
      <span>{item.desc}</span>
    </div>
  );
}

export function HelpDialog({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label="使用说明">
      <div className="sheet wide">
        <div className="sheet-head">
          <span className="mark">T</span>
          <span className="sheet-title">使用说明</span>
          <span className="sheet-sub">TACO 怎么用</span>
          <button type="button" className="sheet-close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </div>

        <p className="help-lead">
          输入框里直接打字就是群聊；下面这些指令以 <code>/</code> 开头，或者用 <code>@Agent</code> 提到
          Agent。按 <code>Esc</code> 关闭本窗口。
        </p>

        <h3 className="help-h">指令</h3>
        <div className="help-list">
          {COMMANDS.map((item) => (
            <Row key={item.key} item={item} />
          ))}
        </div>

        <h3 className="help-h">快捷操作</h3>
        <div className="help-list">
          {SHORTCUTS.map((item) => (
            <Row key={item.key} item={item} />
          ))}
        </div>

        <h3 className="help-h">功能一览</h3>
        <div className="help-list">
          {FEATURES.map((item) => (
            <Row key={item.key} item={item} />
          ))}
        </div>

        <div className="sheet-foot">
          <button type="button" className="btn primary" onClick={onClose}>
            知道了
          </button>
        </div>
      </div>
    </div>
  );
}
