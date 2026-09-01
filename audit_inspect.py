"""Inspect the replenishment audit trail and idempotency state on the janus board."""
import sqlite3
import json

DB = "/home/dan11hermes/kanban/boards/janus/kanban.db"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("=== task_comments with author=replenish (all) ===")
rows = cur.execute(
    "SELECT task_id, author, body, created_at FROM task_comments "
    "WHERE author='replenish' ORDER BY created_at"
).fetchall()
for r in rows:
    d = dict(r)
    print(f"[{d['created_at']}] task={d['task_id']}")
    print(f"    body: {d['body']}")
print(f"\n(total replenish comments: {len(rows)})")

print("\n=== task_events: replenish-related on seed t_22e47f8c ===")
rows = cur.execute(
    "SELECT kind, payload, created_at FROM task_events "
    "WHERE task_id='t_22e47f8c' ORDER BY created_at"
).fetchall()
for r in rows:
    d = dict(r)
    print(f"[{d['created_at']}] {d['kind']}: {d['payload']}")

print("\n=== tasks created by replenishment (idempotency_key like p_d550e150:roadmap:%) ===")
rows = cur.execute(
    "SELECT id, title, status, idempotency_key, created_at, project_id FROM tasks "
    "WHERE idempotency_key LIKE 'p_d550e150:roadmap:%' ORDER BY created_at"
).fetchall()
for r in rows:
    print(dict(r))

print("\n=== task_links: parent -> child for seed + replenished tasks ===")
rows = cur.execute(
    "SELECT parent_id, child_id FROM task_links "
    "WHERE parent_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890') "
    "   OR child_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890')"
).fetchall()
for r in rows:
    print(dict(r))

conn.close()
