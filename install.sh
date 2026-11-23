#!/bin/sh
# grounded-lineage one-shot installer for macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/SleepingDawn/grounded-lineage/main/install.sh | sh
#   curl -LsSf .../install.sh | sh -s -- --readcube
#
# or, from a clone:  sh install.sh [--readcube] [--non-interactive] [--root DIR]
# Install folder: --root or $GL_ROOT (default: ~/.local/share/research-tools).
# Needs git. Installs uv (https://astral.sh/uv) if missing; uv provides Python 3.12.
# Safe to rerun: finished steps are checked and skipped. Rerun it when a session expires.
set -eu

ROOT="${GL_ROOT:-$HOME/.local/share/research-tools}"
ROOT_GIVEN=""
[ -n "${GL_ROOT:-}" ] && ROOT_GIVEN=1
prev=""
for arg in "$@"; do
    [ "$prev" = "--root" ] && ROOT="$arg" && ROOT_GIVEN=1
    prev="$arg"
done

command -v git >/dev/null 2>&1 || { echo "git is required; install it and run this again." >&2; exit 1; }

UV="$(command -v uv 2>/dev/null || true)"
[ -z "$UV" ] && [ -x "$HOME/.local/bin/uv" ] && UV="$HOME/.local/bin/uv"
if [ -z "$UV" ]; then
    echo "== Installing uv (https://astral.sh/uv/install.sh)"
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Installing uv needs curl or wget (and tar); install one, or install uv yourself." >&2
        exit 1
    fi
    UV="$HOME/.local/bin/uv"
    [ -x "$UV" ] || { echo "uv was installed but not found; open a new terminal and run this again." >&2; exit 1; }
fi

# Use the clone this script sits in (not when piped from curl), else clone into ROOT.
HERE=""
case "$0" in
    */install.sh|install.sh) HERE="$(cd "$(dirname "$0")" && pwd)" ;;
esac
if [ -n "$HERE" ] && [ -f "$HERE/pyproject.toml" ] && [ -f "$HERE/scripts/install_all.py" ]; then
    REPO="$HERE"
    [ -z "$ROOT_GIVEN" ] && ROOT="$(dirname "$REPO")"
else
    REPO="$ROOT/grounded-lineage"
    mkdir -p "$ROOT"
    if [ -d "$REPO/.git" ]; then
        git -C "$REPO" pull --ff-only
    elif [ -e "$REPO" ]; then
        echo "$REPO exists but is not a git clone; move it away and run this again." >&2
        exit 1
    else
        git clone https://github.com/SleepingDawn/grounded-lineage.git "$REPO"
    fi
fi

echo "== grounded-lineage in $REPO"
"$UV" python install 3.12
[ -x "$REPO/.venv/bin/python" ] || "$UV" venv --python 3.12 "$REPO/.venv"
(cd "$REPO" && "$UV" pip install --python "$REPO/.venv/bin/python" -e .)

# Prompts need the terminal even when this script arrives through a pipe.
if [ -t 0 ]; then
    exec "$REPO/.venv/bin/python" "$REPO/scripts/install_all.py" --root "$ROOT" --uv "$UV" "$@"
elif [ -r /dev/tty ] && (: </dev/tty) 2>/dev/null; then
    exec "$REPO/.venv/bin/python" "$REPO/scripts/install_all.py" --root "$ROOT" --uv "$UV" "$@" </dev/tty
else
    exec "$REPO/.venv/bin/python" "$REPO/scripts/install_all.py" --root "$ROOT" --uv "$UV" --non-interactive "$@"
fi
