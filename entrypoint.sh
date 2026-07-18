#!/usr/bin/env sh
set -eu

# Without --preload, gunicorn's workers each import app.py independently in
# their own freshly-forked process (that's the whole point of not
# preloading - no shared state). create_app() runs db.create_all() as a
# side effect of that import, so on an EMPTY database, N workers booting
# together means N processes racing the same schema creation: each inspects
# the database, sees no tables, and issues a plain CREATE TABLE (no IF NOT
# EXISTS - that's not what SQLAlchemy's checkfirst emits) for the same
# names at close to the same instant. Whoever loses gets a "relation
# already exists" error and crashes; gunicorn respawns that worker, which
# races again on whatever's still missing. It usually converges in one or
# two respawns, but it's a genuine race, not a deliberate retry loop.
#
# Running the import here first - a single process, before gunicorn exists
# at all - creates every table exactly once, sequentially. By the time
# gunicorn forks its workers, each one's own create_all() finds the schema
# already complete and issues nothing, so there's nothing left to race over.
python -c "import app"

exec "$@"
