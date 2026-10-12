"""
test_meeting_prepopulate_groups.py — GroupsIndex tier 3, the attendee-overlap
fallback that assigns a meeting to a group when its subject names none.

A wrong group is worse than none: the meeting lands in that group's Meetings
view and its prep pulls that group's history. Tier 3 had no tests, and two
ways of over-matching went unnoticed:

  - Coverage was divided by the members that had an email ON FILE. A member
    with a blank Email-Work dropped out of the denominator, so a 3-person
    group with one blank address matched any meeting the other two attended
    -- a board meeting whose guest list held two of three executives came out
    as that executives' group (2026-10-07). Coverage now counts only when
    most of the group is resolvable; a member with no email is unknown, not
    absent, so it neither inflates nor sinks the score.
  - Overlap was counted in addresses, not people, so one person on the invite
    at both of their addresses counted as two members present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import meeting_prepopulate as mp


def _person(people: Path, stem: str, work: str = "", personal: str = "") -> None:
    (people / f"{stem}.md").write_text(
        "---\n"
        f"Email-Personal: {personal}\n"
        f"Email-Work: {work}\n"
        "---\n", encoding="utf-8")


def _group(groups: Path, stem: str, *members: str) -> None:
    body = "\n".join(f"[[{m}]]" for m in members)
    (groups / f"{stem}.md").write_text(
        f"---\ntitle: {stem}\n---\n\n{body}\n\n## Meetings\n\n"
        "![[Meetings.base#Group]]\n", encoding="utf-8")


@pytest.fixture
def idx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    people, groups = tmp_path / "People", tmp_path / "Groups"
    people.mkdir()
    groups.mkdir()
    monkeypatch.setattr(mp, "PEOPLE_DIR", people)
    monkeypatch.setattr(mp, "PEOPLE_UNRESOLVED_DIR", people / "_Unresolved")
    monkeypatch.setattr(mp, "GROUPS_DIR", groups)

    _person(people, "Alpha, Ann", work="ann@corp.example")
    _person(people, "Bravo, Ben", work="ben@corp.example")
    _person(people, "Charlie, Cy")                      # no email on file
    _group(groups, "Exec Trio", "Alpha, Ann", "Bravo, Ben", "Charlie, Cy")

    _person(people, "Delta, Di", work="di@corp.example",
            personal="di@home.example")
    _person(people, "Echo, Ed", work="ed@corp.example")
    _group(groups, "Pair", "Delta, Di", "Echo, Ed")

    # Ten linked, eight with an email: mostly visible.
    board = [f"Member{i:02d}, M" for i in range(10)]
    for i, stem in enumerate(board):
        _person(people, stem, work=f"m{i:02d}@board.example" if i < 8 else "")
    _group(groups, "Big Board", *board)

    def build() -> mp.GroupsIndex:
        pi = mp.PeopleIndex()
        pi.load()
        gi = mp.GroupsIndex(pi)
        gi.load()
        return gi
    return build


GUESTS = {f"guest{i}@outside.example" for i in range(4)}


def test_a_group_that_is_mostly_unknown_cannot_match_on_coverage(idx) -> None:
    # Both resolvable members present among six attendees. Only 2 of 3
    # members are resolvable, so coverage (2/2) is not evidence and Jaccard
    # (2/6) is too low. Pre-fix this scored 2/2 coverage and matched.
    gi = idx()
    attendees = {"ann@corp.example", "ben@corp.example"} | GUESTS
    assert gi.match("Board of Trustees", attendees) is None


def test_one_person_at_two_addresses_is_one_attendee(idx) -> None:
    # Pre-fix the two addresses were two "members present": overlap 2,
    # Jaccard 2/3, matched Pair with Ed nowhere on the invite.
    gi = idx()
    assert gi.match("Catch-up", {"di@corp.example", "di@home.example"}) is None


def test_full_attendance_still_matches(idx) -> None:
    # The fix must not cost the matches tier 3 exists for.
    gi = idx()
    attendees = {"di@corp.example", "ed@corp.example", "guest0@outside.example"}
    assert gi.match("Catch-up", attendees) == "Pair"


def test_unknown_members_of_a_mostly_visible_group_do_not_block_it(idx) -> None:
    # Six of the eight resolvable members plus six outsiders: coverage 6/8.
    # Treating the two unknowns as absent (6/10) loses a real match -- the
    # first version of this fix did exactly that to a Microsoft CAB kickoff.
    gi = idx()
    attendees = {f"m{i:02d}@board.example" for i in range(6)} | {
        f"x{i}@outside.example" for i in range(6)}
    assert gi.match("FY27 kickoff", attendees) == "Big Board"


def test_attendee_address_case_does_not_matter(idx) -> None:
    gi = idx()
    assert gi.match("Catch-up", {"DI@corp.example", "Ed@Corp.Example"}) == "Pair"
