"""Fixes from a Windows tester's morning-pipeline report (2026-10-11).

Each test pins one finding that was real on a shipped install:

- #8 setup-rag.ps1 published Open WebUI on every interface (`-p 3000:8080`),
  and an existing container kept that binding through re-runs and updates.
- #5 only four of the content folders were gitignored, so a user's real
  People notes sat untracked and unignored in the vault's own git tree.
- #4 security-checks.sh called a bare `python3` (the Microsoft Store stub on
  Windows), and its integrity check passed whenever the control exited
  non-zero -- including when the baseline had silently failed.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CHECKS = REPO / "installers" / "lib" / "security-checks.sh"
WIN = REPO / "Templates" / "Scripts" / "windows"

# The vault's content folders (CLAUDE.md, "What this repository is"), less
# Templates/, which is scaffolding and ships.
CONTENT_FOLDERS = ("Actions", "Categories", "Clippings", "Creations", "Daily", "Groups",
                   "Knowledge", "Meetings", "Notes", "People", "Topics", "Z_archive",
                   "Z_attachments")


def _shipped_text_files():
    for root in (REPO / "installers", REPO / "Templates" / "Scripts"):
        for p in root.rglob("*"):
            if p.is_file() and p.suffix in (".sh", ".ps1", ".psm1", ".py") \
                    and "tests" not in p.parts \
                    and not any(part.startswith(".venv") for part in p.parts):
                yield p


# ---------------------------------------------------------------------------
# #8 Open WebUI binding
# ---------------------------------------------------------------------------

def test_no_installer_publishes_open_webui_beyond_loopback() -> None:
    bare = re.compile(r"-p\s+['\"]?3000:8080")
    offenders = [f"{p.relative_to(REPO)}: {line.strip()}" for p in _shipped_text_files()
                 for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
                 if bare.search(line) and not line.lstrip().startswith("#")]
    assert not offenders, offenders


def test_windows_checks_an_existing_container_on_setup_and_update() -> None:
    common = (WIN / "common.ps1").read_text(encoding="utf-8")
    assert "-p 127.0.0.1:3000:8080" in common
    assert "function Repair-OpenWebUIBinding" in common
    assert "docker port open-webui 8080" in common
    setup = (WIN / "setup-rag.ps1").read_text(encoding="utf-8")
    assert "Repair-OpenWebUIBinding" in setup and "Start-OpenWebUIContainer" in setup
    assert "docker run" not in setup        # one run command, in common.ps1
    assert "Repair-OpenWebUIBinding" in (WIN / "update.ps1").read_text(encoding="utf-8")


def test_macos_checks_an_existing_container_too() -> None:
    comp = (REPO / "installers" / "components" / "50-llm-rag.sh").read_text(encoding="utf-8")
    assert "docker port open-webui 8080" in comp
    assert "grep -v '^127\\.0\\.0\\.1:'" in comp
    assert comp.count("-p 127.0.0.1:3000:8080") == 1


# ---------------------------------------------------------------------------
# #5 content folders
# ---------------------------------------------------------------------------

def _ignored(rel: str) -> bool:
    return subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", rel],
                          check=False).returncode == 0


@pytest.mark.parametrize("folder", CONTENT_FOLDERS)
def test_every_content_folder_ignores_a_note_but_keeps_its_structure(
        folder: str, allow_subprocess) -> None:
    assert _ignored(f"{folder}/A Real Person.md")
    assert _ignored(f"{folder}/sub/deeper/note.md")
    assert not _ignored(f"{folder}/.gitkeep")
    assert not _ignored(f"{folder}/sub/.gitkeep")


def test_the_content_folder_list_matches_the_vault(allow_subprocess) -> None:
    """A new top-level folder holding only a .gitkeep is a content folder and
    needs its ignore lines; this list is what the test above covers."""
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-files"], check=True,
                             capture_output=True, text=True).stdout.splitlines()
    roots = {Path(t).parts[0] for t in tracked if t.endswith("/.gitkeep") and "/" in t}
    assert roots - {"Templates"} <= set(CONTENT_FOLDERS), sorted(roots - set(CONTENT_FOLDERS))


def test_no_tracked_file_is_ignored(allow_subprocess) -> None:
    """The files meant to ship from content folders are re-included by name."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-ci", "--exclude-standard"],
                         check=True, capture_output=True, text=True).stdout.split()
    assert out == []


# ---------------------------------------------------------------------------
# #4 security suite interpreter and the integrity check
# ---------------------------------------------------------------------------

def test_the_suite_has_no_bare_python3_call() -> None:
    body = CHECKS.read_text(encoding="utf-8")
    after = body.split('CONTROL_PY="${SECURITY_CONTROL_PYTHON:-$CONTROL_PY}"', 1)[1]
    calls = [l.strip() for l in after.splitlines()
             if re.search(r'(?<![\w/."$])python3\b', l) and not l.strip().startswith("#")]
    assert calls == []
    assert "/usr/bin/python3 Templates/Scripts/integrity_monitor.py" not in after


needs_bash_suite = pytest.mark.skipif(
    platform.system() == "Windows" or not shutil.which("bash") or not shutil.which("git"),
    reason="runs security-checks.sh under bash")


@needs_bash_suite
def test_a_broken_control_interpreter_fails_the_integrity_check(tmp_path, allow_subprocess) -> None:
    """The check used to PASS here: a baseline that failed silently made the
    next run exit non-zero, which it read as 'drift detected'."""
    r = subprocess.run(["bash", str(CHECKS), "--dast", "--artifacts", str(tmp_path)],
                       cwd=REPO, capture_output=True, text=True, timeout=300,
                       env={**os.environ, "SECURITY_CONTROL_PYTHON": "/usr/bin/false"})
    assert "dast     FAIL    integrity check could not record its sandbox baseline (exit 1)" in r.stdout
    assert "integrity monitor fails closed on drift" not in r.stdout
    assert r.returncode != 0


@needs_bash_suite
def test_a_python_override_that_does_not_work_is_named(tmp_path, allow_subprocess) -> None:
    r = subprocess.run(["bash", str(CHECKS), "--fast", "--artifacts", str(tmp_path)],
                       cwd=REPO, capture_output=True, text=True, timeout=300,
                       env={**os.environ, "PYTHON": str(tmp_path / "no-such-python")})
    assert f"python:    NONE - PYTHON={tmp_path / 'no-such-python'} is not a working Python 3.10+" in r.stdout
    assert "RESULT: FAIL" in r.stdout


# ---------------------------------------------------------------------------
# #3 the unmatched-meeting digest runs on this interpreter
# ---------------------------------------------------------------------------

def test_the_digest_runs_on_the_running_interpreter(monkeypatch, tmp_path) -> None:
    """Every Windows pre-populate run ended 'Digest refresh failed:
    [WinError 2]': the digest was started with a hardcoded /usr/bin/python3."""
    import sys as _sys
    import meeting_prepopulate as mp
    (tmp_path / "meeting_group_backfill.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(mp, "SCRIPTS_DIR", tmp_path)
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "done\n", "")
    monkeypatch.setattr(mp.subprocess, "run", fake_run)
    mp.refresh_unmatched_digest(dry_run=False)
    assert seen["argv"][0] == _sys.executable
    assert seen["argv"][1:] == [str(tmp_path / "meeting_group_backfill.py"), "--digest", "--apply"]


# ---------------------------------------------------------------------------
# #6 the retired-plugin detector reads notes, not the template's docs
# ---------------------------------------------------------------------------

def _plugin_in_use():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "plugin_in_use", REPO / "installers" / "lib" / "plugin_in_use.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_template_docs_do_not_count_as_dataview_notes(tmp_path) -> None:
    """update.ps1 reported '2 note(s) still use Dataview queries' -- both were
    the template's own docs quoting a query, so Dataview could never go."""
    piu = _plugin_in_use()
    for rel in ("docs/Data-Classification.md", "installers/notes.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("an inline `= this.file.name` query\n", encoding="utf-8")
    assert piu.dataview_uses(tmp_path) == 0
    # A user's own folder of that name is a note, and still counts.
    (tmp_path / "Knowledge" / "docs").mkdir(parents=True)
    (tmp_path / "Knowledge" / "docs" / "Mine.md").write_text("`= this.file.name`\n", encoding="utf-8")
    assert piu.dataview_uses(tmp_path) == 1
