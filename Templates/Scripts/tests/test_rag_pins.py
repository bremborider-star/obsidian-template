"""installers/rag-pins.json and rag_pins.py: the local RAG stack's image and
models are pinned (2026-10-17). Until then Open WebUI came from its moving
`:main` development tag and Ollama models by name, so whatever upstream
published next is what installed, for the component that holds the whole
vault as a search collection."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PINS = REPO / "installers" / "rag-pins.json"
WIN = REPO / "Templates" / "Scripts" / "windows"
SHA = re.compile(r"^sha256:[0-9a-f]{64}$")

spec = importlib.util.spec_from_file_location("rag_pins", REPO / "installers" / "lib" / "rag_pins.py")
rp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rp)


def test_pins_name_a_release_by_digest_not_a_moving_tag() -> None:
    pins = json.loads(PINS.read_text())
    w = pins["open_webui"]
    assert w["image"] == "ghcr.io/open-webui/open-webui"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", w["tag"]), "a release tag, never main/latest"
    assert SHA.match(w["digest"])
    assert rp.image_ref(pins) == f"{w['image']}:{w['tag']}@{w['digest']}"
    assert pins["ollama_models"] and all(SHA.match(d) for d in pins["ollama_models"].values())


def _setup_ollama_models() -> list:
    src = (REPO / "Templates" / "Scripts" / "setup-ollama.sh").read_text()
    return re.findall(r'MODELS\+?=\("([^"]+)"\)', src)


def test_every_model_the_setup_scripts_pull_is_pinned() -> None:
    pinned = json.loads(PINS.read_text())["ollama_models"]
    mac = _setup_ollama_models()
    win = re.search(r"\[string\]\$Model = '([^']+)'", (WIN / "setup-rag.ps1").read_text()).group(1)
    assert len(mac) >= 1
    for model in mac + [win]:
        assert model in pinned, model


def test_no_shipped_script_pulls_open_webui_by_a_moving_tag() -> None:
    for p in (REPO / "installers" / "components" / "50-llm-rag.sh", WIN / "common.ps1",
              WIN / "setup-rag.ps1", REPO / "update.sh"):
        assert "open-webui:main" not in p.read_text(encoding="utf-8"), p.name
    comp = (REPO / "installers" / "components" / "50-llm-rag.sh").read_text()
    assert 'rag_pins.py" image)' in comp and '"$OPEN_WEBUI_IMAGE"' in comp
    common = (WIN / "common.ps1").read_text(encoding="utf-8")
    assert "rag-pins.json" in common and "function Test-OpenWebUIImagePin" in common
    assert "Test-OllamaModelPin $Model" in (WIN / "setup-rag.ps1").read_text(encoding="utf-8")
    assert "Test-OpenWebUIImagePin" in (WIN / "update.ps1").read_text(encoding="utf-8")
    assert "rag_pins.py\" image-digest" in (REPO / "update.sh").read_text()
    assert 'verify-models "${MODELS[@]}"' in (REPO / "Templates" / "Scripts" / "setup-ollama.sh").read_text()


def test_compare_reports_each_state() -> None:
    pins = {"ollama_models": {"a:1": "sha256:" + "a" * 64, "b:1": "sha256:" + "b" * 64,
                              "c:1": "sha256:" + "c" * 64}}
    installed = {"a:1": "sha256:" + "a" * 64, "b:1": "sha256:" + "f" * 64, "z:9": "sha256:" + "0" * 64}
    assert rp.compare(pins, installed, []) == [("a:1", "OK"), ("b:1", "CHANGED")]
    assert rp.compare(pins, installed, ["c:1", "z:9"]) == [("c:1", "NOT INSTALLED"), ("z:9", "UNPINNED")]


def test_verify_models_exits_1_only_when_a_model_changed(monkeypatch, capsys) -> None:
    pinned = json.loads(PINS.read_text())["ollama_models"]
    name = next(iter(pinned))
    monkeypatch.setattr(rp, "installed_digests", lambda host: {name: pinned[name]})
    assert rp.main(["verify-models"]) == 0
    monkeypatch.setattr(rp, "installed_digests", lambda host: {name: "sha256:" + "0" * 64})
    assert rp.main(["verify-models"]) == 1
    assert "CHANGED" in capsys.readouterr().out


def test_fetches_are_held_to_loopback_and_the_two_registries() -> None:
    import pytest
    with pytest.raises(ValueError):
        rp.installed_digests("http://192.168.1.5:11434")
    with pytest.raises(ValueError):
        rp.installed_digests("file:///etc/passwd")
    with pytest.raises(ValueError):
        rp._get("https://evil.example/v2/x", {})
    with pytest.raises(ValueError):
        rp._get("https://ghcr.io.evil.example/v2/x", {})
