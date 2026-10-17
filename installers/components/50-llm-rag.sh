#!/usr/bin/env bash
# 50-llm-rag.sh - Ollama + 8B model + Open WebUI (Docker) + RAG sync agent.
#
# Reuses Templates/Scripts/setup-ollama.sh for Ollama + 8B model (passes
# --minimal so it skips the 14B and 70B downloads). Then installs Docker
# Desktop if missing, pulls Open WebUI, and configures it to talk to the
# local Ollama on port 11434. Finally wires the obsidian-rag-sync.py
# LaunchAgent to push the vault into a Knowledge collection nightly.
#
# After this component finishes, the user must (one-time, manual):
#   1. Open Open WebUI in a browser at http://localhost:3000
#   2. Create an admin account
#   3. Create a Knowledge collection named "Obsidian"
#   4. Generate an API key in user settings
#   5. Re-run: install.sh --only 20-secrets
#      to populate OPEN_WEBUI_API_KEY and OBSIDIAN_COLLECTION_ID

set -euo pipefail
source "$REPO_ROOT/installers/lib/plist.sh"

VAULT="$HOME/Obsidian"

# ---- 1. Ollama + 8B model --------------------------------------------------
info "Running setup-ollama.sh --minimal..."
bash "$VAULT/Templates/Scripts/setup-ollama.sh" --minimal

# ---- 2. Docker Desktop -----------------------------------------------------
info "Docker Desktop..."
if has_cmd docker && docker info >/dev/null 2>&1; then
    ok "  docker running"
else
    if ! has_cmd docker; then
        info "  installing Docker Desktop via Homebrew cask..."
        brew_install_if_missing docker cask docker
        warn "  Docker Desktop installed. Launch it once (Applications -> Docker) so it can request privileged-helper permissions, then re-run this component."
        warn "  If brew complained about leftover binaries in /usr/local/bin (docker, hub-tool, kubectl.docker, docker-credential-*), 'sudo rm' them and re-run."
        return 0 2>/dev/null || exit 0
    fi
    warn "  docker daemon not running; start Docker Desktop, then re-run this component"
    return 0 2>/dev/null || exit 0
fi

# ---- 3. Open WebUI ---------------------------------------------------------
info "Open WebUI container..."
# 127.0.0.1 binding is load-bearing: this UI can hold the entire vault as a
# RAG collection, and a bare -p 3000:8080 publishes it to every device on the
# LAN (Docker bypasses the macOS application firewall). An existing container
# keeps whatever binding it was created with, so it is checked, not trusted,
# and recreated on the same volume if it is published anywhere else.
# The image is pinned by digest (installers/rag-pins.json, rag_pins.py): Docker
# resolves the digest, so a re-pushed tag or a swapped image is refused.
OPEN_WEBUI_IMAGE="$(python3 "$REPO_ROOT/installers/lib/rag_pins.py" image)"
OPEN_WEBUI_DIGEST="$(python3 "$REPO_ROOT/installers/lib/rag_pins.py" image-digest)"
start_open_webui() {
    docker run -d --restart=always \
        -p 127.0.0.1:3000:8080 \
        -v open-webui:/app/backend/data \
        --add-host=host.docker.internal:host-gateway \
        -e 'OLLAMA_BASE_URL=http://host.docker.internal:11434' \
        --name open-webui \
        "$OPEN_WEBUI_IMAGE"
}
# An existing container keeps the image it was created from. Report, do not
# replace: moving Open WebUI to another release migrates its database, which
# is the operator's call, and the volume keeps the account and knowledge.
report_open_webui_pin() {
    local image_id repo_digests
    image_id="$(docker inspect open-webui --format '{{.Image}}' 2>/dev/null || true)"
    repo_digests="$(docker image inspect "$image_id" --format '{{join .RepoDigests " "}}' 2>/dev/null || true)"
    if [[ "$repo_digests" == *"@$OPEN_WEBUI_DIGEST"* ]]; then
        ok "  open-webui runs the pinned image"
    else
        warn "  open-webui runs an image other than the pinned one ($OPEN_WEBUI_IMAGE)."
        warn "  To move to the pin, on the same volume (account and knowledge kept):"
        warn "    docker pull '$OPEN_WEBUI_IMAGE' && docker rm -f open-webui && ./install.sh --only 50-llm-rag"
    fi
}
if docker ps -a --format '{{.Names}}' | grep -q '^open-webui$'; then
    if ! docker ps --format '{{.Names}}' | grep -q '^open-webui$'; then
        docker start open-webui >/dev/null && sleep 2
    fi
    exposed="$(docker port open-webui 8080 2>/dev/null | grep -v '^127\.0\.0\.1:' || true)"
    if [[ -n "$exposed" ]]; then
        warn "  open-webui is published beyond this Mac ($(echo "$exposed" | tr '\n' ' ')); recreating it on the same volume, bound to 127.0.0.1"
        docker rm -f open-webui >/dev/null
        start_open_webui
        ok "  open-webui recreated; your account and knowledge are kept"
    else
        ok "  open-webui container running, bound to 127.0.0.1"
    fi
    report_open_webui_pin
else
    info "  pulling and starting open-webui..."
    start_open_webui
    ok "  open-webui container started; web UI at http://localhost:3000"
fi

# ---- 4. RAG sync LaunchAgent ----------------------------------------------
info "Installing LaunchAgent com.obsidian-rag-sync..."
install_plist_and_load Templates/Scripts/com.obsidian-rag-sync.plist com.obsidian-rag-sync

ok "llm-rag component complete"
info "  Next (one-time manual): open http://localhost:3000, create admin,"
info "  create 'Obsidian' Knowledge collection, generate API key, then run:"
info "    ./install.sh --only 20-secrets --force"
info "  to populate OPEN_WEBUI_API_KEY and OBSIDIAN_COLLECTION_ID in ~/dev/secrets/.env"
