#!/usr/bin/env bash
# Freezes server.py into a standalone executable (PyInstaller) and drops it
# into app-desktop/src-tauri/binaries/ under the name Tauri's sidecar
# mechanism expects: <name>-<target-triple>[.exe]. Run this once before
# `pnpm tauri build` (or `pnpm tauri dev`) so the sidecar binary exists for
# Tauri to bundle/spawn - it isn't produced by pnpm build (that's the
# frontend only) and isn't versioned (see src-tauri/.gitignore).
#
# Must be run on the target OS: PyInstaller does not cross-compile. This
# has only been built and tested on macOS (aarch64-apple-darwin) so far -
# running it on Windows should work the same way in principle (uv and
# rustc both need to be installed there), but hasn't been verified yet.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

TARGET_TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
if [ -z "$TARGET_TRIPLE" ]; then
  echo "error: could not determine the Rust target triple (is rustc installed?)" >&2
  exit 1
fi

EXT=""
case "$TARGET_TRIPLE" in
  *windows*) EXT=".exe" ;;
esac

BIN_DIR="app-desktop/src-tauri/binaries"
DEST="$BIN_DIR/triton-server-$TARGET_TRIPLE$EXT"

echo "building triton-server for $TARGET_TRIPLE..."
uv run pyinstaller packaging/triton-server.spec --noconfirm

mkdir -p "$BIN_DIR"
cp "dist/triton-server$EXT" "$DEST"
chmod +x "$DEST"

echo "sidecar binary ready: $DEST"
