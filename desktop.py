#!/usr/bin/env python3
"""TimePilot desktop widget (pywebview / Edge WebView2).

    pip install pywebview
    python  desktop.py            # run this first: errors print to the console
    pythonw desktop.py            # once working: no console window
    pythonw desktop.py --framed --on-top --w 520 --h 760

Errors are also written to desktop.log next to this file and shown in a
message box, so a silent pythonw launch can never fail invisibly.
If pywebview won't cooperate, use start_widget.ps1 instead (no extra deps).
"""
import argparse
import json
import os
import socket
import sys
import threading
import time
import traceback

def _app_base():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE = _app_base()
RES = getattr(sys, "_MEIPASS", BASE)
LOG = os.path.join(BASE, "desktop.log")
GEOM = os.path.join(BASE, "data", "window.json")
PORT = 5170


def load_geom():
    try:
        with open(GEOM, "r", encoding="utf-8") as f:
            g = json.load(f)
        # ignore clearly bogus positions (e.g. a monitor that no longer exists)
        if abs(g.get("x", 0)) > 20000 or abs(g.get("y", 0)) > 20000:
            g.pop("x", None); g.pop("y", None)
        return g
    except Exception:
        return {}


def save_geom(g):
    try:
        os.makedirs(os.path.dirname(GEOM), exist_ok=True)
        with open(GEOM, "w", encoding="utf-8") as f:
            json.dump(g, f)
    except Exception as e:
        log(f"save_geom: {e}")


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(msg.rstrip() + "\n")


def alert(title, msg):
    print(f"{title}\n{msg}", file=sys.stderr)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, title, 0x10)
        except Exception:
            pass


def port_open():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--framed", action="store_true", help="normal titlebar window")
    ap.add_argument("--on-top", action="store_true", help="always on top")
    ap.add_argument("--debug", action="store_true", help="open devtools; extra logging")
    ap.add_argument("--gui", default=None, help="force GUI backend (e.g. edgechromium, mshtml)")
    ap.add_argument("--w", type=int, default=None, help="width (overrides remembered size)")
    ap.add_argument("--h", type=int, default=None, help="height (overrides remembered size)")
    args = ap.parse_args()

    geom = load_geom()
    width = args.w or geom.get("w", 520)
    height = args.h or geom.get("h", 760)

    log(f"python {sys.version} | exe {sys.executable}")

    if port_open():
        log(f"Port {PORT} already serving - reusing existing TimePilot server.")
    else:
        import app as backend  # imported here so a Flask problem is caught+logged
        log(f"app module: STATIC={backend.STATIC} DATA_DIR={backend.DATA_DIR}")
        index_path = os.path.join(backend.STATIC, "index.html")
        log(f"index.html present: {os.path.exists(index_path)} ({index_path})")

        def run_server():
            try:
                backend.app.run(host="127.0.0.1", port=PORT, debug=False,
                                use_reloader=False, threaded=True)
            except Exception:
                # a crash in this daemon thread never reaches main(); log it here
                log("SERVER THREAD CRASHED:\n" + traceback.format_exc())

        threading.Thread(target=run_server, daemon=True).start()
        for _ in range(50):
            if port_open():
                break
            time.sleep(0.1)
        else:
            raise RuntimeError(
                f"Backend didn't come up on port {PORT}. See desktop.log for the server traceback.")
        log("Backend port open.")

    # confirm the page actually serves (an open socket isn't enough - static paths
    # can misresolve in a frozen exe, giving a blank window instead of an error)
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=5) as r:
            body = r.read(300)
        ok = b"TimePilot" in body
        log(f"Index check: HTTP {r.status}, TimePilot in body={ok}")
        if not ok:
            raise RuntimeError("Server responded but index.html didn't render - see desktop.log.")
    except Exception:
        log("INDEX CHECK FAILED:\n" + traceback.format_exc())
        raise

    try:
        import webview
    except ImportError:
        raise RuntimeError(
            "pywebview is not installed in THIS interpreter.\n"
            f"Interpreter: {sys.executable}\n"
            "Run:  pip install pywebview\n"
            "(If launching from a shortcut, point it at your venv's pythonw.exe.)")

    # pywebview 6.x doesn't expose __version__ at module top-level; use metadata
    try:
        from importlib.metadata import version as _pkgver
        pw_ver = _pkgver("pywebview")
    except Exception:
        pw_ver = getattr(webview, "__version__", "?")

    if sys.platform == "win32":
        try:  # own taskbar identity (instead of grouping under pythonw) so pinned/shortcut icons stick
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Bud.TimePilot")
        except Exception as e:
            log(f"AppUserModelID: {e}")

    def set_icon(window):
        """Set titlebar+taskbar icon on the native WinForms window (Windows only)."""
        ico = os.path.join(RES, "static", "timepilot.ico")
        if sys.platform != "win32" or not os.path.exists(ico):
            return
        try:
            import clr  # pythonnet - already a pywebview dependency on Windows
            clr.AddReference("System.Drawing")
            from System.Drawing import Icon
            window.native.Icon = Icon(ico)
            log("Window icon set.")
        except Exception as e:
            log(f"icon: {e}")

    log(f"pywebview {pw_ver}")

    # WebView2 runtime is required on Windows; a missing/broken runtime is the
    # usual cause of a window that opens blank or start() that hangs silently.
    # This check is advisory only - we log it but still try to launch, since the
    # registry layout varies and we'd rather attempt than wrongly block.
    if sys.platform == "win32":
        try:
            import winreg
            found = False
            for hive, path in (
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            ):
                try:
                    with winreg.OpenKey(hive, path) as k:
                        v, _ = winreg.QueryValueEx(k, "pv")
                        if v and v != "0.0.0.0":
                            found = True; break
                except OSError:
                    continue
            log(f"WebView2 runtime: {'found' if found else 'not detected (will try anyway)'}")
        except Exception as e:
            log(f"WebView2 check skipped: {e}")

    try:
        webview.settings["ALLOW_DOWNLOADS"] = True   # CSV export from the widget
    except Exception as e:
        log(f"ALLOW_DOWNLOADS: {e}")

    class Api:
        """Window controls callable from the page (frameless windows have no
        native titlebar to drag or edges to resize on Windows)."""
        _s = (0, 0, 0, 0)

        def begin(self):
            w = WIN[0]
            self._s = (w.x, w.y, w.width, w.height)
            return True

        def drag(self, dx, dy):
            x, y, _, _ = self._s
            WIN[0].move(int(x + dx), int(y + dy))

        def size(self, dx, dy):
            _, _, w, h = self._s
            WIN[0].resize(max(380, int(w + dx)), max(420, int(h + dy)))

        def minimize(self):
            WIN[0].minimize()

        def close(self):
            WIN[0].destroy()

        def restore(self):
            try:
                WIN[0].restore()
            except Exception:
                pass

    WIN = []
    WIN.append(webview.create_window(
        "TimePilot", f"http://127.0.0.1:{PORT}",
        width=width, height=height,
        x=geom.get("x"), y=geom.get("y"),
        frameless=not args.framed,
        easy_drag=False,   # drag handled in-page via the API above
        on_top=args.on_top,
        resizable=True,
        js_api=Api(),
    ))
    win = WIN[0]
    win.events.shown += lambda: set_icon(win)

    # remember size/position for next launch
    live = {"w": width, "h": height}
    if "x" in geom: live["x"], live["y"] = geom["x"], geom["y"]

    def on_resized(w, h): live["w"], live["h"] = int(w), int(h)
    def on_moved(x, y): live["x"], live["y"] = int(x), int(y)
    def on_closing():
        try:
            live.setdefault("x", win.x); live.setdefault("y", win.y)
        except Exception:
            pass
        save_geom(live)
        log(f"Saved geometry: {live}")

    for ev, fn in (("resized", on_resized), ("moved", on_moved), ("closing", on_closing)):
        try:
            handler = getattr(win.events, ev)
            handler += fn          # pywebview Event supports +=; returns the same object
        except Exception as e:
            log(f"event {ev}: {e}")
    log("Starting webview...")
    # Force the Edge Chromium backend on Windows (avoids the deprecated MSHTML
    # fallback that renders blank), and give it a writable storage dir so a
    # locked-down profile location can't stall window creation.
    start_kwargs = {}
    if sys.platform == "win32":
        start_kwargs["gui"] = args.gui or "edgechromium"
        try:
            sp = os.path.join(BASE, "data", "webview")
            os.makedirs(sp, exist_ok=True)
            start_kwargs["storage_path"] = sp
            start_kwargs["private_mode"] = False
        except Exception as e:
            log(f"storage_path: {e}")
    elif args.gui:
        start_kwargs["gui"] = args.gui
    log(f"webview.start kwargs: {start_kwargs}")
    try:
        webview.start(debug=args.debug, **start_kwargs)
    except Exception:
        log("webview.start RAISED:\n" + traceback.format_exc())
        raise
    log("Window closed.")


if __name__ == "__main__":
    try:
        open(LOG, "w").close()  # fresh log per run
        main()
    except Exception:
        tb = traceback.format_exc()
        log(tb)
        alert("TimePilot failed to start",
              tb[-1200:] + f"\n\nFull log: {LOG}")
        sys.exit(1)
