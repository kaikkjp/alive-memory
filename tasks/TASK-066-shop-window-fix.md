# TASK-066: Shop Window Fix

**Priority: Critical — the product is broken for visitors**

## Problem

The shop window (public visitor-facing page) has multiple broken features. Visitors cannot see the shopkeeper, enter the shop reliably, or read her inner monologue. The CSP eval() block is likely the root cause of several failures.

## Bugs to fix

### 1. Shopkeeper sprite not rendering

Diagnose why the sprite doesn't appear. Check:
- `pipeline/sprite_gen.py` output — is it generating valid image paths?
- Asset paths — do the generated paths resolve to actual files?
- CSS/HTML image element — is the `<img>` or background-image correctly referencing the asset?
- CSP — is Content Security Policy blocking dynamic image loading (e.g. `img-src` directive)?

### 2. CSP eval() block

Find **all** instances of:
- `eval()`
- `new Function()`
- String-based `setTimeout()` / `setInterval()` (i.e., passing a string instead of a function reference)

Replace with proper alternatives:
- `eval()` → parse JSON with `JSON.parse()`, or restructure logic
- `new Function()` → use regular function definitions
- `setTimeout("code", ms)` → `setTimeout(() => { code }, ms)`

This is likely the root cause of multiple failures including sprite rendering and button behavior.

### 3. "Enter Shop" CTA missing

The "Enter Shop" call-to-action should appear before a visitor session starts. Find where it should be rendered (likely in the initial page state before WebSocket connection), and add it. This is the primary conversion point — without it, visitors see the shop but can't interact.

### 4. Leave button broken

The leave/exit button doesn't work. This is likely a downstream effect of the CSP eval() block — verify it works after fixing bug #2. If not, diagnose separately.

### 5. Inner monologue text readability

Her inner monologue text floats over the scene with no background, making it unreadable depending on the scene image. Fix options:
- Add a semi-transparent dark container/card behind the text
- Move inner monologue to a dedicated panel (sidebar or footer)
- Use text-shadow + background combination for contrast

### 6. Text overflow

Content is clipping with `...` truncation, suggesting CSS `text-overflow: ellipsis` or `overflow: hidden` without a scroll mechanism. Either:
- Allow scrolling within the text container
- Expand the container to fit content
- Use a "show more" pattern for long content

## Scope

**Files you may touch:**
- `window/` — HTML/CSS/JS frontend (all files)
- `pipeline/sprite_gen.py` — sprite path generation
- `pipeline/scene.py` — valid state combos
- `heartbeat_server.py` — serves the page, WebSocket events
- Static assets / templates

**Files you may NOT touch:**
- `pipeline/cortex.py`
- `db.py`
- `heartbeat.py`

## Approach

1. Start with bug #2 (CSP eval) — this likely unblocks multiple other issues
2. After CSP fix, re-check bugs #1 and #4 — they may resolve automatically
3. Fix remaining bugs in order of user impact

## Verification

- Shopkeeper sprite visible in window
- Enter Shop CTA appears for new visitors
- Leave button works
- Inner monologue readable against any scene background
- No CSP errors in browser console (`document.addEventListener('securitypolicyviolation', ...)`)
- All functionality works without eval()

## Definition of done

Visitors can see the shopkeeper, enter the shop, interact, and leave. No CSP violations. Inner monologue is readable. No text overflow.
