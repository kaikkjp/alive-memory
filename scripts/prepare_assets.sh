#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# Prepare frontend assets from source PNGs.
#
# 1. Run image-processing scripts (shop_interior, counter_foreground)
# 2. Copy character sprites into window/public/assets/sprites/
#
# Requires: Pillow (pip install Pillow)
# Source images must exist in assets/ (gitignored, copied manually to VPS)
#
# Usage:  bash scripts/prepare_assets.sh
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ─── Use venv python if available ───
if [ -x "${PROJECT_ROOT}/.venv/bin/python3" ]; then
    PYTHON="${PROJECT_ROOT}/.venv/bin/python3"
else
    PYTHON="python3"
fi

ASSETS_DIR="${PROJECT_ROOT}/assets"
PUBLIC_DIR="${PROJECT_ROOT}/window/public/assets"
SPRITES_DIR="${PUBLIC_DIR}/sprites"

# ─── Check source images exist ───
if [ ! -f "${ASSETS_DIR}/shop-back.png" ]; then
    echo "[prepare_assets] ERROR: ${ASSETS_DIR}/shop-back.png not found"
    echo "[prepare_assets] Source images must be placed in assets/ manually"
    exit 1
fi

SPRITE_COUNT=$(ls "${ASSETS_DIR}"/char-*-cropped.png 2>/dev/null | wc -l | tr -d ' ')
if [ "${SPRITE_COUNT}" -eq 0 ]; then
    echo "[prepare_assets] ERROR: No character sprites found in ${ASSETS_DIR}/"
    exit 1
fi

# ─── Create output directories ───
mkdir -p "${PUBLIC_DIR}" "${SPRITES_DIR}"

# ─── Generate derived images ───
echo "[prepare_assets] Generating shop_interior.png..."
${PYTHON} "${SCRIPT_DIR}/cut_window_mask.py"

echo "[prepare_assets] Generating counter_foreground.png..."
${PYTHON} "${SCRIPT_DIR}/slice_counter.py"

# ─── Copy character sprites ───
echo "[prepare_assets] Copying ${SPRITE_COUNT} character sprites..."
cp "${ASSETS_DIR}"/char-*-cropped.png "${SPRITES_DIR}/"

echo "[prepare_assets] Done. Assets ready in ${PUBLIC_DIR}/"
ls -lh "${PUBLIC_DIR}/"
ls -lh "${SPRITES_DIR}/"
