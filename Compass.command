#!/usr/bin/env bash
# macOS double-click launcher.
#
# Finder runs .command files in Terminal on double-click, which is the whole
# point of this file existing separately from run.sh.
#
# First time only: right-click → Open (macOS blocks double-clicking downloaded
# scripts until you've opened one once).
cd "$(dirname "$0")"
./run.sh
