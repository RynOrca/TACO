import { useState } from 'react';
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

export default function App() {
  const chat = useChat();
  const { state } = chat;
  const [dialog, setDialog] = useState<'search' | null>(null);
  const thread = threadOf(state, state.active);
  const isPM = state.active !== MAIN;
  const target =
    state.active === AGENT ? 'Agent' : isPM ? `@${threadUser(state.active)}` : 'main';

  const search = (keyword: string) => {
    setDialog(null);
    chat.askAgent(`用 search_chat_history 检索关键词“${keyword}”，把命中的原文贴出来`, 'private');
  };

  return (
    <div className="app">
      <Sidebar
        state={state}
        openThread={chat.openThread}
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

      <SidePanel
        state={state}
        askAgent={chat.askAgent}
        refreshTodos={chat.refreshTodos}
        autoSummary={chat.autoSummary}
        setIncludePrivate={chat.setIncludePrivate}
        onGameMove={chat.gameMove}
        onGameStart={chat.gameStart}
        onGameQuit={chat.gameQuit}
        onGameInvite={chat.gameInvite}
        onGameAccept={chat.gameAccept}
        onGameDecline={chat.gameDecline}
        onGameFocus={chat.gameFocus}
        onGameRematch={chat.gameRematch}
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
