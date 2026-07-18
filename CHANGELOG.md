# Changelog

Every entry is tagged `FEATURE` or `BUGFIX`. Sections and entries are in
chronological order (oldest first).

## Architecture: single-user desktop app → multi-user Docker server

- **FEATURE:** Replaced local per-file JSON storage with PostgreSQL, one
  encrypted row per user per data domain (settings, tasks, history, notes,
  snippets, clipboard, runtime).
- **FEATURE:** Added AES-256-GCM encryption at rest for all stored user
  data, keyed by a single `TIMEPILOT_MASTER_KEY`.
- **FEATURE:** Added multi-user accounts: signup/login/logout, password
  hashing, CSRF protection, rate limiting on auth endpoints.
- **FEATURE:** Removed the desktop widget entirely (pywebview wrapper,
  Windows shortcut installer, portable .exe builder) in favor of
  server-only mode.
- **FEATURE:** Verified with crypto round-trip tests, a full
  signup → use → logout → re-login flow, cross-user data isolation tests,
  encryption-at-rest confirmed via raw `pg_dump` inspection, and full
  browser (Playwright) tests.

## Docker packaging & CI

- **FEATURE:** Wrote `Dockerfile`, `docker-compose.yml` (app + Postgres).
- **FEATURE:** Set up a GitHub Actions workflow to build and publish the
  image to GHCR automatically on push/tag, plus a weekly scheduled rebuild
  to pick up base-image OS security patches.
- **FEATURE:** Added Dependabot for dependency/Docker-base-image/GitHub
  Actions updates.
- **BUGFIX:** Dockerfile `apt-get` build step was failing
  (network-dependent); removed it entirely after verifying
  `psycopg2-binary` and `cryptography` both ship prebuilt wheels for
  amd64+arm64, so no compiler was ever actually needed.
- **BUGFIX:** Postgres crash-loop on missing secrets - added fail-fast
  `${VAR:?message}` syntax so `docker compose up` refuses to start with a
  clear error instead of Postgres crash-looping silently.
- **FEATURE:** Diagnosed a genuine "No space left on device" Postgres
  startup failure as a real host/Docker-storage disk issue (not an app
  bug); added detailed troubleshooting docs (Docker Desktop VM disk cap,
  `DockerRootDir` mismatch, inode exhaustion).
- **BUGFIX:** gunicorn control-socket trying to write to a read-only path
  on startup (added `--no-control-socket`).
- **FEATURE:** Split local-testing config into `docker-compose.local.yml`
  (direct port + HTTP cookies for testing without a proxy).
- **FEATURE:** Added `docker-compose.proxy.yml` for attaching to an
  external Traefik's network - later removed (see below) in favor of a
  simpler model.
- **FEATURE:** Published the image at `ghcr.io/shanemc92/timepilot:latest`;
  updated compose file and docs to reference it directly, uncommented by
  default.
- **FEATURE:** Removed all Traefik-specific machinery (labels, external
  network attachment, `docker-compose.proxy.yml`, `DOMAIN`/`TRAEFIK_*` env
  vars) - app now just publishes on `127.0.0.1:5170`, the standard "any
  reverse proxy on the same host" pattern, so Traefik/Nginx/Caddy/etc. all
  work identically with zero app-specific config.

## Security hardening (initial pass)

- **FEATURE:** CSRF: JSON-only endpoints (state, export/import) safely
  exempted with documented reasoning; file-upload endpoints (calendar
  upload) kept protected since raw-byte bodies can be forged by a
  cross-site form.
- **BUGFIX:** Fixed a login timing side-channel: username enumeration was
  possible because password hashing only ran for existing usernames; now
  always hashes something so existing vs. non-existing accounts take equal
  time.
- **FEATURE:** Added an SSRF guard on the calendar ICS URL fetch: rejects
  URLs that resolve to private/loopback/link-local/reserved addresses,
  since the server (not the browser) does the fetching.
- **FEATURE:** Re-audited and pinned all dependencies to exact versions
  via a pip-compile lockfile.
- **BUGFIX:** Caught and fixed one real pre-release CVE (cryptography
  buffer overflow) before it shipped.
- **FEATURE:** Disabled caching on the state endpoint
  (`Cache-Control: no-store`) to rule out any stale-data-after-save class
  of bug.

## Backup / export / import

- **FEATURE:** Added native per-account export/import: single JSON file
  via Settings, full-replace semantics with a confirmation step,
  cross-user isolation verified.
- **FEATURE:** Added desktop-widget-compatible zip export/import
  (optionally AES-256 password-protected via pyzipper) for migrating data
  to/from the old single-user app's file format.
- **FEATURE:** Later removed the desktop-widget zip feature entirely
  (backend routes, frontend UI, pyzipper dependency) now that the old app
  is retired - native JSON export/import is the only supported path going
  forward.

## Feature: browser notifications

- **FEATURE:** Added an optional Settings toggle to fire real OS-level
  browser notifications (Notification API) alongside the existing in-app
  reminder modal, independent of the existing reminders toggle.

## Feature: calendar/Today page improvements

- **FEATURE:** Split "work hours" (bounds Auto-slotting) from a new,
  separate "calendar display range" (what the Today timeline actually
  shows/lets you drag into) - lets out-of-hours items be seen and placed
  manually without changing what Auto treats as normal hours.
- **FEATURE:** Added an optional lunch-break setting: Auto-slotting skips
  over it, and it renders as a distinct hatched block on the timeline.
- **FEATURE:** Added Outlook/Google-Calendar-style overlap handling:
  overlapping meetings and/or tasks now split side by side (cluster +
  greedy column layout) instead of one hiding the other.
- **BUGFIX:** Bulk timesheet export was re-syncing the calendar for every
  day in the range, risking overwriting a manual correction (e.g. a
  meeting that ran over/under); now purely reads whatever's already logged
  per day, no recalendar-sync side effects.

## Bug fixes (Today page & mobile)

- **BUGFIX:** Fixed the last hour label on the Today timeline rendering
  past the container's bottom edge into the panel below.
- **BUGFIX:** Fixed a mobile-only bug where typing a time into an
  unslotted task's input got silently wiped - caused by the on-screen
  keyboard triggering a `resize` event that forced a full re-render
  mid-edit; now skipped while a form field has focus.
- **BUGFIX:** Fixed the Export entries table's label column overlapping
  the category column on narrow/mobile screens (added a table min-width so
  it scrolls instead of squeezing to zero).

## Bug fix: calendar not loading at all

- **BUGFIX:** Root cause #1 (backend): the calendar route read
  `icsUrl`/`ignoreEvents` directly off the wrong (wrapped) settings shape,
  so it always saw an empty URL regardless of what was actually saved.
- **BUGFIX:** Root cause #2 (frontend, still broken after fixing #1):
  Settings' Save button only queued a debounced save (~600ms), so checking
  the Today tab right after saving could beat the actual write to the
  database; Save now explicitly waits for the write to complete before
  closing.

## Misc fixes

- **BUGFIX:** Investigated the login/signup page logo; confirmed the app's
  own logo (not a placeholder/clipboard icon) was already correctly in
  place, centered.
- **BUGFIX:** Converted a custom timer font (Cursed Timer) from TTF to
  WOFF, verified every digit glyph has identical advance width (the actual
  fix for timer digits shifting/jittering as numbers changed).
- **BUGFIX:** The new font was initially added alongside the old
  `digital.woff` instead of replacing it - corrected so only the intended
  file remains.

## Documentation

- **FEATURE:** Split docs into a maintainer README and a self-contained
  user-facing DEPLOY.md, then later consolidated back into a single
  simplified README.md (removing the maintainer-only publish/patch-workflow
  content) covering three equally-supported ways to run it: pull the
  published image, build your own image, or build from source.
- **FEATURE:** Removed a short-lived separate "minimal GHCR build bundle"
  zip in favor of just the one full repo zip.

## Security hardening (from independent review)

- **FEATURE:** Added security response headers: CSP, `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **FEATURE:** Added audit logging: logins (success/failure + source IP),
  signups, data exports/imports, calendar uploads - written to stdout.
- **FEATURE:** Tightened CSRF handling on `/api/state` and `/api/import`:
  now requires `Content-Type: application/json` instead of force-parsing
  any body.
- **FEATURE:** Calendar ICS fetch SSRF guard now re-validates on every
  redirect hop, closing a DNS-rebinding gap.
- **FEATURE:** `/healthz` no longer leaks internal error details to
  unauthenticated clients.
- **FEATURE:** Raised minimum password length to 12 characters for new
  signups (existing accounts unaffected).
- **FEATURE:** Added a scheduled pip-audit GitHub Actions workflow.
- **FEATURE:** Reduced default gunicorn workers 4 → 2, added memory/CPU
  limits in `docker-compose.yml`.
- **BUGFIX:** Caught a stranded/dead code path in the state-save handler
  that would have silently broken partial saves - fixed before shipping.

## GitHub / deployment

- **BUGFIX:** Image-publish workflow built the tag from the repo's actual
  casing (`TimePilot`), which GHCR rejects (must be lowercase) - hardcoded
  to lowercase.
- **FEATURE:** Added a demo GIF to the README.

## Notes tab

- **FEATURE:** Capped at 4 columns to match Snippets/Clipboard (previously
  uncapped, only looked capped by coincidence).
- **FEATURE:** Section panels now stretch to match the tallest one in
  their row.
- **FEATURE:** Added move-left/move-right buttons on sections.
- **BUGFIX:** Long unbroken text (e.g. long URLs) was overflowing the note
  box - now wraps.
- **FEATURE:** Replaced per-item delete with an edit popup (edit or
  delete); clicking a note's text now copies it to clipboard.

## Notifications (ntfy) - new feature

- **FEATURE:** New Notifications tab: schedule one-off or recurring push
  reminders via ntfy, delivered by a background dispatcher so they arrive
  even with the app closed.
- **FEATURE:** Settings: ntfy server URL, topic, optional icon URL.
- **FEATURE:** Toggle to push task/meeting pop-ups to ntfy too (needs a
  tab open, unlike scheduled reminders).
- **FEATURE:** Toggle to enable reminders for calendar meetings, not just
  tasks.
- **FEATURE:** Settings reorganized into collapsible sections, Save/Cancel
  pinned to the bottom.
- **FEATURE:** SSRF protection on the ntfy URL; private/internal addresses
  are opt-in via `TIMEPILOT_ALLOW_PRIVATE_NTFY`.
- **FEATURE:** Multi-worker safety: a Postgres advisory lock ensures only
  one worker dispatches reminders.
- **BUGFIX:** If the lock-holding worker died, the others gave up
  permanently instead of retrying - reminders would've silently stopped
  until a full restart. Fixed to retry and take over.
- **BUGFIX:** Notification titles showed a stray "?" between the emoji and
  text (e.g. "? Task due: ...") - header sanitizing was substituting "?"
  per dropped character instead of removing it.
- **FEATURE:** Paste a single emoji into the Tag field and it
  auto-converts to the matching ntfy shortcode; multiple pasted emoji keep
  only the first; unrecognized emoji are rejected with a message.
- **FEATURE:** Added a customizable quick-pick row of up to 10 tag
  buttons, configurable in Settings.
- **FEATURE:** Restyled the recurring toggle as a switch card.

## Login page

- **FEATURE:** Added `TIMEPILOT_LOGIN_BANNER` env var: optional message
  above login/signup (blank by default).
- **FEATURE:** Added `TIMEPILOT_DISABLE_SIGNUP` env var: fully disables
  public registration (`/signup` 404s, link hidden) while existing
  accounts still log in.

## Timer / timesheet

- **FEATURE:** Correcting a running timer's start time now also adjusts
  the previous logged entry's end time to match (task or meeting,
  whichever was last) - closes the gap instead of leaving unlogged time.
  On by default, with a Settings toggle.
- **FEATURE:** Added a live preview in the edit-timer popup showing
  exactly what will be adjusted, or why nothing will be.
- **BUGFIX:** The "last entry" logic picked whichever timelog entry had
  the latest end time by clock value, with no check that it had actually
  happened - a future calendar meeting would incorrectly win over a task
  that already finished. Fixed to only consider entries already ended by
  the current time.
- **BUGFIX:** Live preview said "extend" even when the adjustment was a
  shortening - changed to "adjust".

## Demo data (sample_data.py)

- **FEATURE:** Expanded seeded data: more tasks across all columns, an
  extra day of timesheet history, more notes/snippets/paste templates, two
  demo scheduled reminders.
- **FEATURE:** Added a generated demo `.ics` calendar (recurring standup,
  one-off meetings, an all-day event, a "Private Appointment" entry to
  demonstrate the ignore filter) - seeded through the same storage path as
  a real Settings → Calendar upload.
- **FEATURE:** Added `--no-ics` flag to skip the demo calendar.

## Repo / docs

- **FEATURE:** Added `deploy/init-timepilot-demo.sh`: an idempotent
  server-setup script for a public demo instance - installs and hardens
  SSH (custom port, key-only, fail2ban), locks the firewall down to
  SSH+443 only, enables unattended security upgrades, installs Docker,
  clones the repo, generates and preserves `.env` secrets, syncs a
  Cloudflare DNS record and obtains a Let's Encrypt cert via DNS-01,
  configures nginx, sends ntfy progress/failure notifications for each
  step, and schedules a nightly cron job that fully wipes the database and
  reseeds it with `sample_data.py` under a freshly generated password
  spliced into the login banner.
- **FEATURE:** Added this changelog (`CHANGELOG.md`).
