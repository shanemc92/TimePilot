# TimePilot 
![Logo](docs/logo.png)

A local, single-user cockpit for managing your day: a Kanban task board, a day
planner that slots tasks around your calendar, a one-at-a-time timer, and a
timesheet exporter. Everything runs on your own machine - no cloud, no accounts,
no telemetry. Your data stays in plain JSON files you control.

Built with a tiny Flask backend and a single-file vanilla-JS frontend (no build
step, no npm). Optionally runs as a borderless desktop widget you can leave in
the corner of a screen.

![TimePilot screenshot](docs/screenshot.png)

## Features

- **Kanban board** - Today / This Week / Next Week / Next Month / Done, with
  drag-and-drop and colour-coded, fully customisable categories. The Done column
  clears itself each day (your time history is kept).
- **Day planner** - a timeline that merges your calendar meetings with slotted
  tasks and auto-fits the window. Drag tasks to reschedule; "Auto" drops a task
  into the first free gap that fits.
- **One-at-a-time timer** - a CASIO-style LCD clock in the top bar. Starting
  anything stops and logs the previous task. Quick "interrupt" chips (Message,
  Email, Call...) capture the little things with an optional note. Click the
  timer to edit the running task's name, category, or start time.
- **Timesheet export** - per-day editable entries that aggregate into a
  clean text list to paste into your time-tracking system, plus a date-range
  bulk export to CSV. Calendar meetings import automatically (and you can tell
  it to ignore titles like "Private Appointment").
- **Notes** - free-form sections for things that aren't tasks (follow-ups,
  questions, ideas).
- **Snippets & Clipboard** - two searchable libraries: code snippets (copied as
  plain text) and reusable text/templates with Markdown support (copied as rich
  formatted text). Filter by category, one-click copy.
- **Themes & fonts** - Dark, Light, HackTheBox and Dracula themes; Sans, Mono
  and Serif fonts. Reminders for slotted tasks. All offline.

## Quick start

Requires Python 3.9+.

```bash
git clone https://github.com/shanemc92/TimePilot.git
cd timepilot

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

Then open <http://localhost:5170>.

Want to try it with example data first? Generate a set before launching:

```bash
python sample_data.py                  # creates ./data with example content
```

The generated data is dated relative to today, so the board and Export tab
always look populated. Delete `data/` at any point to start fresh.

## Demo
![TimePilot demo](docs/demo.gif)

## Calendar (optional)

TimePilot reads your calendar from an **iCalendar (ICS)** feed - it never
connects to your mail account. Two ways to provide it:

1. **Published ICS URL** - in Outlook/Google Calendar, publish your calendar and
   copy the ICS link into Settings. Meetings refresh automatically (cached 5 min).
2. **Upload an .ics file** - a fallback if you don't have (or lose) a URL. Export
   your calendar and upload it in Settings.

Recurring meetings are expanded correctly, and times use your machine's local
timezone.

## Desktop widget (Windows)

Run TimePilot as a small borderless window instead of a browser tab:

```powershell
pip install pywebview
python  desktop.py                 # run once in a console to see any errors
pythonw desktop.py --on-top        # then silent, frameless, always-on-top
```

Drag it by the "TimePilot" title, resize from the corner grip, and use the
window buttons to minimise/close. Its size and position are remembered.

**Start at login with a desktop icon:**

```powershell
.\install_shortcuts.ps1            # Desktop + Start Menu + Startup shortcuts
.\install_shortcuts.ps1 -OnTop     # launch always-on-top
.\install_shortcuts.ps1 -NoStartup # skip the login autostart
```

No `pywebview`? `start_widget.ps1` opens TimePilot in an Edge app-mode window
instead (no extra dependencies).

The widget needs the **Microsoft Edge WebView2 Runtime** (preinstalled on
current Windows 10/11). If the window opens blank or won't appear, check
`desktop.log` next to the script, install the free runtime from
<https://developer.microsoft.com/microsoft-edge/webview2/>, or just run
`python app.py` in a browser instead. Run `python desktop.py --debug` to open
devtools and see any renderer errors.

## Portable .exe (optional)

Bundle everything into a single portable executable:

```powershell
pip install pyinstaller
.\build_exe.ps1            # -> dist\TimePilot.exe
.\build_exe.ps1 -OneDir    # folder build: faster startup, less AV-suspicious
```

The exe keeps its `data\` folder next to itself, so it's fully portable - move
the exe, move your data. It can be code-signed via `.\build_exe.ps1 -Sign`
(see the script header for options).

## Data & privacy

Everything lives in per-domain JSON files under `data/`:

| File | Contents |
|------|----------|
| `settings.json` | Preferences, categories, calendar URL |
| `tasks.json` | Board tasks |
| `history.json` | Time log (your export history) |
| `notes.json` | Notes sections |
| `snippets.json` | Code snippets |
| `clipboard.json` | Reusable text/templates |
| `runtime.json` | Active timer + calendar cache |

Back up, sync, or prune any of them independently. TimePilot binds to
`127.0.0.1` only and has no authentication by design - it's a personal,
local tool. Don't expose it on an untrusted network.

## Tech

- **Backend:** Flask, `icalendar` + `recurring-ical-events` for calendar parsing.
- **Frontend:** one `index.html`, vanilla JS, CSS custom properties for theming.
  No framework, no bundler.
- **Desktop:** `pywebview` (Edge WebView2 on Windows).

## Licence

MIT - see [LICENSE](LICENSE).
