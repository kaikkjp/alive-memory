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
  visitorCount: number;
  thinking: boolean;
  chatError: string | null;
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
  const [visitorCount, setVisitorCount] = useState(0);
  const [pendingAcks, setPendingAcks] = useState(0);
  const [chatError, setChatError] = useState<string | null>(null);
  const thinkingTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const pendingAcksRef = useRef(0);
  const thinking = pendingAcks > 0;

  // Decrement pending counter and clear timeout when all responses arrived.
  const decrementPending = useCallback(() => {
    setPendingAcks((n) => {
      const next = Math.max(0, n - 1);
      pendingAcksRef.current = next;
      if (next === 0) clearTimeout(thinkingTimerRef.current);
      return next;
    });
  }, []);

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
        // Restore chat history from initial connect payload (reconnect support)
        if (msg.chat_history?.length) {
          setChatMessages((prev) => {
            // Only load history if chat is empty (first connect / reconnect)
            if (prev.length > 0) return prev;
            return msg.chat_history!.map((entry, i) => ({
              id: `hist-${i}-${entry.timestamp}`,
              content: entry.content,
              sender: entry.sender_type === 'visitor' ? 'visitor' as const : 'shopkeeper' as const,
              timestamp: entry.timestamp,
            }));
          });
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

      case 'status':
        setWindowState((prev) =>
          prev ? { ...prev, status: msg.status } : prev,
        );
        break;

      case 'chat_ack':
        // Server received our message — increment pending counter.
        setChatError(null);
        setPendingAcks((n) => {
          const next = n + 1;
          pendingAcksRef.current = next;
          return next;
        });
        // Safety timeout: if no response within 60s after last ack, clear all and show fallback.
        clearTimeout(thinkingTimerRef.current);
        thinkingTimerRef.current = setTimeout(() => {
          pendingAcksRef.current = 0;
          setPendingAcks(0);
          setChatError('She seems lost in thought...');
        }, 60_000);
        break;

      case 'chat_response':
        decrementPending();
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
        decrementPending();
        setChatError(msg.message);
        break;

      case 'chat_message':
        // Broadcast room: another viewer's message (or our own echoed back).
        // Skip if this is the local visitor's own message (already added optimistically).
        if (msg.sender_type === 'visitor') {
          // Visitor messages are added optimistically via addVisitorMessage,
          // so we only add if it's from a different visitor (multi-visitor room).
          // Use content dedup: if last visitor message has same content, skip.
          setChatMessages((prev) => {
            const lastVisitor = [...prev].reverse().find((m) => m.sender === 'visitor');
            if (lastVisitor && lastVisitor.content === msg.content) return prev;
            return [
              ...prev,
              {
                id: `room-v-${Date.now()}`,
                content: msg.content,
                sender: 'visitor',
                timestamp: msg.timestamp,
              },
            ];
          });
        } else {
          decrementPending();
          setChatMessages((prev) => [
            ...prev,
            {
              id: `room-sk-${Date.now()}`,
              content: msg.content,
              sender: 'shopkeeper',
              timestamp: msg.timestamp,
            },
          ]);
        }
        break;

      case 'visitor_presence':
        setVisitorCount(msg.visitor_count);
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
    pendingAcksRef.current = 0;
    setPendingAcks(0);
    setChatError(null);
    clearTimeout(thinkingTimerRef.current);
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
      clearTimeout(thinkingTimerRef.current);
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
    visitorCount,
    thinking,
    chatError,
    sendChat,
    sendDisconnect,
    addVisitorMessage,
    clearChatMessages,
  };
}
