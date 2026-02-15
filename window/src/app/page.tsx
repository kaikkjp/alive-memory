'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useShopkeeperSocket } from '@/hooks/useShopkeeperSocket';
import { useSceneTransition } from '@/hooks/useSceneTransition';
import SceneCanvas from '@/components/SceneCanvas';
import TextStream from '@/components/TextStream';
import StatePanel from '@/components/StatePanel';
import ActivityOverlay from '@/components/ActivityOverlay';
import ConnectionIndicator from '@/components/ConnectionIndicator';
import ChatGate from '@/components/ChatGate';
import ChatPanel from '@/components/ChatPanel';
import type { SpriteState, TimeOfDay } from '@/lib/types';
import {
  DEFAULT_SPRITE_STATE,
  DEFAULT_TIME_OF_DAY,
} from '@/lib/scene-constants';

const SPRITE_STATES: SpriteState[] = [
  'surprised', 'tired', 'engaged', 'curious', 'focused', 'thinking',
];
const TIME_OF_DAY_OPTIONS: TimeOfDay[] = [
  'morning', 'afternoon', 'evening', 'night',
];

export default function WindowPage() {
  const searchParams = useSearchParams();
  const debugScene = searchParams.get('debug') === 'scene';

  if (debugScene) {
    return <DebugSceneViewer />;
  }

  return <LiveWindow />;
}

// ─── Debug scene viewer (dev only) ───

function DebugSceneViewer() {
  const [spriteState, setSpriteState] = useState<SpriteState>(DEFAULT_SPRITE_STATE);
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay>(DEFAULT_TIME_OF_DAY);

  return (
    <div style={{ maxWidth: 960, margin: '0 auto', padding: 16 }}>
      <div style={{ marginBottom: 12, display: 'flex', gap: 16, alignItems: 'center' }}>
        <label>
          Sprite:{' '}
          <select
            value={spriteState}
            onChange={(e) => setSpriteState(e.target.value as SpriteState)}
            style={{ padding: '4px 8px' }}
          >
            {SPRITE_STATES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </label>
        <label>
          Time:{' '}
          <select
            value={timeOfDay}
            onChange={(e) => setTimeOfDay(e.target.value as TimeOfDay)}
            style={{ padding: '4px 8px' }}
          >
            {TIME_OF_DAY_OPTIONS.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </label>
        <span style={{ opacity: 0.5, fontSize: 13 }}>
          ?debug=scene
        </span>
      </div>
      <SceneCanvas spriteState={spriteState} timeOfDay={timeOfDay} />
    </div>
  );
}

// ─── Live window (production) ───

function LiveWindow() {
  const {
    layers,
    textEntries,
    windowState,
    currentThought,
    activityLabel,
    connected,
    sendChat,
    sendDisconnect,
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
    if (chatToken) sendDisconnect(chatToken);
    setChatOpen(false);
  }, [chatToken, sendDisconnect]);

  const weather = activeLayers?.weather ?? '';

  // Scene compositor state from WebSocket payload
  const spriteState: SpriteState = useMemo(() => {
    const ws = windowState?.sprite_state;
    if (ws && SPRITE_STATES.includes(ws)) return ws;
    return DEFAULT_SPRITE_STATE;
  }, [windowState?.sprite_state]);

  const timeOfDay: TimeOfDay = useMemo(() => {
    const ws = windowState?.time_of_day;
    if (ws && TIME_OF_DAY_OPTIONS.includes(ws)) return ws;
    return DEFAULT_TIME_OF_DAY;
  }, [windowState?.time_of_day]);

  return (
    <div
      className={`window-layout ${chatOpen ? 'window-layout--chat-open' : ''}`}
    >
      {/* Main scene area */}
      <main className="window-main">
        <SceneCanvas
          spriteState={spriteState}
          timeOfDay={timeOfDay}
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
