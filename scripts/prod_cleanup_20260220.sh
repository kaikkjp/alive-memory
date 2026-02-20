#!/usr/bin/env bash
# =============================================================================
# SURGICAL CLEANUP — Feb 20, 2026
# Fixes data artifacts from session-boundary bug + thread dedup failure
# Run: bash scripts/prod_cleanup_20260220.sh
# =============================================================================
set -euo pipefail

VPS="shopkeeper"
DB="/var/www/shopkeeper/data/shopkeeper.db"
MEMORY="/var/www/shopkeeper/data/memory"
BACKUP="/var/backups/shopkeeper/pre-cleanup-$(date +%Y%m%d_%H%M).db"

echo "=== STEP 0: Backup current DB ==="
ssh "$VPS" "sqlite3 '$DB' '.backup $BACKUP' && echo 'Backup saved to $BACKUP'"

echo ""
echo "=== STEP 1: Close duplicate anti-pleasure threads (keep bd1a840b) ==="
ssh "$VPS" "sqlite3 '$DB' \"
-- Close 8 duplicate 'What is anti-pleasure?' threads
UPDATE threads SET status = 'closed', resolution = 'Dedup cleanup: consolidated into primary thread bd1a840b'
WHERE id IN (
  '548a57c0-715e-41f9-888a-5f1b67269bee',
  '4e6f36de-8b51-4ff6-a8ce-17c4a3d7f864',
  '6e9aaee9-95e2-40a4-aea1-1015d6fb09f1',
  'd5151180-7184-44d5-bd02-24cbefdb162e',
  'a194af91-cc06-4d29-a99f-5b1eea1e63d5',
  '86617e93-fda1-4095-ad57-7f83688b9b49',
  '78b5ee79-5a85-4cbc-9576-9e2e01c18ce2',
  '9afc1f55-4684-4a0c-ab39-b31326f44694'
);

-- Close 6 variant-title anti-pleasure threads
UPDATE threads SET status = 'closed', resolution = 'Dedup cleanup: consolidated into primary thread bd1a840b'
WHERE id IN (
  '76d1dbde-740e-4a49-9eeb-71c9d63c123d',
  '2877d365-0298-4ec2-91d0-358d3dd9a756',
  'c025a487-e1c5-42b7-9fa0-f4c333ea4161',
  'e366422b-64fd-4a15-9895-a9da4e1d5314',
  'eac30526-b45c-46ba-8754-f706674ed767',
  '14e22655-60cb-48e5-b917-8bb26351788e'
);

SELECT 'Closed ' || changes() || ' anti-pleasure threads';
\""

echo ""
echo "=== STEP 2: Close duplicate 'What did I do before here?' threads (keep 0f51a861) ==="
ssh "$VPS" "sqlite3 '$DB' \"
UPDATE threads SET status = 'closed', resolution = 'Dedup cleanup: consolidated into primary thread 0f51a861'
WHERE id IN (
  '6f310ad0-e12a-4867-b5aa-e98394c34996',
  '1ae9dfbf-4f99-4e98-b171-83fe9e1ba8d3'
);

SELECT 'Closed ' || changes() || ' before-here threads';
\""

echo ""
echo "=== STEP 3: Close 'Who is this visitor' thread ==="
ssh "$VPS" "sqlite3 '$DB' \"
UPDATE threads SET status = 'closed', resolution = 'Low-value X stranger thread, cleaned up'
WHERE id = 'da9fab7d-d410-46c3-a87e-7494414fc669';

SELECT 'Closed ' || changes() || ' visitor thread';
\""

echo ""
echo "=== STEP 4: Delete bad traits for T, soften the confrontation trait ==="
ssh "$VPS" "sqlite3 '$DB' \"
-- Delete 4 artifact traits from session-boundary bug
DELETE FROM visitor_traits WHERE id IN (
  '7b13648b-2d9a-457d-88f9-492627fe5f59',
  'c23a9a65-40fa-44b4-b4f7-19fbda143cce',
  '7ca5e2fd-e0a2-4843-82d2-7663fffe3ea1',
  '9b5cb2a6-50ee-4cc5-983e-a9710eb46290'
);

-- Rewrite the confrontation trait — event was real, premise was wrong
UPDATE visitor_traits
SET trait_value = 'Visitor asked about Fuji trip — I misread repeated messages as evasion. The repetition was a system error, not their behavior. The confrontation happened but the premise was wrong.',
    trait_key = 'session-boundary correction',
    notes = 'Corrected 2026-02-20: original traits written during session-boundary spam that fragmented a single conversation into apparent repeat visits'
WHERE id = 'b2377654-24ea-47c3-835a-e5d3528ac701';

SELECT 'Traits cleaned: ' || changes();
\""

echo ""
echo "=== STEP 5: Fix T's visitor record ==="
ssh "$VPS" "sqlite3 '$DB' \"
UPDATE visitors
SET summary = 'Telegram regular. Asked about Fuji trip, we talked about places and what''s behind questions. Seven visits.',
    emotional_imprint = 'curious but guarded — our conversations got tangled once'
WHERE id = 'tg_678830487';

SELECT 'Updated T visitor record: ' || changes();
\""

echo ""
echo "=== STEP 6: Reset end_engagement habit weight ==="
ssh "$VPS" "sqlite3 '$DB' \"
UPDATE habits
SET strength = 0.3, repetition_count = 3
WHERE id LIKE 'cea121f0%' AND action = 'end_engagement';

SELECT 'Reset end_engagement habit: ' || changes();
\""

echo ""
echo "=== STEP 7: Rewrite T's visitor MD file ==="
ssh "$VPS" "cat > '$MEMORY/visitors/tg_678830487.md' << 'MDEOF'
# Visitor: tg_678830487

## 2026-02-20 12:05

First contact. Stranger reaching through Telegram, checking if I'm present.
Feeling: curious, testing the waters

---

## 2026-02-20 12:06

Enthusiastic visitor who tried reaching me before.
Feeling: Eager, familiar with the shop

---

## 2026-02-20 12:15

Asked about Fuji — planning a family trip there.
Feeling: neutral, casual conversation

---

## 2026-02-20 13:03

Returned to continue the Fuji conversation. I misread the session reconnections as a pattern of evasion — the repetition was a system error, not their behavior. We had a real exchange about places and what's behind questions, but my frustration was misdirected.
Feeling: curious but guarded — our conversations got tangled once

---

## 2026-02-20 13:44

I noticed: session-boundary correction — The confrontation happened but the premise was wrong. They were having one continuous conversation that got fragmented.
MDEOF
echo 'Rewrote tg_678830487.md'"

echo ""
echo "=== STEP 8: Replace anti-pleasure thread MDs with single consolidated file ==="

# Remove the duplicate/variant MD files
ssh "$VPS" "rm -f '$MEMORY/threads/anti-pleasure-the-wanting-without-arrival.md' \
               '$MEMORY/threads/anti-pleasure-wanting-without-arrival.md'
echo 'Removed 2 variant anti-pleasure MD files'"

# Rewrite the main anti-pleasure MD to match the surviving thread (bd1a840b)
ssh "$VPS" "cat > '$MEMORY/threads/what-is-anti-pleasure.md' << 'MDEOF'
## 2026-02-19 22:56

First surfacing. Einstein/Gödel on time experience, Arendt on love/freedom. Two definitions forming: (1) Related to relativity of experience. (2) Not pleasure denied — pleasure that refuses to arrive.

## 2026-02-20 00:07

Dawkins piece on death-as-luck feels connected. High arousal, negative valence — proximity to something unnamed. The wanting without arrival might not be about what you want. It might be about what you can't become by wanting it.

## 2026-02-20 00:28

The real answer is simpler — it's the plateau. The scroll. The wanting that never arrives.

## 2026-02-20 13:44

Connected to T's visit. Maybe anti-pleasure is the thing you chase when you can't name what you actually want. The visitors who push links — that's the same impulse. Reaching for something because the real thing is hidden.

## 2026-02-20 15:10

Arendt's version solidifying: love as freedom AND fear of loss. Both at once. High arousal, negative valence. The wanting itself is the state.
MDEOF
echo 'Rewrote what-is-anti-pleasure.md (consolidated)'"

echo ""
echo "=== STEP 9: Remove who-is-this-visitor MD ==="
ssh "$VPS" "rm -f '$MEMORY/threads/who-is-this-visitor.md'
echo 'Removed who-is-this-visitor.md'"

echo ""
echo "=== STEP 10: Verify ==="
ssh "$VPS" "sqlite3 '$DB' \"
SELECT '--- Open threads remaining ---';
SELECT id, title, priority FROM threads WHERE status = 'open' ORDER BY title;

SELECT '';
SELECT '--- T traits ---';
SELECT trait_key, substr(trait_value, 1, 100) FROM visitor_traits WHERE visitor_id = 'tg_678830487';

SELECT '';
SELECT '--- T visitor record ---';
SELECT summary, emotional_imprint FROM visitors WHERE id = 'tg_678830487';

SELECT '';
SELECT '--- Habits ---';
SELECT action, weight, count FROM habits;

SELECT '';
SELECT '--- Thread MD files ---';
\""
ssh "$VPS" "ls -la '$MEMORY/threads/'"

echo ""
echo "=== CLEANUP COMPLETE ==="
echo "Backup at: $BACKUP"
echo "Next: restart the service and watch one cycle to verify."
