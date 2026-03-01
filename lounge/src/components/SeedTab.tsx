"use client";

import { useState, useEffect, useCallback } from "react";
import BackstoryCard from "./BackstoryCard";
import MemoryTimeline from "./MemoryTimeline";
import type {
  Thread,
  JournalEntry,
  Totem,
  DayMemory,
  CollectionItem,
} from "@/lib/types";

interface Memory {
  source_id: string;
  source_type: string;
  text_content: string;
  ts_iso: string;
  origin: string;
}

type MemorySection =
  | "seeds"
  | "threads"
  | "journal"
  | "totems"
  | "moments"
  | "collection";

interface SeedTabProps {
  agentId: string;
  onToast?: (msg: string) => void;
}

function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={`bg-[#1e1e1a] rounded animate-skeleton ${className ?? ""}`}
    />
  );
}

const THREAD_STATUS_COLORS: Record<string, string> = {
  open: "bg-emerald-900/50 text-emerald-400",
  active: "bg-amber-900/50 text-amber-400",
  resolved: "bg-neutral-800 text-neutral-500",
};

const MOMENT_TYPE_COLORS: Record<string, string> = {
  journal: "text-[#d4a574]",
  dream: "text-[#b0a0c0]",
  visitor_conversation: "text-[#8b9dc3]",
  consolidation: "text-[#9a8c7a]",
};

function formatDate(ts: string | null): string {
  if (!ts) return "";
  try {
    const d = new Date(ts);
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

export default function SeedTab({ agentId, onToast }: SeedTabProps) {
  const [section, setSection] = useState<MemorySection>("seeds");
  const [backstory, setBackstory] = useState<Memory[]>([]);
  const [organic, setOrganic] = useState<Memory[]>([]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [journal, setJournal] = useState<JournalEntry[]>([]);
  const [totems, setTotems] = useState<Totem[]>([]);
  const [moments, setMoments] = useState<DayMemory[]>([]);
  const [collection, setCollection] = useState<CollectionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newText, setNewText] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchAll = useCallback(async () => {
    const fetches = [
      fetch(`/api/agents/${agentId}/memories`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`/api/agents/${agentId}/threads`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`/api/agents/${agentId}/journal`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`/api/agents/${agentId}/totems`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`/api/agents/${agentId}/pool`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
      fetch(`/api/agents/${agentId}/collection`)
        .then((r) => (r.ok ? r.json() : null))
        .catch(() => null),
    ];

    const [memData, thrData, jrnData, totData, poolData, colData] =
      await Promise.all(fetches);

    if (memData) {
      setBackstory(memData.backstory || []);
      setOrganic(memData.organic || []);
    }
    if (thrData) setThreads(thrData.threads || []);
    if (jrnData) setJournal(jrnData.entries || []);
    if (totData) setTotems(totData.totems || []);
    if (poolData) setMoments(poolData.pool || []);
    if (colData) setCollection(colData.collection || []);

    setLoading(false);
  }, [agentId]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  async function handleAdd() {
    if (!newText.trim()) return;
    setAdding(true);
    try {
      const res = await fetch(`/api/agents/${agentId}/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: newText.trim(),
          title: newTitle.trim() || undefined,
        }),
      });
      if (res.ok) {
        setNewTitle("");
        setNewText("");
        setShowAddForm(false);
        onToast?.("Seed planted");
        await fetchAll();
      }
    } catch {
      // silent
    } finally {
      setAdding(false);
    }
  }

  async function handleDelete(sourceId: string) {
    try {
      const res = await fetch(
        `/api/agents/${agentId}/memories/${encodeURIComponent(sourceId)}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        await fetchAll();
      }
    } catch {
      // silent
    }
  }

  const sections: { key: MemorySection; label: string; count: number }[] = [
    { key: "seeds", label: "Seeds", count: backstory.length },
    { key: "threads", label: "Threads", count: threads.length },
    { key: "journal", label: "Journal", count: journal.length },
    { key: "totems", label: "Totems", count: totems.length },
    { key: "moments", label: "Moments", count: moments.length },
    { key: "collection", label: "Collection", count: collection.length },
  ];

  return (
    <div className="space-y-3">
      {/* Section pills */}
      <div className="flex gap-1 flex-wrap">
        {sections.map((s) => (
          <button
            key={s.key}
            onClick={() => setSection(s.key)}
            className={`px-2.5 py-1 rounded-md text-[11px] transition-colors ${
              section === s.key
                ? "bg-[#262626] text-white"
                : "text-[#737373] hover:text-white"
            }`}
          >
            {s.label} ({s.count})
          </button>
        ))}
      </div>

      {loading ? (
        <div className="space-y-2">
          {[...Array(3)].map((_, i) => (
            <div
              key={i}
              className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
            >
              <Skeleton className="h-3 w-20 mb-2" />
              <Skeleton className="h-2.5 w-full mb-1" />
              <Skeleton className="h-2.5 w-3/4" />
            </div>
          ))}
        </div>
      ) : section === "seeds" ? (
        <SeedsSection
          backstory={backstory}
          showAddForm={showAddForm}
          setShowAddForm={setShowAddForm}
          newTitle={newTitle}
          setNewTitle={setNewTitle}
          newText={newText}
          setNewText={setNewText}
          adding={adding}
          handleAdd={handleAdd}
          handleDelete={handleDelete}
        />
      ) : section === "threads" ? (
        <ThreadsSection threads={threads} />
      ) : section === "journal" ? (
        <JournalSection entries={journal} />
      ) : section === "totems" ? (
        <TotemsSection totems={totems} />
      ) : section === "moments" ? (
        <MomentsSection moments={moments} organic={organic} />
      ) : section === "collection" ? (
        <CollectionSection items={collection} />
      ) : null}
    </div>
  );
}

/* ── Seeds (existing backstory UI) ── */

function SeedsSection({
  backstory,
  showAddForm,
  setShowAddForm,
  newTitle,
  setNewTitle,
  newText,
  setNewText,
  adding,
  handleAdd,
  handleDelete,
}: {
  backstory: Memory[];
  showAddForm: boolean;
  setShowAddForm: (v: boolean) => void;
  newTitle: string;
  setNewTitle: (v: string) => void;
  newText: string;
  setNewText: (v: string) => void;
  adding: boolean;
  handleAdd: () => void;
  handleDelete: (id: string) => void;
}) {
  return (
    <div className="space-y-2">
      {backstory.length === 0 && !showAddForm && (
        <p className="text-xs text-[#525252] italic">
          No backstory yet. Plant memories to shape who she was before.
        </p>
      )}

      {backstory.map((mem) => (
        <BackstoryCard
          key={mem.source_id}
          sourceId={mem.source_id}
          text={mem.text_content}
          date={mem.ts_iso}
          onDelete={handleDelete}
        />
      ))}

      {showAddForm ? (
        <div className="p-3 bg-[#12121a] border border-[#d4a574]/30 rounded-lg space-y-2">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Title (optional)"
            className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded-md text-xs focus:outline-none focus:border-[#d4a574] transition-colors"
          />
          <textarea
            value={newText}
            onChange={(e) => setNewText(e.target.value)}
            placeholder="A moment, a feeling, a place..."
            rows={3}
            className="w-full px-3 py-2 bg-[#0a0a0f] border border-[#262620] rounded-md text-xs focus:outline-none focus:border-[#d4a574] transition-colors resize-y"
          />
          <div className="flex gap-2 justify-end">
            <button
              onClick={() => {
                setShowAddForm(false);
                setNewTitle("");
                setNewText("");
              }}
              className="px-3 py-1.5 text-xs text-[#737373] hover:text-white transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleAdd}
              disabled={!newText.trim() || adding}
              className="px-3 py-1.5 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] rounded-md text-xs font-medium disabled:opacity-50 transition-colors"
            >
              {adding ? "Planting..." : "Plant seed"}
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setShowAddForm(true)}
          className="w-full py-2 border border-dashed border-[#262620] text-[#737373] hover:text-[#d4a574] hover:border-[#d4a574]/30 rounded-lg text-xs transition-colors"
        >
          + Plant a backstory seed
        </button>
      )}
    </div>
  );
}

/* ── Threads ── */

function ThreadsSection({ threads }: { threads: Thread[] }) {
  if (threads.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic">
        No active threads yet.
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {threads.map((t) => (
        <div
          key={t.id}
          className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-[#e5e5e5] font-medium flex-1 truncate">
              {t.title}
            </span>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                THREAD_STATUS_COLORS[t.status] || "bg-neutral-800 text-neutral-400"
              }`}
            >
              {t.status}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-[#525252]">
            <span>{t.thread_type}</span>
            <span>{t.touch_count} touches</span>
            {t.last_touched && <span>{formatDate(t.last_touched)}</span>}
          </div>
          {t.tags.length > 0 && (
            <div className="flex gap-1 mt-1.5 flex-wrap">
              {t.tags.map((tag) => (
                <span
                  key={tag}
                  className="text-[9px] px-1.5 py-0.5 bg-[#1a1a2e] text-[#737373] rounded"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

/* ── Journal ── */

function JournalSection({ entries }: { entries: JournalEntry[] }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (entries.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic">No journal entries yet.</p>
    );
  }

  return (
    <div className="space-y-1.5">
      {entries.map((e) => {
        const isExpanded = expandedId === e.id;
        const preview =
          e.content.length > 120 ? e.content.slice(0, 120) + "..." : e.content;

        return (
          <div
            key={e.id}
            onClick={() => setExpandedId(isExpanded ? null : e.id)}
            className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg cursor-pointer hover:border-[#262620] transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              {e.mood && (
                <span className="text-[10px] px-1.5 py-0.5 bg-[#1a1a2e] text-[#d4a574] rounded">
                  {e.mood}
                </span>
              )}
              {e.day_alive != null && (
                <span className="text-[10px] text-[#525252]">
                  Day {e.day_alive}
                </span>
              )}
              <span className="text-[10px] text-[#525252] ml-auto">
                {formatDate(e.created_at)}
              </span>
            </div>
            <p className="text-xs text-[#a3a3a3] leading-relaxed whitespace-pre-wrap">
              {isExpanded ? e.content : preview}
            </p>
            {e.tags.length > 0 && (
              <div className="flex gap-1 mt-1.5 flex-wrap">
                {e.tags.map((tag) => (
                  <span
                    key={tag}
                    className="text-[9px] px-1.5 py-0.5 bg-[#1a1a2e] text-[#737373] rounded"
                  >
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ── Totems ── */

function TotemsSection({ totems }: { totems: Totem[] }) {
  if (totems.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic">No totems yet.</p>
    );
  }

  return (
    <div className="space-y-1.5">
      {totems.map((t) => (
        <div
          key={t.id}
          className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
        >
          <div className="flex items-center gap-2 mb-1.5">
            <span className="text-xs text-[#e5e5e5] font-medium flex-1">
              {t.entity}
            </span>
            {t.category && (
              <span className="text-[10px] px-1.5 py-0.5 bg-[#1a1a2e] text-[#737373] rounded">
                {t.category}
              </span>
            )}
          </div>
          {/* Weight bar */}
          <div className="flex items-center gap-2 mb-1">
            <div className="flex-1 h-1.5 bg-[#1a1a2e] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#d4a574] rounded-full"
                style={{ width: `${Math.round(t.weight * 100)}%` }}
              />
            </div>
            <span className="text-[10px] text-[#d4a574] w-8 text-right">
              {t.weight.toFixed(2)}
            </span>
          </div>
          {t.context && (
            <p className="text-[10px] text-[#525252] mt-1">{t.context}</p>
          )}
          <div className="flex gap-3 text-[10px] text-[#525252] mt-1">
            {t.first_seen && <span>First: {formatDate(t.first_seen)}</span>}
            {t.last_referenced && (
              <span>Last: {formatDate(t.last_referenced)}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Moments (day memory pool + organic memories) ── */

function MomentsSection({
  moments,
  organic,
}: {
  moments: DayMemory[];
  organic: Memory[];
}) {
  if (moments.length === 0 && organic.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic">
        No moments in the day memory pool yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {moments.length > 0 && (
        <div className="space-y-1.5">
          {moments.map((m) => (
            <div
              key={m.id}
              className="p-2.5 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
            >
              <div className="flex items-center gap-2 mb-1">
                <span
                  className={`text-[10px] ${
                    MOMENT_TYPE_COLORS[m.moment_type] || "text-[#525252]"
                  }`}
                >
                  {m.moment_type}
                </span>
                <span className="text-[10px] text-[#525252]">
                  {formatDate(m.ts)}
                </span>
                <span className="ml-auto text-[10px] text-[#d4a574]">
                  {"*".repeat(Math.min(Math.ceil(m.salience * 5), 5))}
                </span>
              </div>
              <p className="text-xs text-[#a3a3a3] leading-relaxed">
                {m.summary}
              </p>
            </div>
          ))}
        </div>
      )}

      {organic.length > 0 && (
        <>
          {moments.length > 0 && (
            <p className="text-[10px] text-[#525252] uppercase tracking-wider mt-2">
              Organic memories
            </p>
          )}
          <MemoryTimeline memories={organic} />
        </>
      )}
    </div>
  );
}

/* ── Collection ── */

function CollectionSection({ items }: { items: CollectionItem[] }) {
  if (items.length === 0) {
    return (
      <p className="text-xs text-[#525252] italic">
        No items in the collection yet.
      </p>
    );
  }

  return (
    <div className="space-y-1.5">
      {items.map((item) => (
        <div
          key={item.id}
          className="p-3 bg-[#12121a] border border-[#1e1e1a] rounded-lg"
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs text-[#e5e5e5] font-medium flex-1 truncate">
              {item.title}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 bg-[#1a1a2e] text-[#737373] rounded">
              {item.item_type}
            </span>
          </div>
          <div className="flex items-center gap-3 text-[10px] text-[#525252]">
            <span>{item.location}</span>
            <span>{item.origin}</span>
            {item.created_at && <span>{formatDate(item.created_at)}</span>}
          </div>
          {item.her_feeling && (
            <p className="text-[10px] text-[#9a8c7a] mt-1 italic">
              {item.her_feeling}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
