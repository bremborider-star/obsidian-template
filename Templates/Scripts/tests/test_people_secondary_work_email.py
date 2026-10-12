"""
test_people_secondary_work_email.py — `Email-Work-2`, a second work address
on a People note.

People in a joint organisation often hold two work addresses (a university
address and a health-system one), and an invite can use either. With one
work field, the second address resolved to nobody: the attendee became a
new stub instead of the existing person, and group overlap missed them.

Email-Work-2 is read wherever the other two fields are matched on. Nothing
writes into it automatically: organic backfill reaches a note by a display
name the invite's sender chose, and a namesake's address is likelier than a
second address for the same person.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import backfill_people_email as bpe
import meeting_prepopulate as mp

NOW = "2026-10-12T08:00:00-04:00"


def _person(people: Path, stem: str, work: str = "", work2: str = "",
            personal: str = "") -> Path:
    p = people / f"{stem}.md"
    p.write_text(
        "---\n"
        f"Email-Personal: {personal}\n"
        f"Email-Work: {work}\n"
        f"Email-Work-2: {work2}\n"
        "Mobile Phone:\n"
        "---\n\nBody.\n", encoding="utf-8")
    return p


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    people, groups = tmp_path / "People", tmp_path / "Groups"
    people.mkdir()
    groups.mkdir()
    monkeypatch.setattr(mp, "PEOPLE_DIR", people)
    monkeypatch.setattr(mp, "PEOPLE_UNRESOLVED_DIR", people / "_Unresolved")
    monkeypatch.setattr(mp, "GROUPS_DIR", groups)
    return people, groups


def test_secondary_work_address_resolves_to_the_person(dirs) -> None:
    people, _ = dirs
    _person(people, "Doe, Jo", work="jo@uni.example", work2="jdoe@health.example")
    pi = mp.PeopleIndex()
    pi.load()
    assert pi.email_to_stem.get("jdoe@health.example") == "Doe, Jo"
    assert pi.email_to_stem.get("jo@uni.example") == "Doe, Jo"


def test_group_overlap_sees_an_attendee_at_their_secondary_address(dirs) -> None:
    people, groups = dirs
    _person(people, "Doe, Jo", work="jo@uni.example", work2="jdoe@health.example")
    _person(people, "Roe, Al", work="al@uni.example")
    (groups / "Duo.md").write_text("---\ntitle: Duo\n---\n\n[[Doe, Jo]]\n"
                                   "[[Roe, Al]]\n", encoding="utf-8")
    pi = mp.PeopleIndex()
    pi.load()
    gi = mp.GroupsIndex(pi)
    gi.load()
    assert gi.match("Sync", {"jdoe@health.example", "al@uni.example"}) == "Duo"


def test_an_empty_secondary_field_is_not_an_address(dirs) -> None:
    # An empty `Email-Work-2:` must not capture the next line as its value,
    # the bug the one-line field reader exists to prevent.
    people, _ = dirs
    _person(people, "Doe, Jo", work="jo@uni.example")
    pi = mp.PeopleIndex()
    pi.load()
    assert not any(k.startswith("mobile phone") for k in pi.email_to_stem)
    assert set(pi.email_to_stem) == {"jo@uni.example"}


def test_secondary_domain_vouches_for_organic_backfill(dirs) -> None:
    people, _ = dirs
    p = _person(people, "Doe, Jo", work2="jdoe@health.example")
    assert mp.organic_email_backfill("Doe, Jo", "jo@health.example",
                                     dry_run=False, is_personal=False)
    assert "Email-Work: jo@health.example" in p.read_text(encoding="utf-8")


def test_new_stubs_carry_the_secondary_field(dirs) -> None:
    text = mp.render_people_stub(
        "Doe, Jo", {"email": "jo@uni.example"}, "Jo Doe", "handoff", NOW)
    lines = text.splitlines()
    assert lines.index("Email-Work-2:") == lines.index("Email-Work: jo@uni.example") + 1


def test_backfill_tool_treats_a_secondary_only_note_as_populated() -> None:
    fm = ["Email-Personal:", "Email-Work:", "Email-Work-2: jdoe@health.example"]
    assert bpe.has_any_email(fm)
    assert not bpe.has_any_email(["Email-Personal:", "Email-Work:", "Email-Work-2:"])
