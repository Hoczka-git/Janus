t_68a2a6c7: Add --help to janus and to janus commands (goal, task, workout)

Children integrated:
- t_fc033fdc: findings report (janus_cli_help_findings_t_fc033fdc.md) — gap analysis, recommended Option A (~50 LOC, no deps, no test breakage)
- t_59d0bba5: goal --help (PR #77, merged) — print_goal_help() + dispatcher interception
- t_1318b657: task --help (PR #78, merged) — print_task_help() + dispatcher interception
- t_51a4297a: workout --help (PR #81, merged) — print_workout_help() + dispatcher interception
- t_b49d80d6: integration verification — no-op, --help already on origin/master

All five children complete. --help support is live on origin/master for all three subcommands (goal, task, workout). This root branch fast-forwards to origin/master (06196f4) to satisfy the integration gate.

integration_required: true (gate checks for merged PR on this branch; branch pushed and PR opened by root worker)
