#!/usr/bin/env python3
"""Seed a demo user with example data so you can try TimePilot out of the box.

    python sample_data.py                              # user 'demo' / 'demo1234'
    python sample_data.py --username bob --password mypassword123
    python sample_data.py --force                       # reset the user's data if they exist

Run it with the same environment as the app (DATABASE_URL, FLASK_SECRET_KEY,
TIMEPILOT_MASTER_KEY), against the same database - e.g. inside the container:

    docker compose exec timepilot python sample_data.py

Dates are generated relative to today, so the board and Export tab always
look populated no matter when you run it.
"""
import argparse
import datetime
import sys

from app import app, load_state, save_state, JSON_DOMAINS
from extensions import db
from models import User


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
            "remindMeetings": False,
            "ntfyUrl": "https://ntfy.sh",
            "ntfyTopic": "",
            "ntfyIcon": "",
            "ntfyTasks": False,
            "quickTags": ["alarm_clock", "mailbox_with_mail", "warning", "rotating_light",
                          "calendar", "computer", "bulb", "white_check_mark",
                          "closed_lock_with_key", "wastebasket"],
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
        "reminders": [],
        "activeTimer": None,
        "calSeen": {},
    }


def main():
    ap = argparse.ArgumentParser(description="Seed a demo user with example data.")
    ap.add_argument("--username", default="demo")
    ap.add_argument("--password", default="demo1234")
    ap.add_argument("--force", action="store_true", help="reset the user's data if the account already exists")
    args = ap.parse_args()

    with app.app_context():
        user = User.query.filter_by(username=args.username.lower()).first()
        if user and not args.force:
            print(f"User '{args.username}' already exists. Re-run with --force to reset their data.")
            return 1
        if not user:
            user = User(username=args.username.lower())
            user.set_password(args.password)
            db.session.add(user)
            db.session.commit()
            print(f"Created user '{args.username}'.")
        else:
            print(f"Resetting data for existing user '{args.username}'.")

        save_state(user.id, build())

        print(f"\nLog in at /login\n  username: {args.username}\n  password: {args.password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
