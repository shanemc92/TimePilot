#!/usr/bin/env python3
"""Generate example TimePilot data so you can demo the app out of the box.

    python sample_data.py            # writes to ./data (won't overwrite existing)
    python sample_data.py --force    # overwrite whatever's in ./data
    python sample_data.py --dir foo  # write to ./foo instead

Dates are generated relative to today, so the Today board and the Export tab
always look populated no matter when you run it. Delete the data folder any
time to start fresh.
"""
import argparse
import datetime
import json
import os
import sys

FILES = {
    "settings.json": ["settings"],
    "tasks.json": ["tasks"],
    "history.json": ["timelog"],
    "notes.json": ["notes"],
    "snippets.json": ["snippets"],
    "clipboard.json": ["pastes"],
    "runtime.json": ["activeTimer", "calSeen"],
}


def build():
    today = datetime.date.today()
    y = today - datetime.timedelta(days=1)
    d2 = today - datetime.timedelta(days=2)

    return {
        "settings": {
            "icsUrl": "",
            "theme": "dark",
            "font": "sans",
            "dayStart": "09:00",
            "dayEnd": "17:00",
            "rounding": 15,
            "remind": True,
            "remindLead": 5,
            "interrupts": ["Message", "Email", "Call", "Meeting"],
            "ignoreEvents": ["Private Appointment"],
            "categories": [
                {"k": "general", "label": "General", "color": "#5b9bd5"},
                {"k": "meetings", "label": "Meetings", "color": "#57b76a"},
                {"k": "admin", "label": "Admin", "color": "#a17ae0"},
            ],
        },
        "tasks": [
            {"id": "t1", "title": "Reply to project emails", "category": "admin", "column": "today", "est": 30, "slot": "09:30"},
            {"id": "t2", "title": "Draft weekly status update", "category": "general", "column": "today", "est": 45, "slot": None},
            {"id": "t3", "title": "Review pull requests", "category": "general", "column": "today", "est": 60, "slot": "14:00"},
            {"id": "t4", "title": "Prepare slides for team demo", "category": "meetings", "column": "week", "est": 90, "slot": None},
            {"id": "t5", "title": "Update project documentation", "category": "admin", "column": "week", "est": 60, "slot": None},
            {"id": "t6", "title": "Plan next sprint", "category": "meetings", "column": "nextweek", "est": 120, "slot": None},
            {"id": "t7", "title": "Quarterly goals review", "category": "general", "column": "nextmonth", "est": 60, "slot": None},
            {"id": "t8", "title": "Set up local dev environment", "category": "admin", "column": "done", "est": 45, "slot": None, "doneAt": today.isoformat()},
        ],
        "timelog": [
            {"id": "e1", "date": d2.isoformat(), "label": "Team standup", "taskId": None, "source": "cal", "category": "meetings", "start": "09:00", "end": "09:15", "minutes": 15},
            {"id": "e2", "date": d2.isoformat(), "label": "Feature development", "taskId": None, "category": "general", "start": "09:20", "end": "11:30", "minutes": 130},
            {"id": "e3", "date": d2.isoformat(), "label": "Email - client query", "taskId": None, "category": "admin", "start": "11:30", "end": "11:50", "minutes": 20},
            {"id": "e4", "date": d2.isoformat(), "label": "Code review", "taskId": None, "category": "general", "start": "13:00", "end": "14:30", "minutes": 90},
            {"id": "e5", "date": y.isoformat(), "label": "Team standup", "taskId": None, "source": "cal", "category": "meetings", "start": "09:00", "end": "09:15", "minutes": 15},
            {"id": "e6", "date": y.isoformat(), "label": "Sprint planning", "taskId": None, "source": "cal", "category": "meetings", "start": "10:00", "end": "11:00", "minutes": 60},
            {"id": "e7", "date": y.isoformat(), "label": "Documentation updates", "taskId": None, "category": "admin", "start": "11:15", "end": "12:30", "minutes": 75},
            {"id": "e8", "date": y.isoformat(), "label": "Bug fixing", "taskId": None, "category": "general", "start": "13:30", "end": "16:00", "minutes": 150},
            {"id": "e9", "date": today.isoformat(), "label": "Team standup", "taskId": None, "source": "cal", "category": "meetings", "start": "09:00", "end": "09:15", "minutes": 15},
            {"id": "e10", "date": today.isoformat(), "label": "Set up local dev environment", "taskId": "t8", "category": "admin", "start": "09:15", "end": "10:00", "minutes": 45},
            {"id": "e11", "date": today.isoformat(), "label": "Reply to project emails", "taskId": "t1", "category": "admin", "start": "10:00", "end": "10:25", "minutes": 25},
        ],
        "notes": [
            {"id": "n1", "title": "To follow up", "items": [
                {"id": "i1", "text": "Chase sign-off on the design doc"},
                {"id": "i2", "text": "Book meeting room for Thursday demo"},
            ]},
            {"id": "n2", "title": "Questions", "items": [
                {"id": "i3", "text": "Which environment should the release go to first?"},
                {"id": "i4", "text": "Confirm deadline for the quarterly report"},
            ]},
            {"id": "n3", "title": "Ideas", "items": [
                {"id": "i5", "text": "Automate the weekly status email"},
            ]},
        ],
        "snippets": [
            {"id": "s1", "title": "Git - undo last commit", "category": "Git", "desc": "Keep the changes staged", "body": "git reset --soft HEAD~1"},
            {"id": "s2", "title": "Find large files", "category": "Shell", "desc": "Top 10 by size in current dir", "body": "du -ah . | sort -rh | head -n 10"},
            {"id": "s3", "title": "Python venv", "category": "Python", "desc": "Create and activate", "body": "python -m venv .venv\nsource .venv/bin/activate   # Windows: .venv\\Scripts\\activate"},
            {"id": "s4", "title": "Pretty-print JSON", "category": "Shell", "desc": "", "body": "cat file.json | python -m json.tool"},
        ],
        "pastes": [
            {"id": "p1", "title": "Meeting follow-up", "category": "Email", "desc": "Standard reply after a call", "body": "Hi {name},\n\nThanks for the call today. To summarise what we agreed:\n\n- {point 1}\n- {point 2}\n\nI'll follow up on the above and circle back by {date}.\n\nBest regards"},
            {"id": "p2", "title": "Status update template", "category": "Reports", "desc": "Weekly format", "body": "## Weekly Update\n\n**Done this week**\n- \n\n**In progress**\n- \n\n**Blockers**\n- \n\n**Next week**\n- "},
            {"id": "p3", "title": "Out of office", "category": "Email", "desc": "", "body": "I'm currently out of office and will respond on my return on {date}. For anything urgent, please contact {colleague}."},
        ],
        "activeTimer": None,
        "calSeen": {},
    }


def main():
    ap = argparse.ArgumentParser(description="Generate example TimePilot data.")
    ap.add_argument("--dir", default="data", help="target folder (default: data)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files")
    args = ap.parse_args()

    target = os.path.join(os.path.dirname(os.path.abspath(__file__)), args.dir)
    existing = [fn for fn in FILES if os.path.exists(os.path.join(target, fn))]
    if existing and not args.force:
        print(f"'{args.dir}' already has data ({', '.join(existing)}).")
        print("Refusing to overwrite. Re-run with --force, or delete the folder first.")
        return 1

    data = build()
    os.makedirs(target, exist_ok=True)
    for fn, keys in FILES.items():
        payload = {k: data[k] for k in keys}
        with open(os.path.join(target, fn), "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False)

    print(f"Wrote example data to '{args.dir}/'. Start TimePilot to see it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
