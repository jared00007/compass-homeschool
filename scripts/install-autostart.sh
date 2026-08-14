#!/usr/bin/env bash
# Installs Compass as a background service that starts automatically at
# login and restarts itself if it ever crashes -- so nobody has to remember
# to open Terminal and run `./run.sh --lan` before the day starts.
#
# macOS only. Run this once, from a Terminal, on whichever Mac holds
# compass.db (the "host" machine other devices connect to):
#
#   ./scripts/install-autostart.sh
#
# To undo it: ./scripts/uninstall-autostart.sh
#
# Once this is installed, do not also start Compass manually from Terminal --
# the service already has port 8501, and a second copy will just fail to
# bind it. Check `scripts/install-autostart.sh` did its job with:
#
#   launchctl list | grep compass

set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This installs a macOS background service (launchd) -- macOS only." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.compass.homeschool"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/Compass"

mkdir -p "$PLIST_DIR" "$LOG_DIR"

# A fixed, generous PATH rather than relying on launchd to inherit one --
# launchd's own default PATH is a bare minimum (/usr/bin:/bin:/usr/sbin:/sbin)
# that leaves out Homebrew's python3, wherever it happens to live (Apple
# Silicon vs. Intel put it in different places). Without this, the service
# can fail with "Python 3.10 or newer is required" even though `./run.sh`
# works fine by hand in a normal Terminal, which does pick up Homebrew's PATH
# through the shell's own profile.
cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>cd "$REPO_DIR" &amp;&amp; exec ./run.sh --service</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/compass.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/compass.error.log</string>
</dict>
</plist>
PLIST

# Unload any previous copy first -- reloading an already-loaded label errors
# instead of replacing it, and this script is meant to be safe to re-run
# after an update.
launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load -w "$PLIST_PATH"

echo "✓ Compass will now start automatically at login, and restart itself if it crashes."
echo ""
echo "  Logs:   $LOG_DIR/compass.log"
echo "          $LOG_DIR/compass.error.log"
echo "  Check:  launchctl list | grep compass"
echo ""
echo "  It's running now too -- give it a few seconds, then try the address"
echo "  you'd normally use from another device."
echo ""
echo "  Stop relying on this: ./scripts/uninstall-autostart.sh"
