"""Inspect the live janus board DB to verify idempotency + audit claims."""
import sqlite3, json

DB = "/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

print("=== tables ===")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
    print("  ", r[0])

print("\n=== status distribution ===")
for r in c.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status").fetchall():
    print("  ", dict(r))

print("\n=== replenishment-created tasks (idempotency_key like p_d550e150:roadmap:%) ===")
rows = c.execute(
    "SELECT id, title, status, idempotency_key, created_at, project_id, created_by, assignee FROM tasks "
    "WHERE idempotency_key LIKE 'p_d550e150:roadmap:%' ORDER BY created_at"
).fetchall()
for r in rows:
    print("  ", dict(r))
print("  (total: %d)" % len(rows))

print("\n=== table names that could hold comments ===")
for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%comment%' OR name LIKE '%audit%' OR name='event_log' OR name='events')").fetchall():
    print("  ", r[0])

print("\n=== task_comments author=replenish (all) ===")
try:
    rows = c.execute(
        "SELECT task_id, author, body, created_at FROM task_comments WHERE author='replenish' ORDER BY created_at"
    ).fetchall()
    for r in rows:
        print("  ", dict(r))
    print("  (total: %d)" % len(rows))
except Exception as e:
    print("  ERR:", e)

print("\n=== task_events for seed t_22e47f8c ===")
rows = c.execute(
    "SELECT kind, payload, created_at FROM task_events WHERE task_id='t_22e47f8c' ORDER BY created_at"
).fetchall()
for r in rows:
    print("  ", dict(r))
print("  (total: %d)" % len(rows))

print("\n=== task_events for t_8ac3ff10 and t_a37d1890 ===")
for tid in ["t_8ac3ff10", "t_a37d1890", "t_5b6c2433"]:
    print("--- %s ---" % tid)
    rows = c.execute(
        "SELECT kind, payload, created_at FROM task_events WHERE task_id=? ORDER BY created_at",
        (tid,)
    ).fetchall()
    for r in rows:
        print("  ", dict(r))

print("\n=== task_links involving seed + replenished tasks ===")
rows = c.execute(
    "SELECT parent_id, child_id FROM task_links "
    "WHERE parent_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890','t_5b6c2433') "
    "   OR child_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890','t_5b6c2433')"
).fetchall()
for r in rows:
    print("  ", dict(r))

conn.close()
