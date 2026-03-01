"use client";

import { useState, useEffect, use } from "react";
import { useAgentStream } from "@/hooks/useAgentStream";
import ConsciousnessCanvas from "@/components/ConsciousnessCanvas";
import LoungeTopBar from "@/components/LoungeTopBar";
import StateOverlay from "@/components/StateOverlay";
import MindPanel from "@/components/MindPanel";
import ActionsLog from "@/components/ActionsLog";
import ChatBar from "@/components/ChatBar";
import FeedTab from "@/components/FeedTab";
import SeedTab from "@/components/SeedTab";
import TeachTab from "@/components/TeachTab";
import ToastNotification from "@/components/ToastNotification";
import SettingsDrawer from "@/components/SettingsDrawer";

type IOTab = "feed" | "seed" | "teach";
type MobileTab = "mind" | "feed" | "seed" | "teach";

export default function LoungePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const stream = useAgentStream(id);

  const [agentName, setAgentName] = useState("...");
  const [ioTab, setIoTab] = useState<IOTab>("feed");
  const [mobileTab, setMobileTab] = useState<MobileTab>("mind");
  const [sleepConfirm, setSleepConfirm] = useState(false);
  const [sleeping, setSleeping] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Fetch agent name on mount
  useEffect(() => {
    async function load() {
      try {
        const res = await fetch(`/api/agents/${id}`);
        if (res.ok) {
          const data = await res.json();
          setAgentName(data.name || "Agent");
        }
      } catch {
        // silent
      }
    }
    load();
  }, [id]);

  // Derive canvas props
  const drives = stream.drives;
  const moodValence = drives?.mood_valence ?? stream.mood?.valence ?? 0;
  const energyVal = drives?.energy ?? stream.energy;
  const curiosityVal = drives?.curiosity ?? 0.45;
  const socialVal = drives?.social_hunger ?? 0.5;
  const expressionVal = drives?.expression_need ?? 0.4;
  const isSleeping = sleeping || stream.is_sleeping;

  async function handleForceSleep() {
    setSleepConfirm(false);
    setSleeping(true);
    try {
      const res = await fetch(`/api/agents/${id}/sleep`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const msg = data.queued
          ? "Will rest after current conversation."
          : "Entering sleep cycle...";
        setToast(msg);
        setTimeout(async () => {
          stream.refresh();
          setSleeping(false);
        }, 5000);
      } else {
        setSleeping(false);
      }
    } catch {
      setSleeping(false);
    }
  }

  const isOffline = stream.status === "offline" || stream.status === "error";

  // Tab button with bottom indicator
  function TabButton({
    label,
    active,
    onClick,
    className,
  }: {
    label: string;
    active: boolean;
    onClick: () => void;
    className?: string;
  }) {
    return (
      <button
        onClick={onClick}
        className={`relative px-3 py-1.5 rounded-md text-xs capitalize transition-all min-h-[44px] md:min-h-0 ${
          active
            ? "bg-[#262626] text-white"
            : "text-[#737373] hover:text-white hover:bg-[#1a1a1a]"
        } ${className ?? ""}`}
      >
        {label}
        {active && (
          <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-4 h-0.5 bg-[#d4a574] rounded-full transition-all" />
        )}
      </button>
    );
  }

  return (
    <div className="flex flex-col h-screen bg-[#0a0a0f] text-[#d4d4d4]">
      <LoungeTopBar
        agentName={agentName}
        status={stream.status}
        isSleeping={isSleeping}
        onRestClick={() => setSleepConfirm(true)}
        onBackClick={() => window.history.back()}
        onSettingsClick={() => setSettingsOpen(!settingsOpen)}
        settingsOpen={settingsOpen}
      />

      {/* ── Desktop (xl+): 3-column layout ── */}
      <div className="hidden xl:flex flex-1 overflow-hidden">
        {/* Left: Mind panel */}
        <div className="w-[220px] border-r border-[#1e1e1a] overflow-y-auto bg-[#0a0a0f]">
          <div className="p-3">
            <h2 className="text-xs font-medium text-[#525252] uppercase tracking-wider mb-3">
              Inner Voice
            </h2>
            <MindPanel entries={stream.inner_voice} status={stream.status} />
          </div>
          <div className="p-3 border-t border-[#1e1e1a]">
            <h2 className="text-xs font-medium text-[#525252] uppercase tracking-wider mb-3">
              Actions
            </h2>
            <ActionsLog actions={stream.recent_actions} />
          </div>
        </div>

        {/* Center: Organism + State */}
        <div className="flex-1 flex flex-col relative min-w-0">
          <div className="flex-1 relative">
            <ConsciousnessCanvas
              mood_valence={moodValence}
              energy={energyVal}
              curiosity={curiosityVal}
              social_hunger={socialVal}
              expression_need={expressionVal}
              is_sleeping={isSleeping}
              is_dreaming={stream.is_dreaming}
              is_thinking={false}
            />
            {/* Reconnecting overlay */}
            {(stream.status === "reconnecting" || stream.status === "error") && (
              <div className="absolute inset-0 bg-[#0a0a0f]/60 flex items-center justify-center z-10">
                <span className="text-xs text-[#525252]">
                  {stream.status === "error"
                    ? "Connection lost"
                    : "Reconnecting..."}
                </span>
              </div>
            )}
          </div>
          <StateOverlay
            mood={stream.mood}
            energy={energyVal}
            engagement_state={stream.engagement_state}
            current_action={stream.current_action}
            is_sleeping={isSleeping}
            drives={
              drives
                ? {
                    curiosity: drives.curiosity,
                    social_hunger: drives.social_hunger,
                    expression_need: drives.expression_need,
                  }
                : null
            }
          />
          <ChatBar
            agentId={id}
            agentName={agentName}
            status={stream.status}
            isSleeping={isSleeping}
            onSendComplete={stream.refresh}
          />
        </div>

        {/* Right: I/O tabs */}
        <div className="w-[280px] border-l border-[#1e1e1a] flex flex-col bg-[#0a0a0f]">
          <div className="flex gap-1 px-3 pt-3 pb-2">
            {(["feed", "seed", "teach"] as const).map((tab) => (
              <TabButton
                key={tab}
                label={tab}
                active={ioTab === tab}
                onClick={() => setIoTab(tab)}
              />
            ))}
          </div>
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            <div key={ioTab} className="animate-tab-fade">
              {ioTab === "feed" && (
                <FeedTab agentId={id} status={stream.status} onToast={setToast} />
              )}
              {ioTab === "seed" && <SeedTab agentId={id} onToast={setToast} />}
              {ioTab === "teach" && (
                <TeachTab agentId={id} status={stream.status} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Tablet (md to xl): 2-column layout ── */}
      <div className="hidden md:flex xl:hidden flex-1 overflow-hidden">
        {/* Left: Organism + State */}
        <div className="flex-1 flex flex-col relative min-w-0">
          <div className="flex-1 relative">
            <ConsciousnessCanvas
              mood_valence={moodValence}
              energy={energyVal}
              curiosity={curiosityVal}
              social_hunger={socialVal}
              expression_need={expressionVal}
              is_sleeping={isSleeping}
              is_dreaming={stream.is_dreaming}
              is_thinking={false}
            />
            {(stream.status === "reconnecting" || stream.status === "error") && (
              <div className="absolute inset-0 bg-[#0a0a0f]/60 flex items-center justify-center z-10">
                <span className="text-xs text-[#525252]">
                  {stream.status === "error"
                    ? "Connection lost"
                    : "Reconnecting..."}
                </span>
              </div>
            )}
          </div>
          <StateOverlay
            mood={stream.mood}
            energy={energyVal}
            engagement_state={stream.engagement_state}
            current_action={stream.current_action}
            is_sleeping={isSleeping}
            drives={
              drives
                ? {
                    curiosity: drives.curiosity,
                    social_hunger: drives.social_hunger,
                    expression_need: drives.expression_need,
                  }
                : null
            }
          />
          <ChatBar
            agentId={id}
            agentName={agentName}
            status={stream.status}
            isSleeping={isSleeping}
            onSendComplete={stream.refresh}
          />
        </div>

        {/* Right: Tabbed I/O + Mind */}
        <div className="w-[280px] border-l border-[#1e1e1a] flex flex-col bg-[#0a0a0f]">
          <div className="flex gap-1 px-3 pt-3 pb-2">
            {(["mind", "feed", "seed", "teach"] as const).map((tab) => (
              <TabButton
                key={tab}
                label={tab}
                active={mobileTab === tab}
                onClick={() => setMobileTab(tab)}
              />
            ))}
          </div>
          <div className="flex-1 overflow-y-auto px-3 pb-3">
            <div key={mobileTab} className="animate-tab-fade">
              {mobileTab === "mind" && (
                <>
                  <MindPanel entries={stream.inner_voice} status={stream.status} />
                  <div className="mt-4 pt-3 border-t border-[#1e1e1a]">
                    <h2 className="text-xs font-medium text-[#525252] uppercase tracking-wider mb-3 px-3">
                      Actions
                    </h2>
                    <ActionsLog actions={stream.recent_actions} />
                  </div>
                </>
              )}
              {mobileTab === "feed" && (
                <FeedTab agentId={id} status={stream.status} onToast={setToast} />
              )}
              {mobileTab === "seed" && <SeedTab agentId={id} onToast={setToast} />}
              {mobileTab === "teach" && (
                <TeachTab agentId={id} status={stream.status} />
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Mobile (<md): Stacked layout ── */}
      <div className="flex md:hidden flex-col flex-1 overflow-hidden">
        {/* Organism top */}
        <div className="relative h-[40vh] shrink-0">
          <ConsciousnessCanvas
            mood_valence={moodValence}
            energy={energyVal}
            curiosity={curiosityVal}
            social_hunger={socialVal}
            expression_need={expressionVal}
            is_sleeping={isSleeping}
            is_dreaming={stream.is_dreaming}
            is_thinking={false}
          />
          {isOffline && (
            <div className="absolute inset-0 bg-[#0a0a0f]/60 flex items-center justify-center z-10">
              <span className="text-xs text-[#525252]">
                {stream.status === "error"
                  ? "Connection lost"
                  : "Offline"}
              </span>
            </div>
          )}
          <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-[#0a0a0f]/80 to-transparent pt-6">
            <StateOverlay
              mood={stream.mood}
              energy={energyVal}
              engagement_state={stream.engagement_state}
              current_action={stream.current_action}
              is_sleeping={isSleeping}
              drives={
                drives
                  ? {
                      curiosity: drives.curiosity,
                      social_hunger: drives.social_hunger,
                      expression_need: drives.expression_need,
                    }
                  : null
              }
            />
          </div>
        </div>

        {/* Tab buttons */}
        <div className="flex gap-1 px-3 py-2 border-t border-[#1e1e1a]">
          {(["mind", "feed", "seed", "teach"] as const).map((tab) => (
            <TabButton
              key={tab}
              label={tab}
              active={mobileTab === tab}
              onClick={() => setMobileTab(tab)}
              className="flex-1"
            />
          ))}
        </div>

        {/* Tab content */}
        <div className="flex-1 overflow-y-auto px-3 pb-2">
          <div key={mobileTab} className="animate-tab-fade">
            {mobileTab === "mind" && (
              <>
                <MindPanel entries={stream.inner_voice} status={stream.status} />
                <div className="mt-4 pt-3 border-t border-[#1e1e1a]">
                  <h2 className="text-xs font-medium text-[#525252] uppercase tracking-wider mb-3 px-3">
                    Actions
                  </h2>
                  <ActionsLog actions={stream.recent_actions} />
                </div>
              </>
            )}
            {mobileTab === "feed" && (
              <FeedTab agentId={id} status={stream.status} onToast={setToast} />
            )}
            {mobileTab === "seed" && <SeedTab agentId={id} onToast={setToast} />}
            {mobileTab === "teach" && (
              <TeachTab agentId={id} status={stream.status} />
            )}
          </div>
        </div>

        {/* Chat at bottom */}
        <ChatBar
          agentId={id}
          agentName={agentName}
          status={stream.status}
          isSleeping={isSleeping}
          onSendComplete={stream.refresh}
        />
      </div>

      {/* Sleep confirmation modal */}
      {sleepConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-[#1a1a1a] border border-[#262620] rounded-xl p-6 max-w-sm mx-4">
            <h3 className="text-base font-semibold mb-2">Rest now?</h3>
            <p className="text-sm text-[#a3a3a3] mb-4">
              She&apos;ll enter a sleep cycle. Any queued changes will be
              integrated as dreams.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setSleepConfirm(false)}
                className="px-4 py-2 text-sm text-[#737373] hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleForceSleep}
                disabled={sleeping || isOffline}
                className="px-4 py-2 bg-[#6b5b8a] hover:bg-[#7b6b9a] text-white rounded-lg text-sm transition-colors disabled:opacity-40"
              >
                {sleeping ? "Resting..." : "Rest now"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings Drawer */}
      <SettingsDrawer
        agentId={id}
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        onToast={setToast}
      />

      {/* Toast */}
      {toast && (
        <ToastNotification
          message={toast}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  );
}
