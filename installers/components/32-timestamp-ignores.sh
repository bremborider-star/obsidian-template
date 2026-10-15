#!/usr/bin/env bash
# 32-timestamp-ignores.sh - keep update-time-on-edit off the tracked files.
#
# The template ships the update-time-on-edit plugin enabled, and with no
# settings it stamps created:/updated: frontmatter into every Markdown file
# Obsidian sees change -- including CLAUDE.md, README.md and docs/ after a
# git pull, which leaves the clone with local changes the next update refuses
# over. This merges the tracked paths into the plugin's ignore list; see
# installers/lib/timestamp_ignores.py for why it is merged, not shipped.
#
# Runs after 30-plugins (the plugin folder must exist) and on every update.
# Idempotent. Obsidian must be closed, or the plugin writes its in-memory
# settings back over the merge.

set -euo pipefail

VAULT="$HOME/Obsidian"

if pgrep -x Obsidian >/dev/null 2>&1; then
    warn "  Obsidian is running; quit it and re-run: ./install.sh --only 32-timestamp-ignores"
    exit 0
fi

RESULT="$(python3 "$REPO_ROOT/installers/lib/timestamp_ignores.py" "$VAULT")"

case "$RESULT" in
    ADDED:*)
        ok "  update-time-on-edit now ignores the tracked files (${RESULT#ADDED:} path(s) added)"
        ;;
    ALREADY)
        ok "  update-time-on-edit already ignores the tracked files"
        ;;
    NO_PLUGIN)
        info "  update-time-on-edit not installed; nothing to do"
        ;;
    UNREADABLE)
        warn "  $VAULT/.obsidian/plugins/update-time-on-edit/data.json is not valid JSON; left as it is."
        warn "  Fix or delete it, then re-run: ./install.sh --only 32-timestamp-ignores"
        ;;
    *)
        warn "  timestamp_ignores.py returned an unexpected result: $RESULT"
        ;;
esac
