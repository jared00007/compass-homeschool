"""Snapshots of the compliance record.

A year of logged hours is the family's legal documentation of instruction. It
lives in one SQLite file on one laptop, which means a failed drive, a spilled
drink, or a bad restore currently costs the whole year. This module makes that
recoverable.

Design notes:

* Snapshots use SQLite's own backup API rather than copying the file. A plain
  `cp` of a database with an open connection can capture a torn write; the
  backup API takes a consistent copy of a live database.
* Restore also goes through the backup API, in reverse, writing *into* the live
  connection. Swapping files underneath an open connection is how you get a
  process holding a handle to a database that no longer exists.
* Restoring always snapshots the current state first. A restore is the most
  destructive thing this app can do, and undoing it must be possible.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

BACKUP_DIRNAME = "backups"
SNAPSHOT_PATTERN = re.compile(
    r"^compass-(\d{4})-(\d{2})-(\d{2})-(\d{6})(?:-([a-z]+))?\.db$"
)

# Keep every snapshot from the last 30 days, then the earliest of each month
# forever. Monthly archives are small and a school year is only twelve of them.
KEEP_DAILY_DAYS = 30


@dataclass(frozen=True)
class Snapshot:
    path: Path
    taken_at: datetime
    reason: str
    size_bytes: int

    @property
    def label(self) -> str:
        return self.taken_at.strftime("%Y-%m-%d %H:%M")

    @property
    def size_kb(self) -> int:
        return max(self.size_bytes // 1024, 1)


def backup_dir(db_path: str | Path) -> Path:
    directory = Path(db_path).resolve().parent / BACKUP_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def snapshot(
    conn: sqlite3.Connection,
    db_path: str | Path,
    reason: str = "auto",
    now: datetime | None = None,
) -> Path:
    """Take a consistent copy of the live database.

    `now` sets the snapshot's timestamp and therefore its filename. It exists so
    the caller's clock is the single source of truth — an `auto_snapshot` that
    checked one date but wrote a filename stamped with another would have a
    daily guard that silently never matched.
    """
    now = now or datetime.now()
    safe_reason = re.sub(r"[^a-z]", "", reason.lower()) or "auto"
    directory = backup_dir(db_path)

    target = directory / f"compass-{now:%Y-%m-%d-%H%M%S}-{safe_reason}.db"
    # Two snapshots inside the same second would otherwise silently overwrite
    # each other — easy to trigger by double-clicking "Back up now".
    nudge = now
    while target.exists():
        nudge += timedelta(seconds=1)
        target = directory / f"compass-{nudge:%Y-%m-%d-%H%M%S}-{safe_reason}.db"

    destination = sqlite3.connect(target)
    try:
        conn.backup(destination)
    finally:
        destination.close()
    return target


def parse_snapshot(path: Path) -> Snapshot | None:
    match = SNAPSHOT_PATTERN.match(path.name)
    if not match:
        return None
    year, month, day, clock, reason = match.groups()
    try:
        taken_at = datetime.strptime(f"{year}{month}{day}{clock}", "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return Snapshot(
        path=path,
        taken_at=taken_at,
        reason=reason or "auto",
        size_bytes=path.stat().st_size if path.exists() else 0,
    )


def list_snapshots(db_path: str | Path) -> list[Snapshot]:
    """Newest first."""
    found = (parse_snapshot(p) for p in backup_dir(db_path).glob("compass-*.db"))
    return sorted((s for s in found if s), key=lambda s: s.taken_at, reverse=True)


def prune(db_path: str | Path, today: date | None = None) -> list[Path]:
    """Drop snapshots outside the retention policy. Returns what was removed."""
    today = today or date.today()
    snapshots = list_snapshots(db_path)
    removed: list[Path] = []
    monthly_kept: set[tuple[int, int]] = set()

    # Oldest first, so the *earliest* snapshot in a month is the one kept.
    for snap in sorted(snapshots, key=lambda s: s.taken_at):
        age_days = (today - snap.taken_at.date()).days
        if age_days <= KEEP_DAILY_DAYS:
            continue
        month_key = (snap.taken_at.year, snap.taken_at.month)
        if month_key not in monthly_kept:
            monthly_kept.add(month_key)
            continue
        try:
            snap.path.unlink()
            removed.append(snap.path)
        except OSError:
            pass
    return removed


def auto_snapshot(
    conn: sqlite3.Connection, db_path: str | Path, today: date | None = None
) -> Path | None:
    """Take one automatic snapshot per calendar day, then prune.

    Called on app startup. Returns None when today's snapshot already exists, so
    opening the app repeatedly costs nothing.
    """
    today = today or date.today()
    for snap in list_snapshots(db_path):
        if snap.taken_at.date() == today:
            return None
    stamp = datetime.combine(today, datetime.now().time())
    path = snapshot(conn, db_path, reason="auto", now=stamp)
    prune(db_path, today=today)
    return path


def restore(
    conn: sqlite3.Connection, db_path: str | Path, snapshot_path: str | Path
) -> Path:
    """Replace the live database with a snapshot's contents.

    Snapshots the current state first and returns that safety copy's path, so a
    mistaken restore is itself recoverable.
    """
    snapshot_path = Path(snapshot_path)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"No such snapshot: {snapshot_path}")

    safety = snapshot(conn, db_path, reason="prerestore")

    source = sqlite3.connect(snapshot_path)
    try:
        # Writes into the live connection rather than swapping files, so any
        # handle the app is already holding stays valid.
        source.backup(conn)
    finally:
        source.close()
    conn.commit()
    return safety
