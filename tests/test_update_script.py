"""`scripts/update.sh` -- pulls the latest code and restarts Compass, the one
command to run instead of the fragile multi-step "cd here, pull, clear
caches, restart the right way" sequence.

Exercises it against a real (scratch) git remote/clone pair rather than
mocking git -- the whole point of this script is the git plumbing, so a
mock would test nothing real.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "update.sh"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def repos(tmp_path):
    """A bare `remote`, one clone (`origin_side`) that plays the role of
    commits Claude pushes, and a second clone (`local`) that plays the role
    of the Mac running Compass -- exactly the two-clone shape a real push
    and pull actually has."""
    remote = tmp_path / "remote.git"
    origin_side = tmp_path / "origin_side"
    local = tmp_path / "local"

    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(origin_side)], check=True)
    _git(origin_side, "config", "user.email", "test@example.com")
    _git(origin_side, "config", "user.name", "Test")

    scripts_dir = origin_side / "scripts"
    scripts_dir.mkdir()
    shutil.copy(SCRIPT, scripts_dir / "update.sh")
    (scripts_dir / "update.sh").chmod(0o755)
    (origin_side / "run.sh").write_text("# placeholder\n")

    _git(origin_side, "add", "-A")
    _git(origin_side, "commit", "-q", "-m", "initial")
    _git(origin_side, "push", "-q", "origin", "master")

    subprocess.run(["git", "clone", "-q", str(remote), str(local)], check=True)
    _git(local, "config", "user.email", "test@example.com")
    _git(local, "config", "user.name", "Test")

    return origin_side, local


def run_update(local: Path, path_prefix: str | None = None) -> subprocess.CompletedProcess:
    env = {
        "PATH": f"{path_prefix}:/usr/bin:/bin" if path_prefix else "/usr/bin:/bin",
        # Nothing is actually listening on 8501 in a test sandbox -- shrink
        # the real 20-second health-check wait down to effectively nothing.
        "COMPASS_UPDATE_HEALTHCHECK_RETRIES": "1",
        "COMPASS_UPDATE_HEALTHCHECK_SLEEP": "0",
    }
    return subprocess.run(
        ["bash", "scripts/update.sh"], cwd=local, env=env, capture_output=True, text=True
    )


def test_reports_already_up_to_date_when_there_is_nothing_new(repos):
    _, local = repos
    result = run_update(local)
    assert result.returncode == 0
    assert "Already up to date" in result.stdout


def test_pulls_new_commits_pushed_since_the_last_clone(repos):
    origin_side, local = repos
    (origin_side / "new_feature.txt").write_text("a new feature\n")
    _git(origin_side, "add", "-A")
    _git(origin_side, "commit", "-q", "-m", "Add a new feature")
    _git(origin_side, "push", "-q", "origin", "master")

    result = run_update(local)
    assert result.returncode == 0
    assert "Add a new feature" in result.stdout
    assert (local / "new_feature.txt").exists()


def test_refuses_to_pull_over_uncommitted_local_changes(repos):
    origin_side, local = repos
    (origin_side / "new_feature.txt").write_text("a new feature\n")
    _git(origin_side, "add", "-A")
    _git(origin_side, "commit", "-q", "-m", "Add a new feature")
    _git(origin_side, "push", "-q", "origin", "master")

    (local / "run.sh").write_text("# a stray local edit\n")

    result = run_update(local)
    assert result.returncode != 0
    assert "uncommitted local changes" in result.stdout + result.stderr
    # Nothing was touched -- the stray edit is still there, unpulled.
    assert "a stray local edit" in (local / "run.sh").read_text()
    assert not (local / "new_feature.txt").exists()


def test_tells_the_user_to_restart_by_hand_when_no_service_is_installed(repos, tmp_path):
    _, local = repos
    # No `launchctl` on PATH at all -- `command -v` / `grep -q` on its
    # absence should fail closed into the "no service" branch, not crash.
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    result = run_update(local, path_prefix=str(fake_bin))
    assert result.returncode == 0
    assert "No background service detected" in result.stdout
    assert "./run.sh --lan" in result.stdout


def test_restarts_via_launchctl_when_the_service_is_installed(repos, tmp_path):
    _, local = repos
    fake_bin = tmp_path / "fake_bin"
    fake_bin.mkdir()
    launchctl = fake_bin / "launchctl"
    launchctl.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "list" ]; then echo "1\\t0\\tcom.compass.homeschool"; exit 0; fi\n'
        'if [ "$1" = "kickstart" ]; then echo "KICKSTART $*" >&2; exit 0; fi\n'
        "exit 1\n"
    )
    launchctl.chmod(0o755)
    # Nothing is actually listening on 8501, so the health check degrades
    # to the "hasn't responded yet" warning -- the restart itself (which is
    # what this test cares about) still succeeded.
    result = run_update(local, path_prefix=str(fake_bin))
    assert "Background service detected" in result.stdout
    assert "Service restarted" in result.stdout
    assert "KICKSTART kickstart -k gui/" in result.stderr
