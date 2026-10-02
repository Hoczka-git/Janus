#!/usr/bin/env python3
import sys, os
sys.path.insert(0, "src")
os.chdir("/home/dan11hermes/workspaces/janus")
from janus.services.weekly_review import create_weekly_review
review = create_weekly_review(trace_id="cron")
print("COMPLETED COUNT:", len(review.completed_tasks))
print("OPEN COUNT:", len(review.open_tasks))
print("GOALS:", len(review.goals))
for g in review.goals:
    print("GOAL:", g.goal.title)
    print("  progress:", g.progress)
    print("  health:", g.health_state)
    print("  days_since:", g.days_since_last_activity)
    print("  delta_14d:", g.progress_delta)
    print("  next:", g.suggested_next_step)
    print("  remediation:", g.remediation_action)
