#!/usr/bin/env bash
# Compass launcher — macOS and Linux.
#
# Double-click `Compass.command` (macOS) or run `./run.sh` from a terminal.
# Handles the virtualenv, dependencies, and the API key so nobody has to
# remember any of it.
#
#   ./run.sh              open on this computer only
#   ./run.sh --lan        also reachable from other devices on the same network
#                         (a tablet, his laptop) — prints the address to use
#   ./run.sh --service    same as --lan, but never opens a browser tab. Used by
#                         the background auto-start service (see
#                         scripts/install-autostart.sh) — nobody's sitting at
#                         the keyboard to click through a tab that pops up.

set -euo pipefail
cd "$(dirname "$0")"

GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; BOLD=$'\033[1m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '%s✓%s %s\n' "$GREEN" "$OFF" "$*"; }
warn() { printf '%s!%s %s\n' "$YELLOW" "$OFF" "$*"; }
die()  { printf '%s✗ %s%s\n' "$RED" "$*" "$OFF" >&2; exit 1; }

say ""
say "${BOLD}🧭  Starting Compass${OFF}"
say ""

# macOS quarantines anything downloaded through a browser, so Gatekeeper blocks
# the launcher on every fresh download of the project. Once the user has
# approved it far enough for this script to be running, clear the flag from the
# whole folder — that covers files added by a later download too, so the warning
# does not come back. Silent and harmless on Linux, where xattr doesn't exist.
if [ "$(uname -s)" = "Darwin" ] && command -v xattr >/dev/null 2>&1; then
    if xattr -pr com.apple.quarantine . >/dev/null 2>&1; then
        xattr -dr com.apple.quarantine . 2>/dev/null && \
            ok "Cleared macOS quarantine — you won't be asked to approve this again."
    fi
fi

# --- Python ------------------------------------------------------------------

PY=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            PY="$candidate"; break
        fi
    fi
done
[ -n "$PY" ] || die "Python 3.10 or newer is required. Install it from python.org, then run this again."
ok "Python $($PY -c 'import platform; print(platform.python_version())')"

# --- Virtualenv + dependencies -----------------------------------------------
# Kept inside the project so it never collides with other Python work.

VENV=".venv"
if [ ! -d "$VENV" ]; then
    say "  First run — setting up. This takes a minute, only once."
    "$PY" -m venv "$VENV" || die "Could not create the virtual environment."
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

"$PY" -m pip install --quiet --upgrade pip
# Always run this, not just on first setup: gating it on "is streamlit already
# importable" meant a machine with an existing .venv silently kept running
# without any dependency added after that .venv was first created. pip with
# everything already satisfied is fast — there's no real cost to just asking
# every time.
"$PY" -m pip install --quiet -r requirements.txt || die "Dependency install failed."
ok "Dependencies ready"

# Streamlit prompts for an email on its very first run and blocks on stdin
# waiting for one. In a double-clicked window that reads as a hang. Pre-writing
# an empty credentials file skips the prompt permanently.
STREAMLIT_HOME="${HOME}/.streamlit"
if [ ! -f "$STREAMLIT_HOME/credentials.toml" ]; then
    mkdir -p "$STREAMLIT_HOME"
    printf '[general]\nemail = ""\n' > "$STREAMLIT_HOME/credentials.toml"
fi

# --- API key -----------------------------------------------------------------
# Order: whatever is already exported, else a local .env file (gitignored).

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f .env ]; then
    set -a; # shellcheck disable=SC1091
    source .env; set +a
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -t 0 ]; then
    # Creating a dotfile by hand is awkward on both macOS and Windows, so ask
    # for the key here and write the file. Only when there's a real terminal
    # attached — otherwise this would hang exactly the way Streamlit's email
    # prompt did.
    say ""
    say "  ${BOLD}No API key set up yet.${OFF}"
    say "  Paste your Anthropic API key to enable lesson generation, or just press"
    say "  Enter to skip — everything else in Compass works without one."
    say ""
    # The input is hidden so the key never lands in Terminal scrollback. Say so
    # explicitly: a prompt that shows nothing as you type is indistinguishable
    # from one that isn't receiving the paste at all.
    say "  ${YELLOW}Nothing will appear as you paste — that's deliberate.${OFF}"
    say "  Paste with Cmd-V, then press Enter."
    say ""
    printf '  API key: '
    read -r -s ENTERED || ENTERED=""
    say ""
    if [ -n "$ENTERED" ]; then
        say "  Received ${#ENTERED} characters."
    fi

    if [ -n "$ENTERED" ]; then
        case "$ENTERED" in
            sk-ant-*)
                printf 'ANTHROPIC_API_KEY=%s\n' "$ENTERED" > .env
                chmod 600 .env
                export ANTHROPIC_API_KEY="$ENTERED"
                ok "Saved to .env — you won't be asked again."
                ;;
            *)
                warn "That doesn't look like an Anthropic key (they start with 'sk-ant-')."
                say  "  Skipping for now. Lesson generation will be off."
                ;;
        esac
    fi
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    warn "Running without an API key — lesson generation is off."
    say  "  Everything else still works: the compliance dashboard, activity log,"
    say  "  math graph, choice topics, and life skills."
else
    ok "API key loaded (…${ANTHROPIC_API_KEY: -6})"
fi

# --- Network mode ------------------------------------------------------------

ADDRESS="localhost"
HEADLESS="false"
MODE="${1:-}"
if [ "$MODE" = "--lan" ] || [ "$MODE" = "--service" ]; then
    ADDRESS="0.0.0.0"
    IP=$("$PY" - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except OSError:
    print("")
finally:
    s.close()
PY
)
    say ""
    if [ -n "$IP" ]; then
        say "${BOLD}  On his tablet or laptop, open:  http://$IP:8501${OFF}"
        say "  (Or over Tailscale, using this machine's Tailscale address instead.)"
    else
        warn "Could not determine this machine's network address."
    fi
fi

if [ "$MODE" = "--service" ]; then
    # Running unattended under launchd -- there's no browser tab to pop open
    # and no terminal window for anyone to leave open or close.
    HEADLESS="true"
    say ""
    say "  Running as a background service."
else
    say ""
    say "  Opening Compass. ${BOLD}Leave this window open${OFF} while using it."
    say "  Press Ctrl-C here when finished."
    say ""
fi

exec "$PY" -m streamlit run Home.py \
    --server.address "$ADDRESS" \
    --server.port 8501 \
    --server.headless "$HEADLESS"
