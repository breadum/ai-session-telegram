#!/usr/bin/env bash
# Remove the systemd --user service. Does NOT touch hooks or ~/.ai-session-telegram.
#
#   ./service/uninstall.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT="ai-session-telegram.service"
DEST_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user disable --now "$UNIT" 2>/dev/null || true
rm -f "$DEST_DIR/$UNIT"
systemctl --user daemon-reload
echo "removed $DEST_DIR/$UNIT"
echo "(linger left as-is: 'loginctl disable-linger $USER' to undo that too)"
echo "(hooks left as-is: 'cd $REPO_DIR && uv run bridge uninstall-hooks' to remove them from settings.json)"
