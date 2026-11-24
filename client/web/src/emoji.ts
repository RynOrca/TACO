/** 表情面板的候选集合：够用即可，全部是 Unicode 字符，跟着消息走不加协议字段 */
export const EMOJI_GROUPS: { label: string; items: string[] }[] = [
  {
    label: '常用',
    items: ['😀', '😄', '😁', '😆', '😅', '🤣', '😂', '🙂', '😉', '😊', '😍', '😘', '😜', '🤔', '😐', '😴', '😭', '😤', '😱', '🥳'],
  },
  {
    label: '手势',
    items: ['👍', '👎', '👌', '✌️', '🙏', '👏', '💪', '🤝', '👀', '🫡', '🤙', '👋', '✍️', '🧠', '🫠', '🤷'],
  },
  {
    label: '符号',
    items: ['✅', '❌', '⚠️', '🔥', '💡', '📌', '📎', '📝', '📅', '⏰', '🚀', '🐛', '🎉', '💯', '⭐', '❤️'],
  },
];

const EMOJI_ONLY = /^(?:\p{Extended_Pictographic}|\p{Emoji_Component}|\uFE0F|\u200D|\s){1,3}$/u;

/** 整条消息只有 1-3 个表情时放大显示（Emoji 只在图片消息里出现时才算） */
export function isEmojiOnly(text: string): boolean {
  const trimmed = text.trim();
  if (!trimmed || trimmed.length > 12) return false;
  return EMOJI_ONLY.test(trimmed) && !/\p{L}|\p{N}/u.test(trimmed);
}
