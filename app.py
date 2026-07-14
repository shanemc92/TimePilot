#!/usr/bin/env python3
"""TimePilot server - multi-user, Postgres-backed, encrypted at rest.

Run (dev):   flask --app app run --debug
Run (prod):  gunicorn -w 4 -b 0.0.0.0:5170 'app:app'
"""
import json
import ipaddress
import logging
import os
import socket
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_login import login_required, current_user

try:
    import icalendar
    import recurring_ical_events
    ICS_OK = True
except ImportError:
    ICS_OK = False

from extensions import db, login_manager, limiter, csrf
from models import User, UserData
from crypto import Encryptor
import auth as auth_bp_module

logger = logging.getLogger("timepilot")

BASE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(BASE, "static")

# Domains mirror the pre-multiuser file layout - each is one encrypted row
# per user. JSON_DOMAINS values list which top-level state keys live in that
# domain; calendar_ics is stored separately as raw (encrypted) bytes.
JSON_DOMAINS = {
    "settings": ["settings"],
    "tasks": ["tasks"],
    "history": ["timelog"],
    "notes": ["notes"],
    "snippets": ["snippets"],
    "clipboard": ["pastes"],
    "runtime": ["activeTimer", "calSeen"],
}
CALENDAR_DOMAIN = "calendar_ics"

DEFAULT_SETTINGS = {
    "icsUrl": "",
    "theme": "dark",
    "font": "sans",
    "dayStart": "09:00",
    "dayEnd": "17:00",
    "viewStart": "",
    "viewEnd": "",
    "lunchStart": "",
    "lunchEnd": "",
    "rounding": 15,
    "remind": True,
    "remindLead": 5,
    "browserNotifications": False,
    "interrupts": ["Message", "Email", "Call", "Meeting"],
    "ignoreEvents": ["Private Appointment"],
    "categories": [
        {"k": "general", "label": "General", "color": "#5b9bd5"},
        {"k": "meetings", "label": "Meetings", "color": "#57b76a"},
        {"k": "admin", "label": "Admin", "color": "#a17ae0"},
    ],
}
KEY_DEFAULTS = {
    "settings": DEFAULT_SETTINGS,
    "tasks": [],
    "timelog": [],
    "notes": [
        {"id": "n1", "title": "To follow up", "items": []},
        {"id": "n2", "title": "Questions", "items": []},
    ],
    "snippets": [],
    "pastes": [],
    "activeTimer": None,
    "calSeen": {},
}

CACHE = {}  # ICS URL -> (fetched_at, bytes) - in-process HTTP cache, not sensitive
CACHE_TTL = 300

_encryptor = None


def get_encryptor():
    global _encryptor
    if _encryptor is None:
        _encryptor = Encryptor(os.environ.get("TIMEPILOT_MASTER_KEY", ""))
    return _encryptor


def get_domain_json(user_id, domain):
    row = UserData.query.filter_by(user_id=user_id, domain=domain).first()
    if not row:
        return None
    try:
        return json.loads(get_encryptor().decrypt(row.encrypted_blob))
    except Exception:
        return None


def set_domain_json(user_id, domain, payload):
    blob = get_encryptor().encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    row = UserData.query.filter_by(user_id=user_id, domain=domain).first()
    if row:
        row.encrypted_blob = blob
    else:
        db.session.add(UserData(user_id=user_id, domain=domain, encrypted_blob=blob))
    db.session.commit()


def load_state(user_id):
    state = {}
    for domain, keys in JSON_DOMAINS.items():
        data = get_domain_json(user_id, domain) or {}
        for k in keys:
            state[k] = data[k] if k in data else _default_for(k)
    return state


def save_state(user_id, state):
    for domain, keys in JSON_DOMAINS.items():
        set_domain_json(user_id, domain, {k: state.get(k) for k in keys})


def get_user_ics_bytes(user_id):
    row = UserData.query.filter_by(user_id=user_id, domain=CALENDAR_DOMAIN).first()
    if not row:
        return None
    try:
        return get_encryptor().decrypt(row.encrypted_blob)
    except Exception:
        return None


def set_user_ics_bytes(user_id, data: bytes):
    blob = get_encryptor().encrypt(data)
    row = UserData.query.filter_by(user_id=user_id, domain=CALENDAR_DOMAIN).first()
    if row:
        row.encrypted_blob = blob
    else:
        db.session.add(UserData(user_id=user_id, domain=CALENDAR_DOMAIN, encrypted_blob=blob))
    db.session.commit()


def _check_external_url(url):
    """Returns (ok, reason). Rejects URLs that resolve to a private/internal/
    link-local address, or that fail to resolve at all.

    icsUrl is user-supplied and the SERVER fetches it - without this check,
    any signed-up user could point it at the internal Docker network (e.g.
    the postgres service, which is deliberately unreachable from outside
    for exactly this reason) or a cloud metadata endpoint
    (169.254.169.254) and use the app as a proxy to probe it.

    This is the up-front check that produces a friendly error message. The
    same validation is repeated at connection time by _ValidatingHTTPAdapter
    below (including on every redirect hop), which narrows the DNS-rebinding
    window - a hostname resolving to a public IP here but a private one at
    connect time - from "the whole request setup" to milliseconds.

    Returning a specific reason (rather than a bare bool) matters: a DNS
    resolution failure and "this really is a private address" are very
    different problems for the person debugging why their calendar won't
    load, and conflating them into one message hides the real cause.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "not a valid URL"
    if parsed.scheme not in ("http", "https"):
        return False, f"unsupported URL scheme {parsed.scheme!r} - use http or https"
    hostname = parsed.hostname
    if not hostname:
        return False, "URL has no hostname"
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"couldn't resolve hostname {hostname!r} ({e})"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _ip_is_forbidden(ip):
            return False, f"{hostname!r} resolves to a private/internal address ({ip}) - refusing to fetch it"
    return True, None


def _ip_is_forbidden(ip):
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


class _ValidatingHTTPAdapter(requests.adapters.HTTPAdapter):
    """Re-resolves and re-validates the target hostname immediately before
    each request is sent - including every redirect hop, which the up-front
    _check_external_url never saw at all. Overrides send() (not
    get_connection(), which newer requests versions no longer call for
    HTTPS) so it works across requests releases."""

    def send(self, req, **kwargs):
        hostname = urlparse(req.url).hostname
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            raise requests.exceptions.ConnectionError(
                f"couldn't resolve {hostname!r} ({e})")
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if _ip_is_forbidden(ip):
                raise requests.exceptions.ConnectionError(
                    f"refusing to connect: {hostname!r} resolves to private/internal address {ip}")
        return super().send(req, **kwargs)


# Session used for all user-supplied ICS URL fetches.
_ics_session = requests.Session()
_ics_session.mount("http://", _ValidatingHTTPAdapter())
_ics_session.mount("https://", _ValidatingHTTPAdapter())
STATE_SHAPE = {
    "settings": dict, "tasks": list, "timelog": list, "notes": list,
    "snippets": list, "pastes": list, "calSeen": dict,
}


def _clean_state(state):
    """Keep only known top-level keys with the expected container type.
    Shared by the live PUT /api/state and the backup-restore import
    endpoint, so both apply exactly the same validation - no drift between
    'save my current edits' and 'restore from a file'."""
    if not isinstance(state, dict):
        return None
    clean = {}
    for k, typ in STATE_SHAPE.items():
        if k in state and isinstance(state[k], typ):
            clean[k] = state[k]
    if "activeTimer" in state and (state["activeTimer"] is None or isinstance(state["activeTimer"], dict)):
        clean["activeTimer"] = state["activeTimer"]
    return clean


def _require_env(name):
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"{name} is not set - see .env.example")
    return v


def _default_for(key):
    dv = KEY_DEFAULTS.get(key)
    return json.loads(json.dumps(dv)) if dv is not None else None


def _wait_for_db(uri, attempts=30, delay=1.0):
    """docker-compose starts containers concurrently - `depends_on` only
    waits for the postgres container to start, not for it to accept
    connections yet, so retry the actual connection for a bit."""
    import sqlalchemy
    last_err = None
    for _ in range(attempts):
        try:
            engine = sqlalchemy.create_engine(uri)
            with engine.connect():
                engine.dispose()
                return
        except Exception as e:
            last_err = e
            time.sleep(delay)
    raise RuntimeError(f"Could not connect to database after {attempts * delay:.0f}s: {last_err}")


def create_app():
    app = Flask(__name__, static_folder=STATIC)

    # Security-event logging goes to stdout (docker logs / journald pick it
    # up). Under gunicorn, inherit its handlers so lines aren't dropped.
    gunicorn_logger = logging.getLogger("gunicorn.error")
    if gunicorn_logger.handlers:
        logger.handlers = gunicorn_logger.handlers
        logger.setLevel(gunicorn_logger.level or logging.INFO)
    elif not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    logger.setLevel(min(logger.level or logging.INFO, logging.INFO))

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # 'unsafe-inline' is required: index.html and the auth templates are
        # single-file pages with inline <script>/<style>. The CSP still locks
        # out every external source, framing, plugins and form hijacking.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self'; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        return response

    app.config["SECRET_KEY"] = _require_env("FLASK_SECRET_KEY")
    app.config["SQLALCHEMY_DATABASE_URI"] = _require_env("DATABASE_URL")
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {"pool_pre_ping": True}
    app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB cap on any request body
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    limiter.init_app(app)
    csrf.init_app(app)

    app.register_blueprint(auth_bp_module.bp)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    get_encryptor()  # fail fast at startup if TIMEPILOT_MASTER_KEY is missing/invalid

    _wait_for_db(app.config["SQLALCHEMY_DATABASE_URI"])
    with app.app_context():
        db.create_all()

    @app.route("/healthz")
    def healthz():
        try:
            db.session.execute(db.text("SELECT 1"))
            return jsonify({"ok": True}), 200
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return jsonify({"ok": False, "error": "internal error"}), 503

    # ---- routes ----
    @app.route("/")
    @login_required
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.route("/api/csrf-token")
    @login_required
    def csrf_token():
        from flask_wtf.csrf import generate_csrf
        return jsonify({"token": generate_csrf()})

    @app.route("/api/whoami")
    @login_required
    def whoami():
        return jsonify({"username": current_user.username})

    # The JSON API below is intentionally CSRF-exempt: it only accepts
    # application/json bodies (a cross-site <form> can't set that content
    # type without JS, and cross-origin JS can't reach a same-origin
    # endpoint with cookies unless CORS explicitly allows it - which this
    # app never does). Combined with SameSite=Lax session cookies, that
    # closes the classic CSRF vector. CSRF tokens stay enforced on the
    # server-rendered /login and /signup forms, which are the actual attack
    # surface for cookie-based auth. See README "Security notes".
    #
    # The content-type requirement is ENFORCED via _json_body() below - not
    # just assumed. get_json(force=True) would happily parse a
    # <form enctype="text/plain"> body that looks like JSON, which would
    # quietly invalidate the whole rationale above.
    def _json_body():
        """Body as parsed JSON, or None unless Content-Type is application/json."""
        if not request.is_json:
            return None
        return request.get_json(silent=True)
    @app.route("/api/state", methods=["GET"])
    @login_required
    @csrf.exempt
    def get_state():
        resp = jsonify(load_state(current_user.id))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/api/state", methods=["PUT"])
    @login_required
    @csrf.exempt
    def put_state():
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        clean = _clean_state(_json_body())
        if clean is None:
            return jsonify({"error": "Invalid state payload"}), 400
        cur = load_state(current_user.id)
        cur.update(clean)
        save_state(current_user.id, cur)
        return jsonify({"ok": True})

    EXPORT_VERSION = 1

    @app.route("/api/export")
    @login_required
    def export_data():
        logger.info("user %s (%s) exported data", current_user.id, current_user.username)
        state = load_state(current_user.id)
        state.pop("activeTimer", None)   # a running timer isn't meaningful in a backup
        return jsonify({
            "app": "timepilot",
            "exportVersion": EXPORT_VERSION,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "username": current_user.username,
            "state": state,
        })

    # CSRF-exempt for the same reason as /api/state: only valid JSON is
    # accepted (request.get_json requires real JSON syntax), which a
    # cross-site HTML form cannot produce - see the CSRF note above PUT
    # /api/state.
    @app.route("/api/import", methods=["POST"])
    @login_required
    @csrf.exempt
    def import_data():
        if not request.is_json:
            return jsonify({"error": "Content-Type must be application/json"}), 415
        payload = _json_body()
        if not isinstance(payload, dict) or payload.get("app") != "timepilot":
            return jsonify({"error": "Not a TimePilot export file"}), 400
        if payload.get("exportVersion") != EXPORT_VERSION:
            return jsonify({"error": f"Unsupported export version {payload.get('exportVersion')!r}"}), 400
        clean = _clean_state(payload.get("state"))
        if clean is None:
            return jsonify({"error": "Export file's data section is malformed"}), 400
        clean.pop("activeTimer", None)   # never resurrect a stale running timer from a backup
        # full replace, not merge - restoring a backup means "make my data
        # match this file", not "add this file's tasks to what's already there"
        fresh = {k: (dict() if t is dict else list()) for k, t in STATE_SHAPE.items()}
        fresh.update(clean)
        save_state(current_user.id, fresh)
        logger.info("user %s (%s) imported/restored data (full replace)",
                    current_user.id, current_user.username)
        return jsonify({"ok": True, "restored": {k: len(v) for k, v in clean.items() if isinstance(v, (list, dict))}})

    # cal_upload is CSRF-PROTECTED (unlike the pure-JSON endpoints below): it
    # accepts arbitrary bytes with no Content-Type requirement, so unlike
    # /api/state it CAN be produced by a cross-site <form enctype="text/plain">
    # (the "BEGIN:VCALENDAR" substring check doesn't require an exact prefix).
    # The frontend fetches a CSRF token first and sends it as X-CSRFToken.
    @app.route("/api/calendar/upload", methods=["POST"])
    @login_required
    def cal_upload():
        data = request.get_data()
        if len(data) > 20 * 1024 * 1024:
            return jsonify({"error": "ICS file too large (max 20 MB)"}), 413
        if b"BEGIN:VCALENDAR" not in data[:4000]:
            return jsonify({"error": "That doesn't look like an ICS file"}), 400
        set_user_ics_bytes(current_user.id, data)
        logger.info("user %s (%s) uploaded calendar file (%d bytes)",
                    current_user.id, current_user.username, len(data))
        CACHE.pop(f"user:{current_user.id}", None)
        return jsonify({"ok": True, "size": len(data)})

    @app.route("/api/calendar")
    @login_required
    @csrf.exempt
    def calendar():
        if not ICS_OK:
            return jsonify({"error": "Install icalendar + recurring-ical-events"}), 500
        settings = (get_domain_json(current_user.id, "settings") or {}).get("settings") or {}
        url = (settings.get("icsUrl") or "").strip()

        day = request.args.get("date") or date.today().isoformat()
        force = request.args.get("refresh") == "1"
        try:
            d = date.fromisoformat(day)
        except ValueError:
            return jsonify({"error": "Bad date"}), 400

        raw, source, warn = None, None, None
        if url:
            ok, reason = _check_external_url(url)
            if not ok:
                warn = f"ICS URL: {reason}"
            else:
                cache_key = f"url:{url}"
                now = time.time()
                cached = CACHE.get(cache_key)
                if force or not cached or now - cached[0] > CACHE_TTL:
                    try:
                        r = _ics_session.get(url, timeout=15)
                        r.raise_for_status()
                        CACHE[cache_key] = (now, r.content)
                    except Exception as e:
                        warn = f"ICS URL fetch failed ({e})"
                if cache_key in CACHE:
                    raw, source = CACHE[cache_key][1], "url"
        if raw is None:
            uploaded = get_user_ics_bytes(current_user.id)
            if uploaded is not None:
                raw, source = uploaded, "file"
                warn = ((warn + " - ") if warn else "") + "using uploaded file"
        if raw is None:
            return jsonify({"error": (warn + " and no uploaded file. " if warn else "")
                            + "Set an ICS URL or upload a .ics file in Settings"}), 400

        try:
            cal = icalendar.Calendar.from_ical(raw)
            occurrences = recurring_ical_events.of(cal).between(d, d + timedelta(days=1))
        except Exception as e:
            return jsonify({"error": f"ICS parse failed: {e}"}), 500

        ignore = set(x.lower().strip() for x in (settings.get("ignoreEvents") or []))
        events = []
        for ev in occurrences:
            title = str(ev.get("SUMMARY", "(no title)"))
            if title.lower().strip() in ignore:
                continue
            start = ev.get("DTSTART").dt
            end = ev.get("DTEND").dt if ev.get("DTEND") else start
            all_day = not hasattr(start, "hour")
            if hasattr(start, "tzinfo") and start.tzinfo:
                start = start.astimezone()
            if hasattr(end, "tzinfo") and end.tzinfo:
                end = end.astimezone()
            events.append({
                "title": title,
                "location": str(ev.get("LOCATION", "")) if ev.get("LOCATION") else "",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "allDay": all_day,
            })
        events.sort(key=lambda e: e["start"])
        return jsonify({"date": day, "events": events, "source": source, "warn": warn})

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5170, debug=False)
