"""Second replenishment run against the real JANUS board.

Captures the set of replenishment-created task ids BEFORE invoking the hook
a second time on the completed seed task t_22e47f8c, then re-invokes
``on_task_completed`` (the registered kanban_task_completed callback) and
compares. Also records the audit comments before/after for the audit-trail
inspection required by the task.
"""
import os
import sys
import sqlite3
import json

os.environ.setdefault("HERMES_HOME", "/home/dan11hermes/.hermes")

sys.path.insert(0, "/home/dan11hermes/.hermes/hermes-agent")
# Plugin package lives under plugins/<name>; add plugins root so
# ``import plugins.replenishment`` resolves.
sys.path.insert(0, "/home/dan11hermes/.hermes/hermes-agent/plugins")

BOARD = "janus"
BOARD_DB = "/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db"
SEED = "t_22e47f8c"

SQL_REPL = (
    "SELECT id, idempotency_key, created_at FROM tasks "
    "WHERE idempotency_key LIKE 'p_d550e150:roadmap:%' ORDER BY created_at"
)
SQL_DIST = "SELECT status, COUNT(*) AS n FROM tasks GROUP BY status ORDER BY status"
SQL_COMMENTS = (
    "SELECT task_id, author, body, created_at FROM task_comments "
    "WHERE task_id=? ORDER BY created_at"
)


def count_repl_tasks(conn):
    rows = conn.execute(SQL_REPL).fetchall()
    return [dict(r) for r in rows]


def audit_comments(conn, task_id):
    rows = conn.execute(SQL_COMMENTS, (task_id,)).fetchall()
    return [dict(r) for r in rows]


def status_dist(conn):
    rows = conn.execute(SQL_DIST).fetchall()
    return {r["status"]: r["n"] for r in rows}


def main():
    conn = sqlite3.connect(BOARD_DB)
    conn.row_factory = sqlite3.Row

    print("=== BEFORE second replenishment run ===")
    before = count_repl_tasks(conn)
    print("Replenishment-created tasks: %d" % len(before))
    for t in before:
        print("  %s key=%s created_at=%s" % (t["id"], t["idempotency_key"], t["created_at"]))

    before_status = status_dist(conn)
    print("Status distribution: %s" % before_status)

    before_comments = audit_comments(conn, SEED)
    print("Audit comments on seed %s: %d" % (SEED, len(before_comments)))
    for c in before_comments:
        print("  [%s] %s: %s" % (c["created_at"], c["author"], c["body"]))

    print("\n=== Invoking on_task_completed on seed %s (second run) ===" % SEED)
    # Import AFTER setting up sys.path + env so the plugin uses the right home.
    from plugins.replenishment import on_task_completed  # noqa: E402

    on_task_completed(
        SEED, board=BOARD, profile_name="implementer", run_id=None, summary=None
    )

    print("\n=== AFTER second replenishment run ===")
    after = count_repl_tasks(conn)
    print("Replenishment-created tasks: %d" % len(after))
    for t in after:
        print("  %s key=%s created_at=%s" % (t["id"], t["idempotency_key"], t["created_at"]))

    after_status = status_dist(conn)
    print("Status distribution: %s" % after_status)

    after_comments = audit_comments(conn, SEED)
    print("Audit comments on seed %s: %d" % (SEED, len(after_comments)))
    for c in after_comments:
        print("  [%s] %s: %s" % (c["created_at"], c["author"], c["body"]))

    new_ids = set(t["id"] for t in after) - set(t["id"] for t in before)
    new_keys = set(t["idempotency_key"] for t in after) - set(
        t["idempotency_key"] for t in before
    )
    print("\n=== Idempotency check ===")
    print("New task ids after second run: %s" % sorted(new_ids))
    print("New idempotency keys after second run: %s" % sorted(new_keys))
    if new_ids:
        print("FAIL: additional tasks were generated -> NOT idempotent")
    else:
        print("PASS: no additional tasks generated -> idempotent")

    conn.close()


if __name__ == "__main__":
    main()
