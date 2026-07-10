#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="$ROOT_DIR/web"
TAURI_DIR="$WEB_DIR/src-tauri"

SKIP_CHECKS=0
if [[ "${1:-}" == "--skip-checks" ]]; then
  SKIP_CHECKS=1
fi

cd "$WEB_DIR"

VERSION="$(node -p "require('./package.json').version")"

if [[ "$SKIP_CHECKS" != "1" ]]; then
  npm run check
fi

npm run tauri:build

RELEASE_DIR="$TAURI_DIR/target/release"
EXE_PATH="$RELEASE_DIR/mistrelay-pc-client.exe"
if [[ ! -f "$EXE_PATH" ]]; then
  EXE_PATH="$RELEASE_DIR/mistrelay-pc-client"
fi

if [[ ! -f "$EXE_PATH" ]]; then
  echo "Release executable not found in $RELEASE_DIR" >&2
  exit 1
fi

PORTABLE_DIR="$RELEASE_DIR/bundle/portable"
mkdir -p "$PORTABLE_DIR"

PORTABLE_ZIP="$PORTABLE_DIR/MistRelay-PC-Client-$VERSION-windows-x64-portable.zip"
rm -f "$PORTABLE_ZIP"

if command -v zip >/dev/null 2>&1; then
  (cd "$(dirname "$EXE_PATH")" && zip -q "$PORTABLE_ZIP" "$(basename "$EXE_PATH")")
elif command -v powershell.exe >/dev/null 2>&1; then
  powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '$EXE_PATH' -DestinationPath '$PORTABLE_ZIP' -Force"
else
  echo "Neither zip nor powershell.exe is available to create the portable package" >&2
  exit 1
fi

echo "Portable package: $PORTABLE_ZIP"
echo "Installer output directory: $RELEASE_DIR/bundle/nsis"
