#!/usr/bin/env bash
# verify-gitignore.sh — confirm secrets and local config are not tracked by Git
set -euo pipefail

echo "Checking Git tracking for sensitive files..."

tracked_files=$(git ls-files credentials.json token.json config/config.toml 2>/dev/null || true)

if [ -z "$tracked_files" ]; then
    echo "PASS: credentials.json, token.json, config/config.toml are not tracked."
    exit 0
else
    echo "FAIL: The following files are tracked by Git:"
    echo "$tracked_files"
    echo ""
    echo "Add them to .gitignore and remove from the index:"
    echo "  git rm --cached credentials.json token.json config/config.toml"
    exit 1
fi
