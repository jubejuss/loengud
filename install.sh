#!/usr/bin/env bash
# Paigaldab `loengud` tööriista Maci: venv, käsk ~/.local/bin/loengud, valikuliselt launchd ajastus.
set -euo pipefail
cd "$(dirname "$0")"

VENV="$HOME/.local/share/loengud/venv"
BIN_DIR="$HOME/.local/bin"
PY="${PYTHON:-python3}"

"$PY" -c 'import sys; assert sys.version_info >= (3,10), "Vaja Python 3.10+"'
mkdir -p "$BIN_DIR" "$(dirname "$VENV")"
[ -d "$VENV" ] || "$PY" -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -e .
ln -sf "$VENV/bin/loengud" "$BIN_DIR/loengud"
echo "✓ loengud → $BIN_DIR/loengud"

[ -f "$HOME/.config/loengud/config.yaml" ] || "$BIN_DIR/loengud" init

if [ "${1:-}" = "--launchd" ]; then
  PLIST="$HOME/Library/LaunchAgents/ee.vileandkell.loengud.plist"
  sed -e "s#__HOME__#$HOME#g" -e "s#__BIN__#$BIN_DIR/loengud#g" launchd/ee.vileandkell.loengud.plist > "$PLIST"
  launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "✓ launchd ajastus aktiivne (iga 2 h). Logi: ~/Library/Logs/loengud.log"
else
  echo "Ajastuse lisamiseks: ./install.sh --launchd"
fi
