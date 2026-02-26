#!/usr/bin/env bash
# Debug build script for Fountain
# Produces: src-tauri/target/debug/bundle/dmg/Fountain_0.1.0_aarch64.dmg
#
# Requirements: Rust/cargo, Node.js/npm, create-dmg (brew install create-dmg)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.cargo/bin:$PATH"

echo "==> Building .app bundle..."
cd "$ROOT"
npm run tauri build -- --debug --bundles app

APP_DIR="$ROOT/src-tauri/target/debug/bundle/macos"
DMG_DIR="$ROOT/src-tauri/target/debug/bundle/dmg"
DMG_OUT="$DMG_DIR/Fountain_0.1.0_aarch64.dmg"

# Clean up any leftover temp files inside the macos/ dir
rm -f "$APP_DIR"/rw.*.dmg 2>/dev/null || true

# Remove stale DMG if it exists
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

echo ""
echo "==> Done!"
echo "    .app : $APP_DIR/Fountain.app"
echo "    .dmg : $DMG_OUT"
ls -lh "$DMG_OUT"
