'use client';

import { useCallback, useEffect, useState } from 'react';
import { useShopkeeperSocket } from '@/hooks/useShopkeeperSocket';
import { useSceneTransition } from '@/hooks/useSceneTransition';
import SceneCanvas from '@/components/SceneCanvas';
import TextStream from '@/components/TextStream';
import StatePanel from '@/components/StatePanel';
import ActivityOverlay from '@/components/ActivityOverlay';
import ConnectionIndicator from '@/components/ConnectionIndicator';
import ChatGate from '@/components/ChatGate';
import ChatPanel from '@/components/ChatPanel';

export default function WindowPage() {
  const {
    layers,
    textEntries,
    windowState,
    currentThought,
    activityLabel,
    connected,
    sendChat,
  } = useShopkeeperSocket();

  const { activeLayers, prevLayers, opacity } = useSceneTransition(layers);

  const [chatToken, setChatToken] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  // Restore token from localStorage on mount
  useEffect(() => {
    const stored = localStorage.getItem('shopkeeper-token');
    if (stored) setChatToken(stored);
  }, []);

  const handleAuthenticated = useCallback((token: string) => {
    setChatToken(token);
    setChatOpen(true);
  }, []);

  const handleChatClose = useCallback(() => {
    setChatOpen(false);
  }, []);

  const weather = activeLayers?.weather ?? '';

  return (
    <div
      className={`window-layout ${chatOpen ? 'window-layout--chat-open' : ''}`}
    >
      {/* Main scene area */}
      <main className="window-main">
        <SceneCanvas
          activeLayers={activeLayers}
          prevLayers={prevLayers}
          opacity={opacity}
          weather={weather}
        />
        <ActivityOverlay label={activityLabel} />
      </main>

      {/* Sidebar: text stream + state + chat gate */}
      <div className="window-sidebar">
        <StatePanel state={windowState} activityLabel={activityLabel} />
        <TextStream entries={textEntries} currentThought={currentThought} />
        {!chatOpen && (
          <ChatGate onAuthenticated={handleAuthenticated} />
        )}
      </div>

      {/* Chat panel slides up from bottom */}
      {chatOpen && chatToken && (
        <ChatPanel
          token={chatToken}
          sendChat={sendChat}
          onClose={handleChatClose}
        />
      )}

      {/* Connection indicator */}
      <ConnectionIndicator connected={connected} />
    </div>
  );
}
