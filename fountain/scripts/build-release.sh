#!/usr/bin/env bash
# Release build script for Fountain
# Produces: src-tauri/target/release/bundle/dmg/Fountain_{version}_aarch64.dmg
#
# Usage: ./build-release.sh
# Version is read from tauri.conf.json automatically.
#
# Requirements: Rust/cargo, Node.js/npm, create-dmg (brew install create-dmg)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export PATH="$HOME/.cargo/bin:$PATH"

# Read version from tauri.conf.json
VERSION=$(python3 -c "import json; print(json.load(open('$ROOT/src-tauri/tauri.conf.json'))['version'])")
echo "==> Fountain v${VERSION} release build"

echo "==> Building .app bundle (release)..."
cd "$ROOT"
npm run tauri build -- --bundles app

APP_DIR="$ROOT/src-tauri/target/release/bundle/macos"
DMG_DIR="$ROOT/src-tauri/target/release/bundle/dmg"
DMG_OUT="$DMG_DIR/Fountain_${VERSION}_aarch64.dmg"

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
echo "==> Done! Fountain v${VERSION} release build complete."
echo "    .app : $APP_DIR/Fountain.app ($(du -sh "$APP_DIR/Fountain.app" | cut -f1))"
echo "    .dmg : $DMG_OUT ($(du -sh "$DMG_OUT" | cut -f1))"
