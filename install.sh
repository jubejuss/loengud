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
  # vana staatiline 2-tunnine ajastus maha, kui olemas
  OLD="$HOME/Library/LaunchAgents/ee.vileandkell.loengud.plist"
  launchctl bootout "gui/$(id -u)/ee.vileandkell.loengud" 2>/dev/null || true
  rm -f "$OLD"
  "$BIN_DIR/loengud" ajastus install
  echo "✓ Ajastus tunniplaani järgi. Vaata: loengud ajastus show · logi: ~/Library/Logs/loengud.log"
else
  echo "Ajastuse lisamiseks: ./install.sh --launchd"
fi
