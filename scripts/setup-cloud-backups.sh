#!/usr/bin/env bash
# Points Compass's automatic snapshots at Google Drive instead of this
# machine's own disk -- the "1 offsite copy" leg of a real backup plan. Every
# snapshot Compass already takes automatically (see compass/backup.py) then
# syncs to the cloud on its own, with nothing new to remember.
#
# Run once, after Google Drive for desktop is installed and signed in:
#
#   ./scripts/setup-cloud-backups.sh
#
# What it does: finds Google Drive's local synced folder, creates a "Compass
# Backups" folder inside it, moves any snapshots already sitting in this
# project's own backups/ folder over there, then replaces backups/ with a
# symlink pointing at the synced folder. Compass itself needs no code change
# -- it already just writes into "backups/", wherever that happens to point.
#
# Deliberately NOT syncing compass.db itself, only the snapshots: a cloud sync
# tool can corrupt a database file it catches mid-write, but a finished
# snapshot is never written to again once it exists, so it's safe to sync.

set -euo pipefail

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This looks for Google Drive for desktop's macOS sync folder -- macOS only." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_BACKUPS="$REPO_DIR/backups"

# --- find Google Drive's synced folder ---------------------------------------
# Modern Google Drive for desktop mounts each signed-in account at
# ~/Library/CloudStorage/GoogleDrive-<email>/My Drive. Older installs used
# ~/Google Drive directly -- checked as a fallback for anyone on an older
# version who hasn't been prompted to migrate yet.

CANDIDATES=()
if [ -d "$HOME/Library/CloudStorage" ]; then
    for dir in "$HOME/Library/CloudStorage"/GoogleDrive-*; do
        [ -d "$dir/My Drive" ] && CANDIDATES+=("$dir/My Drive")
    done
fi
if [ -d "$HOME/Google Drive/My Drive" ]; then
    CANDIDATES+=("$HOME/Google Drive/My Drive")
fi

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
    echo "Couldn't find a Google Drive folder yet." >&2
    echo "" >&2
    echo "Make sure Google Drive for desktop is installed, signed in, and has" >&2
    echo "finished its first sync (its menu bar icon stops spinning), then run" >&2
    echo "this again." >&2
    exit 1
fi

if [ "${1:-}" != "" ]; then
    DRIVE_FOLDER="${1:-}"
elif [ "${#CANDIDATES[@]}" -eq 1 ]; then
    DRIVE_FOLDER="${CANDIDATES[0]}"
else
    echo "Found more than one Google Drive account signed in:" >&2
    for c in "${CANDIDATES[@]}"; do
        echo "  $c" >&2
    done
    echo "" >&2
    echo "Re-run this, naming the one to use:" >&2
    echo "  ./scripts/setup-cloud-backups.sh \"${CANDIDATES[0]}\"" >&2
    exit 1
fi

CLOUD_BACKUPS="$DRIVE_FOLDER/Compass Backups"
mkdir -p "$CLOUD_BACKUPS"

# --- already set up? ----------------------------------------------------------

if [ -L "$LOCAL_BACKUPS" ]; then
    EXISTING_TARGET="$(readlink "$LOCAL_BACKUPS")"
    if [ "$EXISTING_TARGET" = "$CLOUD_BACKUPS" ]; then
        echo "✓ Already set up -- backups/ already points at:"
        echo "  $CLOUD_BACKUPS"
        exit 0
    fi
    echo "backups/ is already a symlink, but pointing somewhere else:" >&2
    echo "  $EXISTING_TARGET" >&2
    echo "Not touching it -- remove that symlink by hand first if you want to" >&2
    echo "switch to $CLOUD_BACKUPS instead." >&2
    exit 1
fi

# --- move any existing local snapshots over, then symlink --------------------

if [ -d "$LOCAL_BACKUPS" ]; then
    MOVED=0
    for f in "$LOCAL_BACKUPS"/*; do
        [ -e "$f" ] || continue
        mv -n "$f" "$CLOUD_BACKUPS/" && MOVED=$((MOVED + 1))
    done
    rmdir "$LOCAL_BACKUPS" 2>/dev/null || true
    [ "$MOVED" -gt 0 ] && echo "Moved $MOVED existing snapshot(s) into Google Drive."
fi

ln -s "$CLOUD_BACKUPS" "$LOCAL_BACKUPS"

echo "✓ Compass's snapshots now sync to Google Drive automatically."
echo "  backups/  →  $CLOUD_BACKUPS"
echo ""
echo "  Nothing to remember day to day -- the next automatic snapshot lands"
echo "  there on its own, and Google Drive uploads it in the background."
echo "  Check drive.google.com any time to confirm it's actually up there."
