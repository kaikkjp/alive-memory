# Incident + Fix Timeline (7-day window)

- Window UTC: `2026-02-13T06:26:42Z` to `2026-02-20T06:26:42Z`
- Source DB: `/Users/user/Documents/Tokyo-Arc/product/alive/data/prod_snapshot_20260220_1551.db`

## 1) Valence death-spiral risk
- Incident start: `2026-02-19T13:05:51.071366+00:00`
- Incident end: `2026-02-20T01:04:14.672326+00:00`
- Symptom: `72` cycles with mood_valence <= -0.85
- Root cause: cortex mood output could overpower homeostatic recovery; no hard floor/circuit-breaker.
- Fix commit: `f9683ed` (HOTFIX-001/002/003 — rate limit backoff, valence floor, thread dedup) at `2026-02-20 10:02:43 +0900`
- State continuity preserved: yes (same DB state carried across fix period).

## 2) Thread rumination / duplicate topic loop
- Incident start: `2026-02-19T13:47:15.580911+00:00`
- Incident end: `2026-02-20T01:01:20.122900+00:00`
- Symptom: `18` anti-pleasure-thread creations in the window
- Root cause: missing dedup + no rumination breaker in thread/context selection.
- Fix commit(s): `57a3ae8` (HOTFIX-003 thread dedup + rumination breaker) at `2026-02-20 10:07:02 +0900`, plus `f9683ed`.
- State continuity preserved: yes (threads retained; fix changed selection/creation behavior).

## 3) Visitor connect/boundary spam (Telegram race)
- Incident start: `2026-02-20T04:02:56.539475+00:00`
- Incident end: `2026-02-20T04:10:09.233656+00:00`
- Symptom: `7` `visitor_connect` events for `visitor:tg_678830487`
- Root cause: connect/session-boundary race on repeated messages from same visitor.
- Fix commit: `dfdedcc` (HOTFIX-005 visitor registration across entry points) at `2026-02-20 12:57:16 +0900`
- State continuity preserved: yes (visitor records persisted; connect signaling corrected).

## 4) External action error (web parser contract mismatch)
- Incident start: `2026-02-19T11:07:52.658930+00:00`
- Incident end: `2026-02-19T11:07:52.658930+00:00`
- Symptom: `web search failed: KeyError: 'choices'`
- Root cause: response shape mismatch while parsing external web call response.
- Fix: parser hardening in body/web execution path (description-level fix; no unique incident-tagged hash in this snapshot).
- State continuity preserved: yes (error isolated to action execution; core memory/state continued).
