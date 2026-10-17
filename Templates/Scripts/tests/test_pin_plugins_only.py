"""pin_plugins.py --only: re-pin one plugin and leave every other pin exactly as
it was. Without it, adding a plugin meant refreshing all of them to their
latest releases in the same commit. Offline: the network calls are stubbed."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load(tmp_path, monkeypatch, enabled, pins):
    root = tmp_path / "repo"
    (root / ".obsidian").mkdir(parents=True)
    (root / "installers").mkdir()
    (root / ".obsidian" / "community-plugins.json").write_text(json.dumps(enabled))
    (root / "installers" / "plugin-pins.json").write_text(json.dumps(pins))
    spec = importlib.util.spec_from_file_location(
        "pin_plugins_under_test", REPO / "installers" / "lib" / "pin_plugins.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "REPO_ROOT", root)
    monkeypatch.setattr(mod, "PINS_PATH", root / "installers" / "plugin-pins.json")
    monkeypatch.setattr(mod, "_gh_token", lambda: "")
    monkeypatch.setattr(mod, "_get", lambda url, token: json.dumps(
        [{"id": "a", "repo": "o/a"}, {"id": "b", "repo": "o/b"}, {"id": "new", "repo": "o/new"}]).encode())
    seen = []

    def fake_pin(pid, repo, token, tag=""):
        seen.append((pid, tag))
        return {"id": pid, "repo": repo, "kind": "release", "ref": tag or "latest", "files": {}}
    monkeypatch.setattr(mod, "_pin_one", fake_pin)
    return mod, root, seen


def test_only_adds_one_pin_and_leaves_the_rest(tmp_path, monkeypatch):
    old = [{"id": "a", "ref": "1.0", "files": {"x": 1}}, {"id": "b", "ref": "2.0", "files": {"y": 2}}]
    mod, root, seen = _load(tmp_path, monkeypatch, ["a", "b", "new"], old)
    monkeypatch.setattr(sys, "argv", ["pin_plugins.py", "--only", "new@3.1"])
    assert mod.main() == 0
    pins = json.loads((root / "installers" / "plugin-pins.json").read_text())
    assert [p["id"] for p in pins] == ["a", "b", "new"]
    assert pins[0] == old[0] and pins[1] == old[1]
    assert pins[2]["ref"] == "3.1" and seen == [("new", "3.1")]


def test_only_refuses_a_plugin_that_is_not_enabled(tmp_path, monkeypatch):
    mod, root, seen = _load(tmp_path, monkeypatch, ["a"], [{"id": "a", "files": {}}])
    monkeypatch.setattr(sys, "argv", ["pin_plugins.py", "--only", "new"])
    assert mod.main() == 2 and seen == []
