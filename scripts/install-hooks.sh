#!/usr/bin/env bash
# Copy committed hooks from scripts/ into .git/hooks/ and mark them executable.
# Re-run any time the hooks change; it's idempotent.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
HOOKS_DIR="$ROOT/.git/hooks"
mkdir -p "$HOOKS_DIR"

for hook in pre-push; do
    src="$ROOT/scripts/$hook"
    dst="$HOOKS_DIR/$hook"
    if [[ ! -f "$src" ]]; then
        echo "[install-hooks] skip missing $src"
        continue
    fi
    cp "$src" "$dst"
    chmod +x "$dst"
    echo "[install-hooks] installed $hook"
done

echo "[install-hooks] done. Pytest will now run on every 'git push'."
