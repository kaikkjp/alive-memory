'use client';

import { Suspense, useCallback, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { useShopkeeperSocket } from '@/hooks/useShopkeeperSocket';
import { useExpression } from '@/hooks/useExpression';

// Scene
import SceneViewport from '@/components/scene/SceneViewport';
import CharacterSprite from '@/components/scene/CharacterSprite';
import DustParticles from '@/components/scene/DustParticles';
import GlassOverlay from '@/components/scene/GlassOverlay';
import SleepOverlay from '@/components/scene/SleepOverlay';

// Stream
import ActivityStream from '@/components/stream/ActivityStream';

// Chat
import ChatGate from '@/components/chat/ChatGate';
import TokenAuth from '@/components/chat/TokenAuth';
import ChatPanel from '@/components/chat/ChatPanel';

// UI
import TopBar from '@/components/ui/TopBar';
import BottomBar from '@/components/ui/BottomBar';
import LoadingScreen from '@/components/ui/LoadingScreen';

// Legacy (debug mode only)
import SceneCanvas from '@/components/SceneCanvas';
import type { SpriteState, TimeOfDay } from '@/lib/types';
import { DEFAULT_SPRITE_STATE, DEFAULT_TIME_OF_DAY } from '@/lib/scene-constants';

const SPRITE_STATES: SpriteState[] = [
  'surprised', 'tired', 'engaged', 'curious', 'focused', 'thinking',
];
const TIME_OF_DAY_OPTIONS: TimeOfDay[] = [
  'morning', 'afternoon', 'evening', 'night',
];

export default function WindowPage() {
  return (
    <Suspense>
      <WindowPageInner />
    </Suspense>
  );
}

function WindowPageInner() {
  const searchParams = useSearchParams();
  const mode = searchParams.get('debug');

  if (mode === 'scene') return <DebugSceneViewer />;

  return <LiveWindow />;
}

// ─── Production: Through the Glass ───

function LiveWindow() {
  const {
    fragments,
    windowState,
    connected,
    chatMessages,
    sendChat,
    sendDisconnect,
    addVisitorMessage,
    clearChatMessages,
  } = useShopkeeperSocket();

  const [sceneLoaded, setSceneLoaded] = useState(false);
  const [chatPhase, setChatPhase] = useState<'watching' | 'token' | 'chatting'>('watching');
  const [chatToken, setChatToken] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState('Visitor');

  const status = windowState?.status ?? 'awake';
  const sleeping = status === 'sleeping';
  const weather = windowState?.weather_diegetic ?? '';
  const timeOfDay = windowState?.time_label ?? '';

  const expression = useExpression(windowState?.sprite_state);

  const sceneImageUrl = '/assets/shop_interior.png';

  const handleEnterShop = useCallback(() => {
    setChatPhase('token');
  }, []);

  const handleTokenValidated = useCallback((token: string, name: string) => {
    clearChatMessages();
    setChatToken(token);
    setDisplayName(name);
    setChatPhase('chatting');
  }, [clearChatMessages]);

  const handleTokenCancel = useCallback(() => {
    setChatPhase('watching');
  }, []);

  const handleChatClose = useCallback(() => {
    if (chatToken) sendDisconnect(chatToken);
    clearChatMessages();
    setChatPhase('watching');
  }, [chatToken, sendDisconnect, clearChatMessages]);

  const handleChatSend = useCallback((text: string): boolean => {
    if (!chatToken) return false;
    // Only show the optimistic bubble if the message was actually sent.
    // sendChat returns false when WS is not open, preventing ghost messages.
    const sent = sendChat(text, chatToken);
    if (sent) addVisitorMessage(text);
    return sent;
  }, [chatToken, sendChat, addVisitorMessage]);

  return (
    <div className="window-viewport">
      <LoadingScreen loaded={sceneLoaded} />

      {/* Z-0: Background scene */}
      <SceneViewport
        imageUrl={sceneImageUrl}
        onLoad={() => setSceneLoaded(true)}
      />

      {/* Z-1: Character sprite */}
      <CharacterSprite expression={expression} hidden={sleeping} />

      {/* Z-2: Dust particles */}
      <DustParticles weather={windowState?.weather_diegetic} />

      {/* Z-3: Glass reflection + vignette */}
      <GlassOverlay />

      {/* Z-4: Sleep overlay */}
      <SleepOverlay sleeping={sleeping} />

      {/* UI: Top bar */}
      <TopBar timeOfDay={timeOfDay} weather={weather} connected={connected} />

      {/* UI: Activity stream */}
      <ActivityStream fragments={fragments} />

      {/* UI: Bottom bar */}
      <BottomBar />

      {/* Chat gate / token auth */}
      {chatPhase === 'watching' && (
        <ChatGate onEnter={handleEnterShop} sleeping={sleeping} />
      )}

      {chatPhase === 'token' && (
        <TokenAuth
          onValidated={handleTokenValidated}
          onCancel={handleTokenCancel}
        />
      )}

      {/* Chat panel (slide-up) */}
      <ChatPanel
        open={chatPhase === 'chatting'}
        messages={chatMessages}
        displayName={displayName}
        onSend={handleChatSend}
        onClose={handleChatClose}
      />
    </div>
  );
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
        <span style={{ opacity: 0.5, fontSize: 13 }}>?debug=scene</span>
      </div>
      <SceneCanvas spriteState={spriteState} timeOfDay={timeOfDay} />
    </div>
  );
}
