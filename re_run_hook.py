"""Empirically re-run the replenishment hook a second time on the live janus board.

Captures before/after state of:
  - replenishment-created task rows (idempotency_key like p_d550e150:roadmap:%)
  - audit comments (author=replenish) on the seed t_22e47f8c
  - status distribution

Then re-invokes plugins.replenishment.on_task_completed on the already-completed
seed t_22e47f8c with the SAME configuration the first run used (verified from
projects.db: kind=file, path=docs/roadmap.md, format=markdown,
target_column=triage, max_generated_tasks=1).

Idempotency PASS == no new task rows AND no new audit comment that records a
non-zero pull. (Per the code, an audit comment IS appended unconditionally after
the source loop; if the cursor has no unchecked items the markdown handler
returns 0, but the comment is still written — so we verify the comment body
reports "pulled 0 task(s)" rather than "pulled 1".)
"""
import os, sys, sqlite3, json

os.environ.setdefault("HERMES_HOME", "/home/dan11hermes/.hermes")
ROOT = "/home/dan11hermes/.hermes/hermes-agent"
sys.path.insert(0, ROOT)
sys.path.insert(0, ROOT + "/plugins")

DB = "/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db"
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


def snapshot(conn):
    repl = [dict(r) for r in conn.execute(SQL_REPL).fetchall()]
    dist = {r["status"]: r["n"] for r in conn.execute(SQL_DIST).fetchall()}
    comments = [dict(r) for r in conn.execute(SQL_COMMENTS, (SEED,)).fetchall()]
    return repl, dist, comments


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    before_repl, before_dist, before_comments = snapshot(conn)
    conn.close()

    print("=== BEFORE second on_task_completed call ===")
    print("Replenishment tasks:", len(before_repl))
    for t in before_repl:
        print("  ", dict(t))
    print("Audit comments on seed:", len(before_comments))
    for c in before_comments:
        print("  ", dict(c))
    print("Status dist:", before_dist)

    print("\n=== Invoking on_task_completed(%s) (second run, same config) ===" % SEED)
    from plugins.replenishment import on_task_completed
    on_task_completed(
        SEED, board="janus", profile_name="implementer", run_id=None, summary=None
    )

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    after_repl, after_dist, after_comments = snapshot(conn)
    conn.close()

    print("\n=== AFTER second on_task_completed call ===")
    print("Replenishment tasks:", len(after_repl))
    for t in after_repl:
        print("  ", dict(t))
    print("Audit comments on seed:", len(after_comments))
    for c in after_comments:
        print("  ", dict(c))
    print("Status dist:", after_dist)

    new_ids = set(t["id"] for t in after_repl) - set(t["id"] for t in before_repl)
    new_keys = set(t["idempotency_key"] for t in after_repl) - set(
        t["idempotency_key"] for t in before_repl
    )
    new_comments = [c for c in after_comments if c["created_at"] > before_comments[-1]["created_at"]] if before_comments else after_comments
    print("\n=== Idempotency check ===")
    print("New task ids:", sorted(new_ids))
    print("New idempotency keys:", sorted(new_keys))
    print("New audit comments:", len(new_comments))
    for c in new_comments:
        print("  ", c["body"])
    if new_ids:
        print("FAIL: additional tasks generated -> NOT idempotent")
    else:
        print("PASS: no additional tasks generated -> idempotent")

    # The audit comment is written unconditionally (code lines 199-207).
    # Verify any NEW comment reports pulled == 0 (no side effect).
    if new_comments:
        bodies = " | ".join(c["body"] for c in new_comments)
        print("New comment body text:", bodies)
        print("PASS: audit comment records 0 pulls (cursor exhausted)" if "pulled 0" in bodies else "NOTE: new comment does not say 'pulled 0'")


if __name__ == "__main__":
    main()
