#!/usr/bin/env bash
# Pulls the latest Compass code and restarts it cleanly -- the one command
# to run whenever there's an update, instead of the multi-step "cd here,
# pull, clear caches, restart" sequence that's easy to get wrong (wrong
# directory, forgetting to clear __pycache__, or restarting the wrong way
# if the background service is installed).
#
#   ./scripts/update.sh
#
# Refuses to pull over uncommitted local changes rather than risking a bad
# merge -- if that happens, it stops and tells you so nothing is silently
# clobbered. After pulling, it restarts Compass the right way for however
# it's actually running: through launchctl if the auto-start service
# (scripts/install-autostart.sh) is installed, or by telling you to
# restart it yourself if you start it by hand each time -- a script can't
# safely relaunch a process that's tied to a Terminal window it doesn't
# own. Either way, it finishes by actually checking the app came back up,
# rather than assuming a restart command succeeding means the app did.

set -euo pipefail

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s✗ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

say ""
say "${BOLD}🧭  Updating Compass${OFF}"
say ""

# --- refuse to pull over uncommitted local changes ---------------------------

if [ -n "$(git status --porcelain)" ]; then
    die "There are uncommitted local changes -- stopping before touching anything.
  Run 'git status' to see what they are. If you don't recognize them,
  don't guess -- ask before discarding or committing anything."
fi
ok "No uncommitted local changes"

# --- pull ----------------------------------------------------------------

BEFORE="$(git rev-parse HEAD)"
git pull
AFTER="$(git rev-parse HEAD)"

if [ "$BEFORE" = "$AFTER" ]; then
    ok "Already up to date -- nothing new to pull."
else
    ok "Updated:"
    git log --oneline "$BEFORE..$AFTER" | sed 's/^/    /'
fi

# --- clear stale bytecode ------------------------------------------------

find . -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
ok "Cleared cached Python bytecode"

# --- restart, the right way for how this machine runs it -----------------

LABEL="com.compass.homeschool"
if launchctl list 2>/dev/null | grep -q "$LABEL"; then
    say ""
    say "  Background service detected -- restarting it."
    launchctl kickstart -k "gui/$(id -u)/$LABEL"
    ok "Service restarted"
else
    say ""
    warn "No background service detected."
    pkill -f "streamlit run Home.py" 2>/dev/null && \
        ok "Stopped the running copy." || \
        say "  (Nothing was running.)"
    say "  Start it again yourself: ${BOLD}./run.sh --lan${OFF}"
    say ""
    say "  (Tip: scripts/install-autostart.sh sets this up to restart itself"
    say "  automatically next time, so this manual step goes away.)"
    exit 0
fi

# --- confirm it actually came back up -------------------------------------

# Overridable so tests can shrink a 20-second real-world wait down to
# nothing -- default values are what an actual restart needs.
RETRIES="${COMPASS_UPDATE_HEALTHCHECK_RETRIES:-10}"
RETRY_SLEEP="${COMPASS_UPDATE_HEALTHCHECK_SLEEP:-2}"

say ""
say "  Checking it's actually back up…"
for ((_i = 0; _i < RETRIES; _i++)); do
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8501 2>/dev/null | grep -q "^200$"; then
        ok "Compass is back up and responding."
        exit 0
    fi
    sleep "$RETRY_SLEEP"
done

warn "Compass hasn't responded yet after $((RETRIES * RETRY_SLEEP)) seconds."
say "  It may still be starting (a fresh dependency install takes longer) --"
say "  check again in a minute, or look at ~/Library/Logs/Compass/compass.error.log"
say "  if it's still not responding after that."
