'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { authManager } from '@/lib/auth-manager';
import { getWsUrl, RECONNECT_BASE_MS, RECONNECT_MAX_MS, MAX_FRAGMENTS } from '@/lib/config';
import type {
  SceneLayers,
  TextEntry,
  WindowState,
  ServerMessage,
  ChatMessage,
  Fragment,
} from '@/lib/types';

const WS_URL = getWsUrl();

let fragmentIdCounter = 0;

export interface SocketState {
  layers: SceneLayers | null;
  textEntries: TextEntry[];
  fragments: Fragment[];
  windowState: WindowState | null;
  currentThought: string;
  activityLabel: string;
  connected: boolean;
  chatMessages: ChatMessage[];
}

export function useShopkeeperSocket(): SocketState & {
  sendChat: (text: string, token: string) => boolean;
  sendDisconnect: (token: string) => void;
  addVisitorMessage: (text: string) => void;
  clearChatMessages: () => void;
} {
  const [layers, setLayers] = useState<SceneLayers | null>(null);
  const [textEntries, setTextEntries] = useState<TextEntry[]>([]);
  const [fragments, setFragments] = useState<Fragment[]>([]);
  const [windowState, setWindowState] = useState<WindowState | null>(null);
  const [currentThought, setCurrentThought] = useState('');
  const [activityLabel, setActivityLabel] = useState('');
  const [connected, setConnected] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE_MS);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const disposedRef = useRef(false);
  // Tracks the last shopkeeper thought added to chatMessages to prevent
  // duplicate bubbles when scene_update repeats the same current_thought.
  const lastSkThoughtRef = useRef<string>('');

  const addFragment = useCallback((content: string, type: string, timestamp: string) => {
    const id = `frag-${++fragmentIdCounter}-${Date.now()}`;
    setFragments((prev) => {
      const next: Fragment = { id, content, type: type as Fragment['type'], timestamp };
      return [next, ...prev].slice(0, MAX_FRAGMENTS);
    });
  }, []);

  const connect = useCallback(() => {
    if (disposedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      const token = authManager.getToken();
      if (token) {
        ws.send(JSON.stringify({ type: 'auth', token }));
      }
      setConnected(true);
      reconnectDelay.current = RECONNECT_BASE_MS;
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        handleMessage(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
      if (disposedRef.current) return;
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(
          reconnectDelay.current * 2,
          RECONNECT_MAX_MS,
        );
        connect();
      }, reconnectDelay.current);
    };

    ws.onerror = () => {
      ws.close();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleMessage = (msg: ServerMessage) => {
    switch (msg.type) {
      case 'scene_update':
        setLayers(msg.layers);
        setWindowState(msg.state);
        if (msg.text?.recent_entries?.length) {
          setTextEntries(msg.text.recent_entries.slice(0, MAX_FRAGMENTS));
          const frags: Fragment[] = msg.text.recent_entries
            .slice(0, MAX_FRAGMENTS)
            .map((e, i) => ({
              id: `init-${i}-${e.timestamp}`,
              content: e.content,
              type: e.type,
              timestamp: e.timestamp,
            }));
          setFragments(frags);
        }
        if (msg.text?.current_thought) {
          setCurrentThought(msg.text.current_thought);
          // Mirror shopkeeper speech into ChatPanel when a visitor is present.
          // Gate: visitor_present AND current_thought is not just the activity label
          // (which is the fallback when she has nothing to say).
          if (
            msg.state?.visitor_present &&
            msg.text.current_thought !== msg.text.activity_label &&
            msg.text.current_thought !== lastSkThoughtRef.current
          ) {
            lastSkThoughtRef.current = msg.text.current_thought;
            setChatMessages((prev) => [
              ...prev,
              {
                id: `sk-${Date.now()}`,
                content: msg.text.current_thought!,
                sender: 'shopkeeper',
                timestamp: msg.timestamp,
              },
            ]);
          }
        }
        if (msg.text?.activity_label) setActivityLabel(msg.text.activity_label);
        break;

      case 'text_fragment':
        setTextEntries((prev) => {
          const entry: TextEntry = { content: msg.content, type: msg.fragment_type, timestamp: msg.timestamp };
          return [entry, ...prev].slice(0, MAX_FRAGMENTS);
        });
        addFragment(msg.content, msg.fragment_type, msg.timestamp);
        break;

      case 'expression_change':
        setWindowState((prev) =>
          prev ? { ...prev, sprite_state: msg.expression as WindowState['sprite_state'] } : prev,
        );
        break;

      case 'item_added':
        setLayers((prev) => {
          if (!prev) return prev;
          return { ...prev, items: [...prev.items, msg.item] };
        });
        break;

      case 'status':
        setWindowState((prev) =>
          prev ? { ...prev, status: msg.status } : prev,
        );
        break;

      case 'chat_response':
        setChatMessages((prev) => [
          ...prev,
          {
            id: `sk-${Date.now()}`,
            content: msg.content,
            sender: 'shopkeeper',
            timestamp: msg.timestamp,
          },
        ]);
        addFragment(msg.content, 'speech', msg.timestamp);
        break;

      case 'chat_error':
        console.warn('[chat]', msg.message);
        break;
    }
  };

  const sendChat = useCallback((text: string, token: string): boolean => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'visitor_message', text, token }));
      return true;
    }
    return false;
  }, []);

  const sendDisconnect = useCallback((token: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'visitor_disconnect', token }));
    }
  }, []);

  const clearChatMessages = useCallback(() => {
    setChatMessages([]);
    lastSkThoughtRef.current = '';
  }, []);

  const addVisitorMessage = useCallback((text: string) => {
    setChatMessages((prev) => [
      ...prev,
      {
        id: `v-${Date.now()}`,
        content: text,
        sender: 'visitor',
        timestamp: new Date().toISOString(),
      },
    ]);
  }, []);

  useEffect(() => {
    disposedRef.current = false;
    connect();
    return () => {
      disposedRef.current = true;
      clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return {
    layers,
    textEntries,
    fragments,
    windowState,
    currentThought,
    activityLabel,
    connected,
    chatMessages,
    sendChat,
    sendDisconnect,
    addVisitorMessage,
    clearChatMessages,
  };
}
