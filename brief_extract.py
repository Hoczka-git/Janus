#!/usr/bin/env python3
from janus.services.weekly_review import create_weekly_review
r = create_weekly_review()
print("Goals:", len(r.goals))
print("Open:", len(r.open_tasks))
print("Completed:", len(r.completed_tasks))
for gr in r.goals:
    print(f"{gr.goal.title}: progress={gr.progress} health={gr.health_state} days={gr.days_since_last_activity} next={gr.suggested_next_step}")
