"""Shared extension instances, created here and initialised in app.py's
create_app() - keeps auth.py/models.py free of circular imports."""
import os

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
# In-memory rate-limit storage is per-process, so it's only a true limit
# within a single gunicorn worker - with -w 2 (see Dockerfile), someone
# could in principle get up to ~2x a given limit by landing on both workers.
# That's an acceptable trade for this app's threat model (slowing down
# brute-force login attempts on a small self-hosted instance, not a hard
# security boundary) rather than adding Redis as a hard dependency just for
# this. Passing storage_uri explicitly (rather than leaving it unset) also
# silences flask-limiter's "no storage specified" warning - the omission
# was never a bug, just unstated, and this states it.
#
# If you run more workers/replicas and want the limits actually shared
# across them, point TIMEPILOT_RATELIMIT_STORAGE_URI at a Redis instance,
# e.g. redis://localhost:6379.
limiter = Limiter(key_func=get_remote_address,
                   storage_uri=os.environ.get("TIMEPILOT_RATELIMIT_STORAGE_URI", "memory://"))
csrf = CSRFProtect()
