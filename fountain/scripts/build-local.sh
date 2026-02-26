#!/usr/bin/env bash
# Local release build for Fountain
# Produces: src-tauri/target/release/bundle/dmg/Fountain_<version>_aarch64.dmg
#
# Requirements:
#   brew install create-dmg
#   rustup (https://rustup.rs)
#   node + npm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.cargo/bin:$PATH"

# ── version from tauri.conf.json ──────────────────────────────────────────────
VERSION=$(python3 -c "import json,sys; print(json.load(open('$ROOT/src-tauri/tauri.conf.json'))['version'])")
ARCH=$(uname -m)  # arm64 / x86_64

APP_DIR="$ROOT/src-tauri/target/release/bundle/macos"
DMG_DIR="$ROOT/src-tauri/target/release/bundle/dmg"
DMG_OUT="$DMG_DIR/Fountain_${VERSION}_${ARCH}.dmg"

# ── preflight checks ──────────────────────────────────────────────────────────
echo "==> Checking prerequisites..."
for cmd in cargo npm node create-dmg python3; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "ERROR: '$cmd' not found."
    [[ "$cmd" == "create-dmg" ]] && echo "       Run: brew install create-dmg"
    exit 1
  fi
done

echo "    Fountain v${VERSION} — ${ARCH}"
echo "    Output : $DMG_OUT"
echo ""

# ── build ─────────────────────────────────────────────────────────────────────
echo "==> Installing JS dependencies..."
cd "$ROOT"
npm install --silent

echo "==> Building release .app (LTO + strip, this takes a few minutes)..."
npm run tauri build -- --bundles app

# ── package DMG ───────────────────────────────────────────────────────────────
rm -f "$APP_DIR"/rw.*.dmg 2>/dev/null || true
rm -f "$DMG_OUT" 2>/dev/null || true
mkdir -p "$DMG_DIR"

echo "==> Creating DMG..."
create-dmg \
  --volname "Fountain" \
  --icon-size 100 \
  --app-drop-link 350 140 \
  --skip-jenkins \
  "$DMG_OUT" \
  "$APP_DIR/"

# ── summary ───────────────────────────────────────────────────────────────────
echo ""
echo "==> Done!"
printf "    .app : %s\n" "$APP_DIR/Fountain.app"
printf "    .dmg : %s  (%s)\n" "$DMG_OUT" "$(du -sh "$DMG_OUT" | cut -f1)"
echo ""
echo "To install: open \"$DMG_OUT\""
