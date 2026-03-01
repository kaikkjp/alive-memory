"use client";

import { useRef, useEffect, useCallback } from "react";

export interface ConsciousnessCanvasProps {
  mood_valence?: number; // -1 to 1
  energy?: number; // 0 to 1
  curiosity?: number; // 0 to 1
  social_hunger?: number; // 0 to 1
  expression_need?: number; // 0 to 1
  is_sleeping?: boolean;
  is_dreaming?: boolean;
  is_thinking?: boolean;
  className?: string;
}

// Lerp helper — smoothly interpolate toward target
function lerp(current: number, target: number, rate: number): number {
  return current + (target - rate) * 0 + (target - current) * rate;
}

// Clamp helper
function clamp(v: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, v));
}

// Detect point count from canvas width
function getPointCount(width: number): number {
  if (width < 500) return 4000;
  if (width < 900) return 8000;
  return 15000;
}

// Mood-based color interpolation
function moodColor(
  valence: number,
  component: "r" | "g" | "b",
  type: "stroke" | "bg"
): number {
  if (type === "stroke") {
    const warm = { r: 255, g: 240, b: 220 };
    const neutral = { r: 255, g: 255, b: 255 };
    const cool = { r: 220, g: 230, b: 255 };
    if (valence >= 0) {
      const t = valence;
      return Math.round(neutral[component] + (warm[component] - neutral[component]) * t);
    } else {
      const t = -valence;
      return Math.round(neutral[component] + (cool[component] - neutral[component]) * t);
    }
  }
  const warmBg = { r: 12, g: 10, b: 8 };
  const neutralBg = { r: 8, g: 8, b: 10 };
  const coolBg = { r: 8, g: 8, b: 14 };
  if (valence >= 0) {
    const t = valence;
    return Math.round(neutralBg[component] + (warmBg[component] - neutralBg[component]) * t);
  } else {
    const t = -valence;
    return Math.round(neutralBg[component] + (coolBg[component] - neutralBg[component]) * t);
  }
}

export default function ConsciousnessCanvas({
  mood_valence = 0,
  energy = 0.5,
  curiosity = 0.45,
  social_hunger = 0.5,
  expression_need = 0.4,
  is_sleeping = false,
  is_dreaming = false,
  is_thinking = false,
  className = "",
}: ConsciousnessCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const stateRef = useRef({
    // Animation clock — never resets
    t: 0,
    // Current interpolated values
    speed: Math.PI / 45,
    alpha: 40 + energy * 80,
    complexity: 8 - curiosity * 4,
    amplitude: 0.7 + social_hunger * 0.6,
    strokeR: 255,
    strokeG: 255,
    strokeB: 255,
    bgR: 8,
    bgG: 8,
    bgB: 10,
    // Dream flare state
    flareActive: false,
    flareFrames: 0,
    nextFlareIn: 180, // frames (~6s at 30fps)
    // Dream flare "bias forces" — random nudges to existing params
    // (RujiK approach: don't add new systems, push existing knobs)
    flareDriveIdx: 0,        // which drive channel to spike (0/1/2)
    flareDriveBias: 0,       // how much to push it (0.2–0.6)
    flareComplexityBias: 0,  // nudge complexity (±1.5)
    flareAlphaBias: 0,       // nudge alpha (10–40)
    flareBlend: 0,           // 0→1→0 smooth envelope
    // Frame skip for target ~18fps
    lastFrame: 0,
    pointCount: 15000,
  });

  const propsRef = useRef({
    mood_valence,
    energy,
    curiosity,
    social_hunger,
    expression_need,
    is_sleeping,
    is_dreaming,
    is_thinking,
  });

  // Update props ref on every render
  propsRef.current = {
    mood_valence,
    energy,
    curiosity,
    social_hunger,
    expression_need,
    is_sleeping,
    is_dreaming,
    is_thinking,
  };

  const render = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const now = performance.now();
    const st = stateRef.current;
    const props = propsRef.current;

    // Target ~18fps — skip frames
    if (now - st.lastFrame < 55) {
      animRef.current = requestAnimationFrame(render);
      return;
    }
    st.lastFrame = now;

    // Compute targets from props
    let targetSpeed: number;
    if (props.is_sleeping && props.is_dreaming && st.flareActive) {
      targetSpeed = Math.PI / 20;
    } else if (props.is_sleeping) {
      targetSpeed = Math.PI / 120;
    } else if (props.is_thinking) {
      targetSpeed = Math.PI / 40;
    } else {
      targetSpeed = Math.PI / 45;
    }

    const sleepAlphaFactor = props.is_sleeping ? 0.6 : 1.0;
    const thinkAlphaFactor = props.is_thinking ? 1.15 : 1.0;
    const targetAlpha =
      (40 + props.energy * 80) * sleepAlphaFactor * thinkAlphaFactor;

    const targetComplexity = clamp(8 - props.curiosity * 4, 4, 8);
    const targetAmplitude = (0.7 + props.social_hunger * 0.6) * (props.is_sleeping ? 0.7 : 1.0);

    const v = props.mood_valence;
    const targetStrokeR = moodColor(v, "r", "stroke");
    const targetStrokeG = moodColor(v, "g", "stroke");
    const targetStrokeB = moodColor(v, "b", "stroke");

    const sleepBg = props.is_sleeping;
    const targetBgR = sleepBg ? 4 : moodColor(v, "r", "bg");
    const targetBgG = sleepBg ? 4 : moodColor(v, "g", "bg");
    const targetBgB = sleepBg ? 6 : moodColor(v, "b", "bg");

    // Interpolate all values (smooth transitions 3-5s)
    const rate = 0.02;
    st.speed = lerp(st.speed, targetSpeed, rate);
    st.alpha = lerp(st.alpha, targetAlpha, rate);
    st.complexity = lerp(st.complexity, targetComplexity, rate);
    st.amplitude = lerp(st.amplitude, targetAmplitude, rate);
    st.strokeR = lerp(st.strokeR, targetStrokeR, rate);
    st.strokeG = lerp(st.strokeG, targetStrokeG, rate);
    st.strokeB = lerp(st.strokeB, targetStrokeB, rate);
    st.bgR = lerp(st.bgR, targetBgR, rate);
    st.bgG = lerp(st.bgG, targetBgG, rate);
    st.bgB = lerp(st.bgB, targetBgB, rate);

    // ─── Dream flare logic ───
    // Each flare rolls random "bias forces" on existing parameters.
    // The existing math does all the visual work — we just push its knobs.
    if (props.is_dreaming && props.is_sleeping) {
      st.nextFlareIn--;
      if (st.nextFlareIn <= 0 && !st.flareActive) {
        st.flareActive = true;
        st.flareFrames = 14 + Math.random() * 8; // ~0.8-1.2s
        // Roll this dream's bias forces
        st.flareDriveIdx = (Math.random() * 3) | 0;          // pick a drive channel
        st.flareDriveBias = 0.2 + Math.random() * 0.4;       // spike it by 0.2–0.6
        st.flareComplexityBias = (Math.random() - 0.5) * 3;  // nudge complexity ±1.5
        st.flareAlphaBias = 10 + Math.random() * 30;         // brighten by 10–40
      }
      if (st.flareActive) {
        st.flareFrames--;
        // Smooth envelope
        if (st.flareFrames > 12) {
          st.flareBlend = lerp(st.flareBlend, 1.0, 0.25);
        } else if (st.flareFrames < 5) {
          st.flareBlend = lerp(st.flareBlend, 0.0, 0.2);
        }
        if (st.flareFrames <= 0) {
          st.flareActive = false;
          st.flareBlend = 0;
          st.nextFlareIn = Math.floor(54 + Math.random() * 90);
        }
      }
    } else {
      st.flareActive = false;
      st.flareBlend = lerp(st.flareBlend, 0, 0.1);
    }

    // Advance clock
    st.t += st.speed;

    const w = canvas.width;
    const h = canvas.height;

    // Clear with background color
    ctx.fillStyle = `rgb(${Math.round(st.bgR)},${Math.round(st.bgG)},${Math.round(st.bgB)})`;
    ctx.fillRect(0, 0, w, h);

    // ─── Point rendering ───
    // Apply flare bias forces to existing params — that's it
    const fb = st.flareBlend;
    const alpha = clamp(Math.round(st.alpha + fb * st.flareAlphaBias), 0, 255);
    const complexity = clamp(st.complexity + fb * st.flareComplexityBias, 3, 9);
    const amp = st.amplitude;

    ctx.fillStyle = `rgba(${Math.round(st.strokeR)},${Math.round(st.strokeG)},${Math.round(st.strokeB)},${alpha / 255})`;

    const t = st.t;

    // Drive weights with flare bias injected into one channel
    const driveWeights = [props.curiosity, props.social_hunger, props.expression_need];
    driveWeights[st.flareDriveIdx] = clamp(
      driveWeights[st.flareDriveIdx] + fb * st.flareDriveBias,
      0, 1
    );

    // Center offset for the form — scale to canvas size
    const cx = w * 0.5;
    const cy = h * 0.46;
    const scale = Math.min(w, h) / 400;

    for (let i = st.pointCount; i--; ) {
      const y = i / 500;
      const k = Math.cos(y * 5) * (y < 11 ? 21 : 11);
      const e = y / 8 - 13;
      const o = Math.sqrt(k * k + e * e) / complexity;

      const phaseGroup = i % 3;
      const driveOffset = 6 + driveWeights[phaseGroup] * 4;

      const q =
        k * 2 +
        49 +
        Math.cos(y) / k +
        k * Math.cos(y / 2) * (amp * (1 + Math.sin(o * 4 - e / 2 - t)));
      const c = o / 1.5 - e / 5 - t / 8 + phaseGroup * driveOffset;

      const px = q * Math.sin(c) * scale + cx;
      const py = q * Math.cos(c) * scale + cy - 79 * Math.sin(c / 2) * scale;

      ctx.fillRect(px, py, 1, 1);
    }

    animRef.current = requestAnimationFrame(render);
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    // Check prefers-reduced-motion
    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // Size canvas at 0.5x viewport for softness
    const resize = () => {
      const rect = canvas.parentElement?.getBoundingClientRect();
      if (!rect) return;
      const dpr = 0.5; // intentionally soft
      canvas.width = Math.floor(rect.width * dpr);
      canvas.height = Math.floor(rect.height * dpr);
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      stateRef.current.pointCount = getPointCount(rect.width);
    };

    resize();
    const observer = new ResizeObserver(resize);
    if (canvas.parentElement) observer.observe(canvas.parentElement);

    if (prefersReduced) {
      // Render single frame and stop
      stateRef.current.t = 1; // some non-zero value for form
      const renderOnce = () => {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        render();
        cancelAnimationFrame(animRef.current);
      };
      requestAnimationFrame(renderOnce);
    } else {
      animRef.current = requestAnimationFrame(render);
    }

    return () => {
      cancelAnimationFrame(animRef.current);
      observer.disconnect();
    };
  }, [render]);

  return (
    <div className={`absolute inset-0 overflow-hidden ${className}`}>
      <canvas ref={canvasRef} className="block" />
    </div>
  );
}
