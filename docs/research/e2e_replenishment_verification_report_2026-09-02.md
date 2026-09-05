# E2E Replenishment Verification Report

**Seed Task:** `t_03cc0750` — Controlled E2E test seed for replenishment validation
**Overall:** FAIL
**Generated:** 2026-09-02T08:59:02.002874+00:00

## Checks

### status_distribution — PASS

Status distribution retrieved successfully

### replenishment_tasks — FAIL

0 replenishment task(s) parented on seed t_03cc0750 (0/0 unique idempotency keys). All [plan]-prefixed: True. All parented on seed t_03cc0750: True.

### idempotency_keys — PASS

No duplicate non-archived tasks per idempotency key

### audit_trail — FAIL

0 audit comment(s) found on seed t_03cc0750, all well-formed: True

### task_events — FAIL

Seed t_03cc0750 has 65 events including completion: False. Event kinds: ['created', 'completion_blocked_repo_unsynced', 'claimed', 'spawned', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'timed_out', 'claimed', 'spawned', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'protocol_violation', 'claimed', 'spawned', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'heartbeat', 'protocol_violation', 'claimed', 'spawned', 'heartbeat', 'heartbeat']

| Field | Value |
|-------|-------|
| kind | created |
| created_at | 1788332679 |
| kind | completion_blocked_repo_unsynced |
| created_at | 1788332680 |
| kind | claimed |
| created_at | 1788336464 |
| kind | spawned |
| created_at | 1788336464 |
| kind | heartbeat |
| created_at | 1788336466 |
| kind | heartbeat |
| created_at | 1788336526 |
| kind | heartbeat |
| created_at | 1788336557 |
| kind | heartbeat |
| created_at | 1788336587 |

### task_links — FAIL

0 task(s) parented on seed t_03cc0750

### replenishment_plugin_tests — PASS

Plugin tests: passed=True, 23 passed in 2.56s

### janus_test_suite — PASS

JANUS test suite: passed=True, 601 passed in 9.78s

## Conclusion

One or more checks failed — see details above.
