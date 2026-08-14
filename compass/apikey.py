"""Anthropic API key management -- reads and writes the same `.env` file
run.sh's own first-run prompt uses, so a key entered here and a key pasted
into a terminal prompt stay in sync no matter which path the parent takes.

Deliberately kept out of the database: compass.db gets synced to Google
Drive by the backup script, and a secret has no business riding along in a
cloud-synced file. `.env` is gitignored and stays local to the machine.
"""

from __future__ import annotations

import os
import re

from compass.config import PROJECT_ROOT

ENV_PATH = PROJECT_ROOT / ".env"
_KEY_LINE = re.compile(r"^ANTHROPIC_API_KEY=.*$", re.MULTILINE)


def masked_key() -> str | None:
    """The last 6 characters of whatever key the running process would
    actually use right now, or None if nothing is set -- enough to confirm
    which key is active without ever displaying the whole thing."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    return f"…{key[-6:]}" if len(key) > 6 else f"…{key}"


def save_key(key: str) -> None:
    """Writes the key into .env (creating it if needed, preserving any
    other lines already there) and updates the running process's own
    environment so the very next lesson generation picks it up --
    no restart of the background service required."""
    key = key.strip()
    line = f"ANTHROPIC_API_KEY={key}"
    existing = ENV_PATH.read_text() if ENV_PATH.exists() else ""
    if _KEY_LINE.search(existing):
        text = _KEY_LINE.sub(line, existing)
    elif existing.strip():
        text = existing.rstrip("\n") + f"\n{line}\n"
    else:
        text = line + "\n"
    ENV_PATH.write_text(text)
    ENV_PATH.chmod(0o600)
    os.environ["ANTHROPIC_API_KEY"] = key
