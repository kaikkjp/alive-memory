'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  SceneLayers,
  TextEntry,
  WindowState,
  ServerMessage,
  ShopkeeperState,
} from '@/lib/types';

// In production (behind nginx), WebSocket is at wss://<host>/ws/.
// In development, fall back to the local heartbeat server.
function getWsUrl(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window === 'undefined') return 'ws://localhost:8765';
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/`;
}
const WS_URL = getWsUrl();
const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 30000;
const MAX_TEXT_ENTRIES = 8;

export function useShopkeeperSocket(): ShopkeeperState & {
  sendChat: (text: string, token: string) => void;
} {
  const [layers, setLayers] = useState<SceneLayers | null>(null);
  const [textEntries, setTextEntries] = useState<TextEntry[]>([]);
  const [windowState, setWindowState] = useState<WindowState | null>(null);
  const [currentThought, setCurrentThought] = useState('');
  const [activityLabel, setActivityLabel] = useState('');
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectDelay = useRef(RECONNECT_BASE_MS);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const disposedRef = useRef(false);

  const connect = useCallback(() => {
    if (disposedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
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
      // Only reconnect if not intentionally disposed
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
  }, []);

  const handleMessage = (msg: ServerMessage) => {
    switch (msg.type) {
      case 'scene_update':
        setLayers(msg.layers);
        setWindowState(msg.state);

        // Handle initial load with recent_entries
        if (msg.text.recent_entries?.length) {
          setTextEntries(msg.text.recent_entries.slice(0, MAX_TEXT_ENTRIES));
        }
        if (msg.text.current_thought) {
          setCurrentThought(msg.text.current_thought);
        }
        if (msg.text.activity_label) {
          setActivityLabel(msg.text.activity_label);
        }
        break;

      case 'text_fragment':
        setTextEntries((prev) => {
          const newEntry: TextEntry = {
            content: msg.content,
            type: msg.fragment_type,
            timestamp: msg.timestamp,
          };
          return [newEntry, ...prev].slice(0, MAX_TEXT_ENTRIES);
        });
        break;

      case 'item_added':
        // Update layers to include new item
        setLayers((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            items: [...prev.items, msg.item],
          };
        });
        break;

      case 'status':
        setWindowState((prev) =>
          prev ? { ...prev, status: msg.status } : prev,
        );
        break;

      case 'chat_error':
        // Could surface this to the chat panel
        console.warn('[chat]', msg.message);
        break;
    }
  };

  const sendChat = useCallback((text: string, token: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({ type: 'visitor_message', text, token }),
      );
    }
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
    windowState,
    currentThought,
    activityLabel,
    connected,
    sendChat,
  };
}
