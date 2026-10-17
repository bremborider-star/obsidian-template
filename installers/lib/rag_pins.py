#!/usr/bin/env python3
"""rag_pins.py — the local RAG stack's pinned image and models.

The local RAG stack holds the whole vault as a search collection, and until
2026-10-17 it installed whatever upstream published next: Open WebUI by its
`:main` tag (a moving development build) and Ollama models by name. This file
is the stack's equivalent of installers/plugin-pins.json: installers/rag-pins.json
names the Open WebUI release and its image digest, and the manifest digest of
every Ollama model the setup scripts pull.

- Open WebUI runs as `image:tag@digest`. Docker resolves the digest, not the
  tag, so a re-pushed tag or a swapped image is refused, not run.
- Ollama cannot pull by digest, so each model is checked after its pull:
  Ollama's own /api/tags reports the full manifest digest, which must equal
  the pin. A model that changed under its tag is reported, never deleted.

Moving a pin is a deliberate step, like re-pinning a plugin: run `repin`, read
the release notes, commit the diff. Open WebUI ships security fixes often, so
re-pin it on a schedule rather than leaving it to age.

Usage:
    rag_pins.py image                    # print the pinned image reference
    rag_pins.py image-digest             # print just its digest
    rag_pins.py verify-models [MODEL ...] [--host URL]
        # compare installed models with their pins (default: every pinned
        # model that is installed); exit 1 if any changed under its tag
    rag_pins.py repin [--webui TAG] [--model NAME:TAG ...]   (maintainer, network)

Stdlib only, Python 3.9-compatible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

PINS_PATH = Path(__file__).resolve().parent.parent / "rag-pins.json"
DEFAULT_HOST = "http://127.0.0.1:11434"
GHCR = "https://ghcr.io"
OLLAMA_REGISTRY = "https://registry.ollama.ai"
INDEX_TYPES = ("application/vnd.oci.image.index.v1+json, "
               "application/vnd.docker.distribution.manifest.list.v2+json")


def load(path: Path = PINS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def image_ref(pins: dict) -> str:
    w = pins["open_webui"]
    return f"{w['image']}:{w['tag']}@{w['digest']}"


LOOPBACK = ("127.0.0.1", "localhost", "::1")


def installed_digests(host: str = DEFAULT_HOST, timeout: float = 10) -> dict:
    """{name: full manifest digest} from Ollama's /api/tags. Loopback only:
    the RAG stack's Ollama never listens anywhere else."""
    parts = urlsplit(host)
    if parts.scheme not in ("http", "https") or parts.hostname not in LOOPBACK:
        raise ValueError(f"refusing a non-loopback Ollama host: {host}")
    with urllib.request.urlopen(f"{host.rstrip('/')}/api/tags", timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    out = {}
    for m in data.get("models", []):
        digest = m.get("digest") or ""
        if digest and not digest.startswith("sha256:"):
            digest = "sha256:" + digest
        out[m.get("name") or m.get("model")] = digest
    return out


def compare(pins: dict, installed: dict, wanted: list) -> list:
    """[(model, status)] with status OK, CHANGED, UNPINNED or NOT INSTALLED."""
    pinned = pins.get("ollama_models", {})
    names = wanted or [n for n in pinned if n in installed]
    rows = []
    for name in names:
        if name not in pinned:
            rows.append((name, "UNPINNED"))
        elif name not in installed:
            rows.append((name, "NOT INSTALLED"))
        elif installed[name] == pinned[name]:
            rows.append((name, "OK"))
        else:
            rows.append((name, "CHANGED"))
    return rows


def _get(url: str, headers: dict, timeout: float = 30) -> tuple[bytes, dict]:
    """GET from one of the two registries, and nowhere else."""
    if not url.startswith((GHCR + "/", OLLAMA_REGISTRY + "/")):
        raise ValueError(f"refusing a URL outside the pinned registries: {url}")
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), dict(r.headers)


def ghcr_digest(repo: str, tag: str) -> str:
    token = json.loads(_get(f"{GHCR}/token?scope=repository:{repo}:pull", {})[0])["token"]
    _, headers = _get(f"{GHCR}/v2/{repo}/manifests/{tag}",
                      {"Authorization": f"Bearer {token}", "Accept": INDEX_TYPES})
    digest = {k.lower(): v for k, v in headers.items()}.get("docker-content-digest", "")
    if not digest.startswith("sha256:"):
        raise SystemExit(f"no digest for {repo}:{tag}")
    return digest


def ollama_digest(model: str) -> str:
    name, _, tag = model.partition(":")
    body, _ = _get(f"{OLLAMA_REGISTRY}/v2/library/{name}/manifests/{tag or 'latest'}",
                   {"Accept": "application/vnd.docker.distribution.manifest.v2+json"})
    return "sha256:" + hashlib.sha256(body).hexdigest()


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("image")
    sub.add_parser("image-digest")
    v = sub.add_parser("verify-models")
    v.add_argument("models", nargs="*")
    v.add_argument("--host", default=DEFAULT_HOST)
    r = sub.add_parser("repin")
    r.add_argument("--webui", metavar="TAG")
    r.add_argument("--model", action="append", default=[], metavar="NAME:TAG")
    args = ap.parse_args(argv)
    pins = load()

    if args.cmd == "image":
        print(image_ref(pins))
        return 0
    if args.cmd == "image-digest":
        print(pins["open_webui"]["digest"])
        return 0
    if args.cmd == "verify-models":
        try:
            installed = installed_digests(args.host)
        except (OSError, ValueError) as exc:
            print(f"ollama not reachable at {args.host}: {exc}", file=sys.stderr)
            return 2
        rows = compare(pins, installed, args.models)
        for name, status in rows:
            print(f"{status:13} {name}")
        return 1 if any(s == "CHANGED" for _, s in rows) else 0

    # repin
    if args.webui:
        w = pins["open_webui"]
        repo = w["image"].split("/", 1)[1]
        w["tag"], w["digest"] = args.webui, ghcr_digest(repo, args.webui)
        print(f"open_webui -> {image_ref(pins)}")
    for model in args.model:
        pins.setdefault("ollama_models", {})[model] = ollama_digest(model)
        print(f"{model} -> {pins['ollama_models'][model]}")
    PINS_PATH.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
