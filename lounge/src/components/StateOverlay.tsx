"use client";

import { useRef } from "react";

interface StateOverlayProps {
  mood: { valence: number; arousal: number } | null;
  energy: number;
  engagement_state: string;
  current_action: string | null;
  is_sleeping: boolean;
  drives: {
    curiosity: number;
    social_hunger: number;
    expression_need: number;
  } | null;
}

// 3x3 valence x arousal mood word matrix
function getMoodWord(valence: number, arousal: number): string {
  if (valence > 0.3 && arousal > 0.3) return "excited";
  if (valence > 0.3 && arousal < -0.1) return "serene";
  if (valence > 0.1) return "content";
  if (valence < -0.3 && arousal > 0.3) return "agitated";
  if (valence < -0.3) return "melancholic";
  if (valence < -0.1) return "pensive";
  if (arousal > 0.3) return "alert";
  if (arousal < -0.2) return "drowsy";
  return "neutral";
}

function getMoodColor(valence: number): string {
  if (valence > 0.2) return "#d4a574"; // warm amber
  if (valence < -0.2) return "#8b9dc3"; // cool blue-gray
  return "#9a8c7a"; // muted
}

function getActivityText(
  engagement_state: string,
  current_action: string | null,
  is_sleeping: boolean,
  drives: StateOverlayProps["drives"]
): string {
  if (is_sleeping) return "sleeping";
  if (current_action) return current_action.replace(/_/g, " ");
  if (engagement_state === "engaged") return "in conversation";
  if (drives) {
    const high: string[] = [];
    if (drives.curiosity > 0.6) high.push("curious");
    if (drives.expression_need > 0.6) high.push("expressive");
    if (drives.social_hunger > 0.6) high.push("sociable");
    if (high.length > 0) return high.join(" & ");
  }
  return engagement_state === "idle" ? "resting" : engagement_state;
}

const DRIVE_META: { key: keyof NonNullable<StateOverlayProps["drives"]>; label: string; color: string }[] = [
  { key: "curiosity", label: "curiosity", color: "#7ab8b8" },
  { key: "social_hunger", label: "social", color: "#c4869a" },
  { key: "expression_need", label: "expression", color: "#9a8cc4" },
];

function DriveBar({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="flex items-center gap-1.5 flex-1 min-w-0">
      <span className="text-[10px] text-[#525252] w-[54px] shrink-0 text-right">
        {label}
      </span>
      <div className="flex-1 h-[3px] rounded-full bg-[#161616] overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-[2s] ease-out"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  );
}

export default function StateOverlay({
  mood,
  energy,
  engagement_state,
  current_action,
  is_sleeping,
  drives,
}: StateOverlayProps) {
  // Anti-flicker: debounce mood word changes with 25s hold
  const moodWordRef = useRef<{ word: string; setAt: number }>({
    word: "neutral",
    setAt: 0,
  });

  const valence = mood?.valence ?? 0;
  const arousal = mood?.arousal ?? 0;
  const candidateWord = getMoodWord(valence, arousal);
  const now = Date.now();

  if (
    candidateWord !== moodWordRef.current.word &&
    now - moodWordRef.current.setAt > 25_000
  ) {
    moodWordRef.current = { word: candidateWord, setAt: now };
  }

  const moodWord = moodWordRef.current.word;
  const moodColor = getMoodColor(valence);
  const activity = getActivityText(engagement_state, current_action, is_sleeping, drives);
  const energyPct = Math.round(Math.max(0, Math.min(1, energy)) * 100);

  return (
    <div className="px-4 py-2 text-xs select-none space-y-1.5">
      {/* Row 1: Mood + Energy + Activity */}
      <div className="flex items-center gap-3">
        <span style={{ color: moodColor }} className="font-medium">
          {moodWord}
        </span>
        <div className="flex-1 max-w-[120px]">
          <div className="h-1.5 rounded-full bg-[#1a1a1a] overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-1000 ease-out"
              style={{
                width: `${energyPct}%`,
                background: `linear-gradient(90deg, ${moodColor}88, ${moodColor})`,
              }}
            />
          </div>
        </div>
        <span className="text-[#737373] truncate">{activity}</span>
      </div>

      {/* Row 2: Drive bars */}
      {drives && (
        <div className="flex gap-3">
          {DRIVE_META.map((d) => (
            <DriveBar
              key={d.key}
              label={d.label}
              value={drives[d.key]}
              color={d.color}
            />
          ))}
        </div>
      )}
    </div>
  );
}
