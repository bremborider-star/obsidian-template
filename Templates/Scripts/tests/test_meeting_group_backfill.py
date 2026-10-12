"""
test_meeting_group_backfill.py — the reason an overlap proposal gives.

meeting_group_backfill.py borrows GroupsIndex.match so its proposals can never
drift from the pipeline. The matcher counts overlap in people, but the
backfill used to explain its proposals in addresses: a member on file at two
addresses counted twice, so a two-person meeting was reported as "3/3
attendees overlap" against a decision made on 2 of 2 people.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import meeting_group_backfill as bf
import meeting_prepopulate as mp


def _person(people: Path, stem: str, work: str = "", personal: str = "") -> None:
    (people / f"{stem}.md").write_text(
        "---\n"
        f"Email-Personal: {personal}\n"
        f"Email-Work: {work}\n"
        "---\n", encoding="utf-8")


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    people, groups, meetings = (tmp_path / d for d in ("People", "Groups", "Meetings"))
    for d in (people, groups, meetings):
        d.mkdir()
    monkeypatch.setattr(mp, "PEOPLE_DIR", people)
    monkeypatch.setattr(mp, "PEOPLE_UNRESOLVED_DIR", people / "_Unresolved")
    monkeypatch.setattr(mp, "GROUPS_DIR", groups)

    _person(people, "Delta, Di", work="di@corp.example", personal="di@home.example")
    _person(people, "Echo, Ed", work="ed@corp.example")
    (groups / "Pair.md").write_text(
        "---\ntitle: Pair\n---\n\n[[Delta, Di]]\n[[Echo, Ed]]\n", encoding="utf-8")
    (meetings / "2026-10-01 Untitled.md").write_text(
        "---\ncategories:\n  - \"[[Meetings]]\"\ntype: Group\n"
        "people:\n  - \"[[Delta, Di]]\"\n  - \"[[Echo, Ed]]\"\n---\n\nbody\n",
        encoding="utf-8")
    return tmp_path


def test_overlap_reason_counts_people_not_addresses(vault: Path) -> None:
    pi = mp.PeopleIndex()
    pi.load()
    gi = mp.GroupsIndex(pi)
    gi.load()
    rev = bf.stem_emails(mp, pi)
    note = bf.Note(vault / "Meetings" / "2026-10-01 Untitled.md", vault)

    props, unmatched = bf.build_proposals([note], gi, mp, pi, rev)

    assert not unmatched
    assert [(p.stem, p.confidence) for p in props] == [("Pair", "overlap")]
    assert props[0].why == "2/2 attendees overlap"
