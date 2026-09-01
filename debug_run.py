"""Debug: re-run on_task_completed with full exception trace on the seed task."""
import os
import sys
import sqlite3
import traceback

os.environ.setdefault("HERMES_HOME", "/home/dan11hermes/.hermes")
sys.path.insert(0, "/home/dan11hermes/.hermes/hermes-agent")
sys.path.insert(0, "/home/dan11hermes/.hermes/hermes-agent/plugins")

BOARD_DB = "/home/dan11hermes/.hermes/kanban/boards/janus/kanban.db"
SEED = "t_22e47f8c"

def count_comments(conn, task_id):
    rows = conn.execute(
        "SELECT task_id, author, body, created_at FROM task_comments WHERE task_id=? ORDER BY created_at",
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]

conn = sqlite3.connect(BOARD_DB)
conn.row_factory = sqlite3.Row

print("Comments before:", len(count_comments(conn, SEED)))
for c in count_comments(conn, SEED):
    print("  ", dict(c))

from plugins.replenishment import on_task_completed, _run_replenishment

# Patch the logger to surface debug
import logging
logging.basicConfig(level=logging.DEBUG)
h = logging.StreamHandler(sys.stdout)
h.setLevel(logging.DEBUG)
logging.getLogger("plugins.replenishment").addHandler(h)
logging.getLogger().setLevel(logging.INFO)

print("\n--- Calling _run_replenishment directly (raises) ---")
try:
    _run_replenishment(SEED, board="janus")
    print("_run_replenishment returned WITHOUT raising")
except Exception:
    traceback.print_exc()

print("\nComments after:", len(count_comments(conn, SEED)))
for c in count_comments(conn, SEED):
    print("  ", dict(c))
conn.close()
