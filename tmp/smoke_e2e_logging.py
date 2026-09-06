"""End-to-end smoke: invoke the real CLI as a subprocess.

Exercises the real path: main() -> setup_logging() -> StreamHandler(stderr)
-> _StructuredFormatter -> emit() -> one JSON object per line.

We set sys.argv inside the child so no -c/-e flagging is involved, and we
point PYTHONPATH at the worktree src so `import janus` resolves.

Verifies the canonical schema (docs/design/observability_log_schema.md §3):
  * Every stderr line is valid JSON.
  * Each line has the required top-level fields: ts, level, service,
    component, event, message, data.
  * trace_id is consistent across all lines in one run.
  * stdout remains pure user output (no JSON bleed).
"""
import json
import os
import subprocess
import sys
import textwrap

WORKTREE = "/home/dan11hermes/workspaces/janus/.worktrees/t_33fbab9e"

# Stub the integrations so the CLI runs without real files/credentials.
bootstrap = textwrap.dedent("""
    import sys
    sys.argv = ["janus", "today", "--verbose"]
    import janus.today as _t
    _t.list_upcoming_events = lambda trace_id=None: []
    _t.load_tasks = lambda trace_id=None: []
    _t.load_goals = lambda trace_id=None: []
    from janus import main
    try:
        main()
    except SystemExit:
        pass
""")

env = dict(os.environ)
env["PYTHONPATH"] = os.path.join(WORKTREE, "src")

proc = subprocess.run(
    [sys.executable, "-c", bootstrap],
    capture_output=True, text=True, cwd=WORKTREE, env=env,
)

stderr = proc.stderr
lines = [l for l in stderr.splitlines() if l.strip()]
print("exit code:", proc.returncode)
print("stdout (user-facing) lines:", len(proc.stdout.splitlines()))
print("stderr (structured log) lines:", len(lines))

events = []
for l in lines:
    obj = json.loads(l)  # every stderr line must be valid JSON
    events.append(obj)

    # Verify canonical required fields.
    for field in ("ts", "level", "service", "component", "event", "message", "data"):
        assert field in obj, f"Line missing required field '{field}': {obj}"
    assert obj["level"] in ("debug", "info", "warning", "error", "critical")
    print(obj["event"], "| level=" + obj["level"], "| service=" + obj["service"],
          "| tid=" + str(obj.get("trace_id", ""))[:8])

names = {e["event"] for e in events}
assert "cli.command.invoked" in names, names
assert "cli.command.finished" in names, names
assert "briefing.generation.started" in names, names
assert "briefing.generation.finished" in names, names

# Correlation (trace_id) must be consistent across the run.
tid = next(e["trace_id"] for e in events if e["event"] == "cli.command.invoked")
assert all(e.get("trace_id") == tid for e in events if "trace_id" in e), \
    "trace_id not consistent across emitted events"

# stdout must remain pure user output (no JSON bleed).
assert "cli.command" not in proc.stdout

print("\nSMOKE OK — structured JSON logs emitted on stderr, stdout untouched, trace_id:", tid[:8])
