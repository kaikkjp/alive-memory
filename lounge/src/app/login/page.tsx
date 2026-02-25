"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import ConsciousnessCanvas from "@/components/ConsciousnessCanvas";

export default function LoginPage() {
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [shake, setShake] = useState(false);
  const router = useRouter();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      const data = await res.json();

      if (data.authenticated) {
        router.push("/dashboard");
      } else {
        setError("Invalid token");
        setShake(true);
        setTimeout(() => setShake(false), 500);
      }
    } catch {
      setError("Connection error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative flex items-center justify-center min-h-screen px-4">
      {/* Dormant organism background */}
      <ConsciousnessCanvas
        energy={0.2}
        curiosity={0.3}
        social_hunger={0.3}
        expression_need={0.2}
        mood_valence={0}
        is_sleeping={true}
        className="z-0"
      />

      <div className="relative z-10 w-full max-w-sm">
        <h1 className="text-2xl font-light tracking-[0.2em] uppercase text-center mb-1">
          ALIVE
        </h1>
        <p className="text-[#9a8c7a] text-sm mb-10 text-center">
          Private Lounge
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="password"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="mgr-..."
            className={`w-full px-4 py-3 bg-[#0a0a0f]/80 backdrop-blur border border-[#262620] rounded-lg text-sm focus:outline-none focus:border-[#d4a574] transition-all ${
              shake ? "animate-[shake_0.5s_ease-in-out]" : ""
            }`}
            autoFocus
          />

          {error && (
            <p className="text-[#ef4444] text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !token.trim()}
            className="w-full py-3 bg-[#d4a574] hover:bg-[#c4955a] text-[#0a0a0a] disabled:opacity-50 disabled:cursor-not-allowed rounded-lg text-sm font-medium transition-colors"
          >
            {loading ? "..." : "Enter"}
          </button>
        </form>

        <p className="text-[#525252] text-xs text-center mt-6">
          By invitation
        </p>
      </div>
    </div>
  );
}
