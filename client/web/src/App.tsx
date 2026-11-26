import { useEffect, useState } from 'react';
import { useChat } from './use-chat';
import { threadOf } from './store';
import { AGENT, MAIN, threadUser } from './types';
import { Sidebar, ConvHead } from './components/Sidebar';
import { Transcript } from './components/Transcript';
import { Composer } from './components/Composer';
import { SidePanel } from './components/SidePanel';
import { AuthGate } from './components/AuthGate';
import { Prompt } from './components/Prompt';
import { HelpDialog } from './components/HelpDialog';
import { Arena } from './components/Arena';
import { involvesMe } from './components/GameBoard';

export default function App() {
  const chat = useChat();
  const { state } = chat;
  const [dialog, setDialog] = useState<'search' | null>(null);
  const thread = threadOf(state, state.active);
  const isPM = state.active !== MAIN;
  const target =
    state.active === AGENT ? 'Agent' : isPM ? `@${threadUser(state.active)}` : 'main';

  const layout = state.layout;
  const allGames = Object.values(state.games);
  const mineGame = allGames.find((g) => involvesMe(g, state.me)) ?? null;
  const focusedGame = state.gameFocus ? state.games[state.gameFocus] ?? null : null;
  const arenaGame = mineGame ?? focusedGame;

  // Esc：从专注/剧场回到聊天（对局不中断）
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      if (state.auth.open || state.help || dialog) return;
      if (layout !== 'chat') chat.setLayout('chat');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [layout, state.auth.open, state.help, dialog, chat]);

  const search = (keyword: string) => {
    setDialog(null);
    chat.askAgent(`用 search_chat_history 检索关键词“${keyword}”，把命中的原文贴出来`, 'private');
  };

  return (
    <div className="app" data-layout={layout}>
      <Sidebar
        state={state}
        collapsed={layout !== 'chat'}
        openThread={(thread) => {
          chat.openThread(thread);
          if (layout !== 'chat' && !arenaGame) chat.setLayout('chat');
        }}
        openAuth={chat.openAuth}
        onReconnect={chat.reconnect}
      />

      <main className="conv">
        <ConvHead
          state={state}
          onSearch={() => setDialog('search')}
          onSummary={() =>
            chat.askAgent('总结一下本群最近的讨论，并把待办事项列出来', 'group')
          }
        />

        <Transcript
          events={thread.events}
          offline={thread.offline}
          me={state.me}
          imageBase={state.imageBase}
          hasMore={thread.more}
          loading={thread.loading}
          prependToken={state.prependToken}
          bottomToken={state.bottomToken}
          onLoadOlder={chat.loadOlder}
          onRecall={chat.recall}
        />

        <Composer
          thread={state.active}
          target={target}
          isPM={isPM}
          members={[...state.online.filter((u) => u !== state.me), 'Agent']}
          disabled={!state.me || state.link !== 'open'}
          onSend={chat.sendText}
          onImage={chat.sendFile}
        />
      </main>

      {layout !== 'chat' && (
        <Arena
          game={arenaGame}
          me={state.me}
          invite={state.gameInvite}
          onMove={chat.gameMove}
          onRematch={chat.gameRematch}
          onHit={chat.gameHit}
          onStand={chat.gameStand}
          onStartKind={chat.gameStartKind}
          onQuit={chat.gameQuit}

          onAccept={chat.gameAccept}
          onDecline={chat.gameDecline}
          onClose={() => chat.setLayout('chat')}
          onTheater={() => chat.setLayout(layout === 'theater' ? 'game' : 'theater')}
        />
      )}

      <SidePanel
        state={state}
        askAgent={chat.askAgent}
        refreshTodos={chat.refreshTodos}
        autoSummary={chat.autoSummary}
        setIncludePrivate={chat.setIncludePrivate}
        onGameInvite={chat.gameInvite}
        onGameAccept={chat.gameAccept}
        onGameDecline={chat.gameDecline}
        onGameFocus={chat.gameFocus}
        onEnterArena={() => chat.setLayout('game')}
        onStartKind={chat.gameStartKind}
      />

      {state.auth.open && (
        <AuthGate
          state={state}
          onSubmit={chat.submitAuth}
          onUser={chat.setAuthUser}
          onReconnect={chat.reconnect}
          onClose={() => chat.openAuth(false)}
        />
      )}

      {state.help && <HelpDialog onClose={() => chat.setHelp(false)} />}

      {dialog === 'search' && (
        <Prompt
          title="搜索历史"
          label="关键词"
          subtitle={`在 room_id ${state.roomId ?? '-'} 的历史消息里检索，由服务端 Agent 调 search_chat_history 执行`}
          okText="让 Agent 检索"
          onCancel={() => setDialog(null)}
          onOk={search}
        />
      )}
    </div>
  );
}
