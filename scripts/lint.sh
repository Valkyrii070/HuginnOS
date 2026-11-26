#!/bin/sh
# The static checks, in one go: Python (ruff, rules in ruff.toml), shell scripts (shellcheck), the compositor (clippy).
# Each is skipped with a word if its tool isn't installed. Exit status 1 if anything was found.
set -u
cd "$(dirname "$0")/.." || exit 2
bad=0
if command -v ruff >/dev/null 2>&1; then
    echo "== Python (ruff)"
    ruff check --no-cache apps shell scripts config/overlay || bad=1
else
    echo "(ruff isn't installed: Python not checked)"
fi
if command -v shellcheck >/dev/null 2>&1; then
    echo "== Shell scripts (shellcheck)"
    grep -rlI -E '^#!.*\b(sh|bash)\b' config scripts | grep -v '\.py$' | xargs shellcheck -S warning || bad=1
else
    echo "(shellcheck isn't installed: shell scripts not checked)"
fi
if command -v cargo-clippy >/dev/null 2>&1 || cargo clippy --version >/dev/null 2>&1; then
    echo "== Compositor (clippy)"
    (cd compositor && cargo clippy --offline 2>&1 | tail -3)
else
    echo "(clippy isn't installed: the compositor not checked)"
fi
exit $bad
