#!/usr/bin/env python3
"""TimePilot - local task/time/calendar cockpit.

Run:  pip install -r requirements.txt && python app.py
Then open http://localhost:5170
"""
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, date, timedelta

import requests
from flask import Flask, jsonify, request, send_from_directory

try:
    import icalendar
    import recurring_ical_events
    ICS_OK = True
except ImportError:
    ICS_OK = False


def app_base():
    """Writable location: next to the .exe when frozen, next to app.py otherwise."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def res_base():
    """Read-only bundled resources (static/): PyInstaller extraction dir when frozen."""
    return getattr(sys, "_MEIPASS", app_base())


BASE = app_base()
STATIC = os.path.join(res_base(), "static")
DATA_DIR = os.path.join(BASE, "data")
ICS_FILE = os.path.join(DATA_DIR, "calendar.ics")
LOCK = threading.Lock()
CACHE = {}  # url -> (fetched_at, ical bytes)
CACHE_TTL = 300

DEFAULT_STATE = {
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
    "tasks": [],
    "timelog": [],
    "notes": [
        {"id": "n1", "title": "To follow up", "items": []},
        {"id": "n2", "title": "Questions", "items": []},
    ],
    "calSeen": {},
    "snippets": [],
    "pastes": [],
    "activeTimer": None,
}

app = Flask(__name__, static_folder=STATIC)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB cap on any request body

# On-disk layout: one file per domain. Each maps to top-level key(s) of the
# combined state object the frontend expects. activeTimer/calSeen are transient
# bookkeeping, kept together in runtime.json.
FILES = {
    "settings.json": ["settings"],
    "tasks.json": ["tasks"],
    "history.json": ["timelog"],       # task history / export log
    "notes.json": ["notes"],
    "snippets.json": ["snippets"],
    "clipboard.json": ["pastes"],
    "runtime.json": ["activeTimer", "calSeen"],
}


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def load_state():
    state = {}
    for fn, keys in FILES.items():
        data = _read_json(os.path.join(DATA_DIR, fn), None)
        for k in keys:
            if data and k in data:
                state[k] = data[k]
            else:
                # fall back to a deep copy of the default for this key
                dv = DEFAULT_STATE.get(k)
                state[k] = json.loads(json.dumps(dv)) if dv is not None else (
                    [] if k in ("tasks", "timelog", "notes", "snippets", "pastes") else
                    {} if k == "calSeen" else None)
    return state


def save_state(state):
    for fn, keys in FILES.items():
        _write_json(os.path.join(DATA_DIR, fn), {k: state.get(k) for k in keys})


@app.route("/")
def index():
    return send_from_directory(STATIC, "index.html")


@app.route("/api/state", methods=["GET"])
def get_state():
    with LOCK:
        return jsonify(load_state())


@app.route("/api/state", methods=["PUT"])
def put_state():
    state = request.get_json(force=True, silent=True)
    if not isinstance(state, dict):
        return jsonify({"error": "Invalid state payload"}), 400
    # only persist known keys with expected container types; ignore anything else
    expected = {
        "settings": dict, "tasks": list, "timelog": list, "notes": list,
        "snippets": list, "pastes": list, "calSeen": dict,
    }
    clean = {}
    for k, typ in expected.items():
        if k in state and isinstance(state[k], typ):
            clean[k] = state[k]
    # activeTimer is either a dict or null
    if "activeTimer" in state and (state["activeTimer"] is None or isinstance(state["activeTimer"], dict)):
        clean["activeTimer"] = state["activeTimer"]
    with LOCK:
        # merge onto current so a partial PUT never wipes untouched domains
        cur = load_state()
        cur.update(clean)
        save_state(cur)
    return jsonify({"ok": True})


@app.route("/api/calendar/upload", methods=["POST"])
def cal_upload():
    data = request.get_data()
    if len(data) > 20 * 1024 * 1024:
        return jsonify({"error": "ICS file too large (max 20 MB)"}), 413
    if b"BEGIN:VCALENDAR" not in data[:4000]:
        return jsonify({"error": "That doesn't look like an ICS file"}), 400
    os.makedirs(os.path.dirname(ICS_FILE), exist_ok=True)
    with open(ICS_FILE, "wb") as f:
        f.write(data)
    CACHE.clear()
    return jsonify({"ok": True, "size": len(data)})


@app.route("/api/calendar")
def calendar():
    if not ICS_OK:
        return jsonify({"error": "Install icalendar + recurring-ical-events"}), 500
    with LOCK:
        url = load_state().get("settings", {}).get("icsUrl", "").strip()

    day = request.args.get("date") or date.today().isoformat()
    force = request.args.get("refresh") == "1"
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return jsonify({"error": "Bad date"}), 400

    raw, source, warn = None, None, None
    if url:
        now = time.time()
        cached = CACHE.get(url)
        if force or not cached or now - cached[0] > CACHE_TTL:
            try:
                r = requests.get(url, timeout=15)
                r.raise_for_status()
                CACHE[url] = (now, r.content)
            except Exception as e:
                warn = f"ICS URL fetch failed ({e})"
        if url in CACHE:
            raw, source = CACHE[url][1], "url"
    if raw is None and os.path.exists(ICS_FILE):
        with open(ICS_FILE, "rb") as f:
            raw = f.read()
        source = "file"
        mtime = date.fromtimestamp(os.path.getmtime(ICS_FILE)).isoformat()
        warn = ((warn + " - ") if warn else "") + f"using uploaded file from {mtime}"
    if raw is None:
        return jsonify({"error": (warn + " and no uploaded file. " if warn else "")
                        + "Set an ICS URL or upload a .ics file in Settings"}), 400

    try:
        cal = icalendar.Calendar.from_ical(raw)
        occurrences = recurring_ical_events.of(cal).between(d, d + timedelta(days=1))
    except Exception as e:
        return jsonify({"error": f"ICS parse failed: {e}"}), 500

    events = []
    for ev in occurrences:
        start = ev.get("DTSTART").dt
        end = ev.get("DTEND").dt if ev.get("DTEND") else start
        all_day = not isinstance(start, datetime)
        if isinstance(start, datetime) and start.tzinfo:
            start = start.astimezone()
        if isinstance(end, datetime) and end.tzinfo:
            end = end.astimezone()
        events.append({
            "title": str(ev.get("SUMMARY", "(no title)")),
            "location": str(ev.get("LOCATION", "")) if ev.get("LOCATION") else "",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "allDay": all_day,
        })
    events.sort(key=lambda e: e["start"])
    return jsonify({"date": day, "events": events, "source": source, "warn": warn})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5170, debug=False)
