"use client";

/**
 * TASK-095 v3.1 Batch 4: Central real-time data hook for the Lounge.
 *
 * Polls /api/agents/:id/status (15s) and /api/agents/:id/inner-voice (20s).
 * Status poll is the sole authority for connection state.
 * Inner-voice poll failures are silently ignored (stale data preserved).
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type { AgentStreamState, InnerVoiceEntry } from "@/lib/types";

const STATUS_INTERVAL = 15_000;
const INNER_VOICE_INTERVAL = 20_000;
const MAX_FAILURES = 3;

const DEFAULT_STATE: AgentStreamState = {
  drives: null,
  mood: null,
  energy: 0.5,
  engagement_state: "idle",
  is_sleeping: false,
  is_dreaming: false,
  cycle_count: 0,
  inner_voice: [],
  recent_actions: [],
  current_action: null,
  status: "reconnecting",
  lastUpdate: null,
};

/** Extract a number from a drive value that may be a DriveState object or a plain number. */
function normalizeDrive(v: unknown, fallback = 0.45): number {
  if (typeof v === "number") return v;
  if (v && typeof v === "object" && "value" in v) {
    const n = (v as { value: unknown }).value;
    if (typeof n === "number") return n;
  }
  return fallback;
}

/** Deduplicate inner voice entries by composite key (timestamp + text). */
function dedupeEntries(entries: InnerVoiceEntry[]): InnerVoiceEntry[] {
  const seen = new Set<string>();
  return entries.filter((e) => {
    const key = `${e.timestamp}|${e.text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function useAgentStream(agentId: string) {
  const [state, setState] = useState<AgentStreamState>(DEFAULT_STATE);
  const failCountRef = useRef(0);
  const mountedRef = useRef(true);

  const pollStatus = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      const res = await fetch(`/api/agents/${agentId}/status`);
      if (!res.ok) {
        failCountRef.current++;
        setState((prev) => ({
          ...prev,
          status: failCountRef.current >= MAX_FAILURES ? "error" : "reconnecting",
        }));
        return;
      }

      const data = await res.json();

      // Check for offline in response body (status route returns 200 with {status:"offline"})
      if (data.status === "offline") {
        failCountRef.current = 0;
        setState((prev) => ({ ...prev, status: "offline" }));
        return;
      }

      // Connected — reset failures and merge state
      failCountRef.current = 0;

      // Normalize drives from DriveState objects or plain numbers
      const rawDrives = data.drives;
      const drives = rawDrives
        ? {
            curiosity: normalizeDrive(rawDrives.curiosity),
            social_hunger: normalizeDrive(rawDrives.social_hunger),
            expression_need: normalizeDrive(rawDrives.expression_need),
            rest_need: normalizeDrive(rawDrives.rest_need),
            energy: normalizeDrive(rawDrives.energy, 0.5),
            mood_valence: normalizeDrive(rawDrives.mood_valence, 0),
            mood_arousal: normalizeDrive(rawDrives.mood_arousal, 0),
          }
        : null;

      setState((prev) => ({
        ...prev,
        status: "connected",
        drives,
        mood: data.mood ?? prev.mood,
        energy: data.energy ?? data.drives?.energy ?? prev.energy,
        engagement_state: data.engagement_state ?? prev.engagement_state,
        is_sleeping: data.is_sleeping ?? prev.is_sleeping,
        is_dreaming: data.is_dreaming ?? prev.is_dreaming,
        cycle_count: data.cycle_count ?? prev.cycle_count,
        recent_actions: data.recent_actions ?? prev.recent_actions,
        current_action: data.current_action ?? prev.current_action,
        lastUpdate: new Date().toISOString(),
      }));
    } catch {
      failCountRef.current++;
      setState((prev) => ({
        ...prev,
        status: failCountRef.current >= MAX_FAILURES ? "error" : "reconnecting",
      }));
    }
  }, [agentId]);

  const pollInnerVoice = useCallback(async () => {
    if (!mountedRef.current) return;
    try {
      const res = await fetch(`/api/agents/${agentId}/inner-voice`);
      // Silently ignore failures — inner-voice does NOT affect connection state
      if (!res.ok) return;
      const data = await res.json();
      const entries: InnerVoiceEntry[] = Array.isArray(data.entries)
        ? data.entries
        : Array.isArray(data)
          ? data
          : [];

      if (entries.length > 0) {
        setState((prev) => ({
          ...prev,
          inner_voice: dedupeEntries([...entries, ...prev.inner_voice]).slice(0, 50),
        }));
      }
    } catch {
      // Silently ignored — stale data preserved
    }
  }, [agentId]);

  const refresh = useCallback(() => {
    pollStatus();
    pollInnerVoice();
  }, [pollStatus, pollInnerVoice]);

  useEffect(() => {
    mountedRef.current = true;

    // Initial polls
    pollStatus();
    pollInnerVoice();

    const statusTimer = setInterval(pollStatus, STATUS_INTERVAL);
    const voiceTimer = setInterval(pollInnerVoice, INNER_VOICE_INTERVAL);

    return () => {
      mountedRef.current = false;
      clearInterval(statusTimer);
      clearInterval(voiceTimer);
    };
  }, [pollStatus, pollInnerVoice]);

  return { ...state, refresh };
}
