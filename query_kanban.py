import sys, os, sqlite3

ROOT = "/home/dan11hermes/.hermes/hermes-agent"
sys.path.insert(0, ROOT)
os.chdir(ROOT)

DB = "/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db"

def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("=== tables ===")
    rows = cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    for row in rows:
        print(row["name"])

    print("\n=== status distribution ===")
    for row in cur.execute("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status"):
        print(dict(row))

    print("\n=== tasks with idempotency_key LIKE 'p_d550e150:roadmap:%' ===")
    rows = cur.execute(
        "SELECT id, title, status, idempotency_key, created_at, project_id, created_by FROM tasks "
        "WHERE idempotency_key LIKE 'p_d550e150:roadmap:%' ORDER BY created_at"
    ).fetchall()
    for row in rows:
        print(dict(row))

    # Check what tables hold comments / audit trail
    print("\n=== columns in comments (if exists) ===")
    try:
        cols = cur.execute("PRAGMA table_info(comments)").fetchall()
        for c in cols:
            print(dict(c))
    except Exception as e:
        print("comments table err:", e)

    print("\n=== task_events schema ===")
    cols = cur.execute("PRAGMA table_info(task_events)").fetchall()
    for c in cols:
        print(dict(c))

    print("\n=== audit comments (author=replenish) on seed t_22e47f8c ===")
    try:
        rows = cur.execute(
            "SELECT task_id, author, body, created_at FROM comments WHERE task_id = 't_22e47f8c' AND author='replenish' ORDER BY created_at"
        ).fetchall()
        for row in rows:
            print(dict(row))
    except Exception as e:
        print("comments query err:", e)

    print("\n=== task_events for t_22e47f8c ===")
    rows = cur.execute(
        "SELECT kind, payload, created_at FROM task_events WHERE task_id='t_22e47f8c' ORDER BY created_at"
    ).fetchall()
    for row in rows:
        print(dict(row))

    print("\n=== ALL replenish-ish events/comments across board (last 30) ===")
    # try event_log if present
    for tbl in ["event_log", "events", "task_events"]:
        try:
            c2 = cur.execute(f"SELECT kind, payload FROM {tbl} WHERE payload LIKE '%replenish%' ORDER BY created_at DESC LIMIT 30")
            cnt = 0
            for row in c2.fetchall():
                print(tbl, dict(row))
                cnt += 1
            if cnt == 0:
                print(tbl, "(no replenish matches in payload)")
        except Exception as e:
            print(tbl, "err:", e)

    print("\n=== task_events for t_8ac3ff10 and t_a37d1890 (replenished tasks) ===")
    for tid in ["t_8ac3ff10", "t_a37d1890"]:
        print(f"--- {tid} ---")
        rows = cur.execute(
            "SELECT kind, payload, created_at FROM task_events WHERE task_id=? ORDER BY created_at",
            (tid,)
        ).fetchall()
        for row in rows:
            print(dict(row))

    print("\n=== task_links involving the replenished tasks ===")
    try:
        rows = cur.execute(
            "SELECT parent_id, child_id FROM task_links WHERE parent_id IN ('t_8ac3ff10','t_a37d1890') OR child_id IN ('t_8ac3ff10','t_a37d1890')"
        ).fetchall()
        for row in rows:
            print(dict(row))
    except Exception as e:
        print("task_links err:", e)

    conn.close()

if __name__ == "__main__":
    main()
