#!/usr/bin/env python3
"""pin_plugins.py — (re)generate installers/plugin-pins.json.

The installers do NOT fetch "latest" plugin releases: whatever release is
current when a maintainer runs this tool gets pinned — repo, release tag
(or commit, for release-less plugins), download URL, and SHA256 per file —
and installs verify every byte against those hashes, failing closed. A
compromised or merely surprising upstream release cannot reach an adopter's
vault until a maintainer reruns this tool and commits the diff, which is
exactly the review moment the pin exists to create.

Usage (maintainer, with network):
    python3 installers/lib/pin_plugins.py            # refresh all pins
    python3 installers/lib/pin_plugins.py --check    # verify pins still fetch
    python3 installers/lib/pin_plugins.py --only ID[@TAG] [--only ...]
        # (re)pin just these plugins, at TAG or their latest release; every
        # other pin is left exactly as it is

Reads:  .obsidian/community-plugins.json  (the vault's enabled-plugin list)
Writes: installers/plugin-pins.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REGISTRY_URL = ("https://raw.githubusercontent.com/obsidianmd/"
                "obsidian-releases/master/community-plugins.json")
PINS_PATH = REPO_ROOT / "installers" / "plugin-pins.json"
FILES = ("manifest.json", "main.js", "styles.css")   # styles.css optional


def _gh_token() -> str:
    try:
        p = subprocess.run(["gh", "auth", "token"], capture_output=True,
                           text=True, timeout=10)
        return p.stdout.strip() if p.returncode == 0 else ""
    except Exception:
        return ""


def _get(url: str, token: str = "") -> bytes:
    req = urllib.request.Request(url)
    if token and url.startswith("https://api.github.com/"):
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _pin_one(pid: str, repo: str | None, token: str, tag: str = "") -> dict | None:
    """The pin for one plugin: at TAG if given, else its latest release, else
    the files at the current HEAD commit. None (with the reason on stderr)
    when it cannot be pinned."""
    if not repo:
        print(f"  {pid}: NOT IN REGISTRY — skipped", file=sys.stderr)
        return None
    if not tag:
        try:
            rel = json.loads(_get(
                f"https://api.github.com/repos/{repo}/releases/latest", token))
            tag = rel.get("tag_name", "")
        except urllib.error.HTTPError:
            pass
    if tag:
        base = f"https://github.com/{repo}/releases/download/{tag}"
        ref_desc = {"kind": "release", "ref": tag}
    else:
        # No releases: pin raw files at the current HEAD commit, so the
        # bytes are still immutable.
        head = json.loads(_get(
            f"https://api.github.com/repos/{repo}/commits/HEAD", token))
        sha = head["sha"]
        base = f"https://raw.githubusercontent.com/{repo}/{sha}"
        ref_desc = {"kind": "commit", "ref": sha}
    files = {}
    for fname in FILES:
        try:
            data = _get(f"{base}/{fname}", token)
        except urllib.error.HTTPError:
            if fname == "styles.css":
                continue          # optional
            print(f"  {pid}: missing required {fname} at {base} — "
                  f"skipped entirely", file=sys.stderr)
            return None
        files[fname] = {"url": f"{base}/{fname}",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "bytes": len(data)}
    print(f"  pinned {pid} @ {ref_desc['ref']} ({len(files)} files)")
    return {"id": pid, "repo": repo, **ref_desc, "files": files}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="re-download pinned URLs and verify hashes")
    ap.add_argument("--only", action="append", metavar="ID[@TAG]", default=[],
                    help="pin only this plugin (at TAG, or its latest release), "
                         "leaving every other pin untouched; repeatable")
    args = ap.parse_args()

    ids = json.loads(
        (REPO_ROOT / ".obsidian" / "community-plugins.json").read_text())
    token = _gh_token()

    if args.check:
        pins = json.loads(PINS_PATH.read_text())
        bad = 0
        for pin in pins:
            for fname, meta in pin["files"].items():
                data = _get(meta["url"], token)
                got = hashlib.sha256(data).hexdigest()
                status = "OK" if got == meta["sha256"] else "HASH MISMATCH"
                if got != meta["sha256"]:
                    bad += 1
                print(f"  {pin['id']}/{fname}: {status}")
        print(f"{'FAIL' if bad else 'PASS'}: {bad} mismatches")
        return 1 if bad else 0

    registry = {p["id"]: p["repo"]
                for p in json.loads(_get(REGISTRY_URL, token))}

    if args.only:
        wanted = dict((o.split("@", 1) + [""])[:2] for o in args.only)
        unknown = [pid for pid in wanted if pid not in ids]
        if unknown:
            print(f"not in .obsidian/community-plugins.json: {', '.join(unknown)}",
                  file=sys.stderr)
            return 2
        existing = {p["id"]: p for p in json.loads(PINS_PATH.read_text())}
        for pid, tag in wanted.items():
            pin = _pin_one(pid, registry.get(pid), token, tag)
            if pin is None:
                return 1
            existing[pid] = pin
        # Order follows the enabled-plugin list; ids no longer enabled drop.
        pins = [existing[pid] for pid in ids if pid in existing]
        PINS_PATH.write_text(json.dumps(pins, indent=2) + "\n")
        print(f"\nwrote {PINS_PATH} ({len(wanted)} re-pinned, "
              f"{len(pins) - len(wanted)} unchanged)")
        return 0

    pins = []
    for pid in ids:
        pin = _pin_one(pid, registry.get(pid), token)
        if pin is not None:
            pins.append(pin)

    PINS_PATH.write_text(json.dumps(pins, indent=2) + "\n")
    print(f"\nwrote {PINS_PATH} ({len(pins)}/{len(ids)} plugins pinned)")
    return 0 if len(pins) == len(ids) else 1


if __name__ == "__main__":
    raise SystemExit(main())
