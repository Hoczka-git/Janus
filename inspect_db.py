import sqlite3, json

DB = '/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

tabs = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()]
print('TABLES:', tabs)

print('\n--- STATUS DISTRIBUTION ---')
for r in c.execute('SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status').fetchall():
    print('  ', dict(r))

print('\n--- replenishment-created tasks (idempotency_key like p_d550e150:roadmap:%) ---')
rows = c.execute(
    "SELECT id, title, status, idempotency_key, created_at, created_by, project_id FROM tasks "
    "WHERE idempotency_key LIKE 'p_d550e150:roadmap:%' ORDER BY created_at"
).fetchall()
for r in rows:
    print(dict(r))
print(f"(total: {len(rows)})")

print('\n--- task_comments author=replenish (all) ---')
rows = c.execute(
    "SELECT task_id, author, body, created_at FROM task_comments "
    "WHERE author='replenish' ORDER BY created_at"
).fetchall()
for r in rows:
    print(dict(r))
print(f"(total: {len(rows)})")

print('\n--- task_links involving t_22e47f8c, t_8ac3ff10, t_a37d1890 ---')
rows = c.execute(
    "SELECT parent_id, child_id FROM task_links "
    "WHERE parent_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890') "
    "   OR child_id IN ('t_22e47f8c','t_8ac3ff10','t_a37d1890')"
).fetchall()
for r in rows:
    print(dict(r))

print('\n--- task_events for t_22e47f8c ---')
rows = c.execute(
    "SELECT kind, payload, created_at FROM task_events WHERE task_id='t_22e47f8c' ORDER BY created_at"
).fetchall()
for r in rows:
    print(dict(r))

print('\n--- task_events for t_8ac3ff10, t_a37d1890 ---')
for tid in ['t_8ac3ff10', 't_a37d1890']:
    print(f'--- {tid} ---')
    rows = c.execute(
        "SELECT kind, payload, created_at FROM task_events WHERE task_id=? ORDER BY created_at",
        (tid,)
    ).fetchall()
    for r in rows:
        print(dict(r))

conn.close()
