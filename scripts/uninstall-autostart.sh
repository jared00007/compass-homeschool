#!/usr/bin/env bash
# Undoes scripts/install-autostart.sh: stops the background service and
# removes it, so Compass goes back to only running when someone starts it
# by hand (double-clicking Compass.command, or ./run.sh / ./run.sh --lan).

set -euo pipefail

LABEL="com.compass.homeschool"
PLIST_PATH="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ ! -f "$PLIST_PATH" ]; then
    echo "Not installed -- nothing to undo."
    exit 0
fi

launchctl unload -w "$PLIST_PATH" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "✓ Background auto-start removed. Compass will no longer start itself at login."
echo "  Logs from earlier runs are still at ~/Library/Logs/Compass/ if you want them --"
echo "  harmless to leave, or delete that folder if you don't."
