#!/bin/bash
# Resolve merge conflicts in favor of our (HEAD) version for both conflicted files
# This keeps the current worktree's edits and discards the incoming origin changes.

cd /home/dan11hermes/workspaces/janus/.worktrees/t_4c456b46

resolve() {
    local file="$1"
    git checkout --ours "$file"
    # Re-read markers to confirm they're cleaned
    remaining=$(grep -c "^<<<<<<<\|^=======\|^>>>>>>>" "$file" 2>/dev/null || echo "0")
    echo "[$file] markers after --ours: $remaining"
}

resolve "docs/decisions/004-safe-sync-integrate-workflow.md"
resolve "docs/research/open_work_authoritative_list_2026-09-18.md"

# Final verification
echo "=== FINAL MARKER COUNTS ==="
for f in docs/decisions/004-safe-sync-integrate-workflow.md docs/research/open_work_authoritative_list_2026-09-18.md; do
    echo "$f: $(grep -c '^<<<<<<<\|^=======\|^>>>>>>>' "$f" 2>/dev/null || echo 0) markers"
done
