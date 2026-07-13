"""
PriceScout — GUI installer / launcher.

Shown to the customer instead of a raw cmd window. Started by START.bat via
``pythonw setup_gui.py`` (no console). On first run it walks the setup steps
(venv → dependencies → browser) with a progress bar and a collapsible log;
afterwards it acts as a small control window: start status, "Відкрити у
браузері" and "Зупинити" buttons. Closing the window stops the server.

IMPORTANT: this file runs on the SYSTEM Python, before the venv exists —
it must import ONLY the standard library (tkinter, subprocess, urllib, …).
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
VENV_PY = VENV_DIR / "Scripts" / "python.exe"
SCRAPLING_EXE = VENV_DIR / "Scripts" / "scrapling.exe"
SETUP_MARK = VENV_DIR / ".setup_done"

# Hide child console windows (we are running under pythonw).
CREATE_NO_WINDOW = 0x08000000

# Child processes write to PIPES (no console): without this, Windows Python
# encodes their stdout with the locale codepage (cp1252) and app.py's
# Ukrainian startup banner crashes with UnicodeEncodeError. Forcing UTF-8
# also makes unspecified open() calls inside the app behave sanely.
CHILD_ENV = {
    **os.environ,
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
    # pip niceties: no "new version available" banner, never prompt.
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
}

MAX_LOG_LINES = 2000  # log widget scrollback cap

# Window icon — the app's "PS" brand mark (gold box on ink) pre-rendered as
# tiny PNGs and embedded base64, so the launcher stays a single stdlib-only
# file with no image assets. Without this, Windows shows the default Tcl/Tk
# feather icon in the title bar and taskbar.
ICON_16 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABA0lEQVR42mPcOsnnPwMFgIWBgYEh"
    "vu0KWZoXVukwMDFQCAbeABZkTm6QHIOJBh8DAwMDw6/f/xgOXfrAsP/8O4bsAFkGSWF2BkZGBoZJ"
    "ax4xnL31CbsLpm14zMDAAFG0//x7BhdjIQZTDT6G+y++M6R1X2NYvOs5cV7IC5FjcDQUZNh9+i3D"
    "vrPvGH79/scQ6y7JICfOwfDgxXfcXoCB/lUPGS7c+czAwMDA4GkuwnDh9meGqw++MMS6SzF4W4oy"
    "LNr5DLsLsgJkGRgYGBgKw+QZRPjZ4OKFYfIMs0u1GbTkuRlO3/iI2wWT1z3CcM32k28Ytp98M4jT"
    "wSBJiQurdMg2AACiMk2XQ3VYZgAAAABJRU5ErkJggg=="
)
ICON_32 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAACaklEQVR42u2XXUiTURzGf/vwnZtO"
    "nVO2UZqGoqGUwVghEVKIEXQhUUJdGN0ESRfRRSVdSxeFFBUJXeRdUlCIN0VWN0opmoE4cwathbr2"
    "7VzbXp1vF+r6YFFq9hbsf/f+Dy/nx/Oc85xzFAXmEgkZSw3Q2Voty+TNbaMokbnUPxL9jfpWcdkV"
    "SAOkAf6tbbhSNWV6zh7dkvKHSDTBlC/Ok0EfA/ZQsm+tyKHBVoDFqCFDrcAbFHk3FeXlWBC7M4Ik"
    "rUKBkckwzW2jBMLzAMxFE5xoG+VChwN3QKR8s46WxiIabEYAGmxGzhwuZsYf59IdBy3tdm48dKHJ"
    "UHL+WCkVxVnrt0ACpn1x7r9wJ3t1NfkAHNhVAEDvkJ/g3AILCYlpX5zb3S68IfHPrgGF4nsogNys"
    "JScP1RZiMghfxyU4d3OCcWdkdWsg5cSA2ajhSJ0p2Xs+7AfgU0DEYtRgrczBWpmDJyhid0YYmQzz"
    "ZjLMQkJaH0C2VsXd5fyOxBI4Pn7m8YCXwfFZALqezXC6sQhBvSRoYZ5AYZ7A3h0G3H6Rq13vcQfE"
    "tQPMRRO0tNt/Ov7aEeZih4Pa6jxqyvSUWLSolEtemfIFmvabuf7gw/os+FV5Q/N093no7vOQKSip"
    "Ks2maZ8Zk0Fgq0W7sUF0+VQ5O8v1ye+YuMjQ21l6h3wAROOLG5+EJw9uwrYtF71OhVqloNiUyZ7t"
    "BgCeLoOsOQmztSo6W6sZnpjlWgovr9xzsrsql3qrkeP1FvQ6FTFxEZc7xq1HLl6NhVYHsJKEv++/"
    "SE+/h55+T/o0TAOkAf7zK5kcb0TZFVDI/Tz/ArPb14k4K1U4AAAAAElFTkSuQmCC"
)
ICON_48 = (
    "iVBORw0KGgoAAAANSUhEUgAAADAAAAAwCAYAAABXAvmHAAADoElEQVR42u2aX0xbVRzHP3ft6PqH"
    "3rCCdOsoReboBhrdxiAmxmiIZtEXk7n5ps/6sGzxCY1PRt/UmPCivkxjYlzMEhPjyJxh/omC3cbU"
    "SXEwS6VS1tJCy720t7f3+gDrLBQEpR1N7vfl5p5z7rn3c87vz/klV6h3+3SqWGaAM70dVfnxz7/x"
    "K9uoclU9gLnUtmxlLTd3w4QMAAPAADAADAADYEsdJZar79R+HFbTmmN0IJPViCayXBtPc/FygpSk"
    "rnyZSeCRB+o47HfSdM8OHFYTSk4nLaukZZXJWJYbkzJjEZmpmezmALz09ggAr73QSutua6H9y8E4"
    "n1yMItrNPNHp4umHG2jZZaVll5WeQy7e/SzMaFgqjN/p3M7Lz/nw1FsYmZDoO/cnk7cy5FQd0WHm"
    "gM/OU90NPPpgHQCvvD/GZCxTfhOak1TODkzzw/XZQpvDauLUs15E++L6CAKcPObFU29BUTXe+nSC"
    "0bCElMmjqBqxWYVLw0le/+gm8Tnl7vjAhZ9miu6tFlNhNdua7Pjci7s3L+dRclrJOVKSyoVAYnN9"
    "YL2aSqxcOW+jdem6o8iUDu5zcuX3VMl5zg/GOT8YrzyAIJRwbn2x3NaWVd0nj3kJhiUCwRTXQ/P8"
    "Fc+WLwqtV7tdlhVtE9OLThgtEVH8Xjt+r73gRyMhieHxNJeDKRRVqzzAk0fqi+7lTJ5vriUB+C0k"
    "EYll8TRYSj4r2s10t4t0t4uke1Q+7J9iaGSuMk4s2s2ceNxNp99ZaJtfyPPO2XAhF2i6Tt+58LpM"
    "pdZm5sVnmjjc5izvDhztqudo151VzyhLiWwszVclElkknuXVD8Z4aF8tXftF2n0O7KskSAE4/pib"
    "wGiqfAC3E9lGlNd0AsEUgWAKQYDmRivtPjsH25zs9diKxjburMHl3M5MKlcZH9iodB1C0QVC0QW+"
    "+DFOq8fG6ePNRccW0WH+V4CKHOZaPTbO9HZwaA27Ho/I9A8Vx/+MopXfiTeiI35xzf60nC+KYtMJ"
    "ZWsBdB0Q6WhxrNp//713+vqHZshrevmc+L9m69Mnmrk0nOTbn5PcSirkVJ3Guhp6Ol0FExu4muDz"
    "72PlrQf+GUbf/PgPghPSqnPcjMj0vneD+/bY2LvHRrPbSkeLg1qbCUvNNrKKRmwux9dXEnz3yyzj"
    "EXnzMvHteuB/RZylPBCJZxkYTholpQFgABgABoABYAAYAFtFK85C1fbbgWFCd1tCtf9u8zewdF+x"
    "PYYEYgAAAABJRU5ErkJggg=="
)


def read_port() -> int:
    """PORT from .env (manual parse — python-dotenv isn't installed yet)."""
    env = ROOT / ".env"
    if env.exists():
        try:
            for line in env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("PORT=") and not line.startswith("#"):
                    return int(line.split("=", 1)[1].strip())
        except Exception:
            pass
    return 8765   # must match app.py's default (5000 is contested on Windows)


PORT = read_port()
URL = f"http://localhost:{PORT}"


def server_responds(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(URL, timeout=timeout):
            return True
    except Exception:
        return False


class LauncherApp:
    STEPS = [
        "Створення середовища",
        "Встановлення компонентів",
        "Завантаження браузера",
        "Запуск PriceScout",
    ]

    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.external = False   # server was already running (we don't own it)
        self._build_ui()
        threading.Thread(target=self._worker, daemon=True).start()

    # ── UI construction ────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        r.title("PriceScout")
        # Replace the default Tcl/Tk feather icon with the PS brand mark.
        # References are kept on self — Tk drops images that get GC'd.
        try:
            self._icons = [tk.PhotoImage(data=d) for d in (ICON_48, ICON_32, ICON_16)]
            r.iconphoto(True, *self._icons)
        except Exception:
            pass
        r.geometry("560x340")
        r.minsize(520, 300)
        r.protocol("WM_DELETE_WINDOW", self.on_close)

        # Header — mirrors the app's top-left brand block (dark strip, gold
        # "PS" box, serif name). The logo is drawn on a Canvas: the web app's
        # logo is pure CSS, there is no image asset to load (and this file
        # must stay stdlib-only anyway).
        INK, GOLD = "#141820", "#b5924c"
        head = tk.Frame(r, bg=INK)
        head.pack(fill="x")
        brand = tk.Frame(head, bg=INK)
        brand.pack(anchor="w", padx=16, pady=10)
        logo = tk.Canvas(brand, width=38, height=38, bg=INK,
                         highlightthickness=0, bd=0)
        logo.create_rectangle(3, 3, 35, 35, outline=GOLD, width=2)
        logo.create_text(19, 19, text="PS", fill=GOLD, font=("Georgia", 12))
        logo.pack(side="left", padx=(0, 10))
        names = tk.Frame(brand, bg=INK)
        names.pack(side="left")
        tk.Label(names, text="PriceScout", bg=INK, fg="#ffffff",
                 font=("Georgia", 14)).pack(anchor="w")
        tk.Label(names, text="МОНІТОРИНГ ЦІН БУДМАТЕРІАЛІВ", bg=INK,
                 fg="#6b7078", font=("Segoe UI", 7)).pack(anchor="w")
        # thin gold underline, like the header's gradient rule in the app
        tk.Frame(r, bg=GOLD, height=1).pack(fill="x")

        body = ttk.Frame(r, padding=(16, 8))
        body.pack(fill="both", expand=True)

        self.step_labels: list[ttk.Label] = []
        for name in self.STEPS:
            lbl = ttk.Label(body, text=f"   {name}", foreground="#999")
            lbl.pack(anchor="w", pady=1)
            self.step_labels.append(lbl)

        self.progress = ttk.Progressbar(body, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 4))

        self.status = ttk.Label(body, text="Підготовка…")
        self.status.pack(anchor="w")

        btns = ttk.Frame(r, padding=(16, 4, 16, 6))
        btns.pack(fill="x")
        self.btn_open = ttk.Button(btns, text="Відкрити у браузері",
                                   command=lambda: webbrowser.open(URL),
                                   state="disabled")
        self.btn_open.pack(side="left")
        self.btn_stop = ttk.Button(btns, text="Зупинити", command=self.stop_server,
                                   state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        self.btn_log = ttk.Button(btns, text="Детальніше ▾", command=self.toggle_log)
        self.btn_log.pack(side="right")

        self.log_frame = ttk.Frame(r, padding=(16, 0, 16, 10))
        self.log_text = tk.Text(self.log_frame, height=10, font=("Consolas", 8),
                                bg="#10131a", fg="#9aa4b2", wrap="none",
                                state="disabled", relief="flat")
        scroll = ttk.Scrollbar(self.log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)
        self.log_visible = False

    def toggle_log(self):
        if self.log_visible:
            self.log_frame.pack_forget()
            self.root.geometry("560x340")
            self.btn_log.configure(text="Детальніше ▾")
        else:
            self.log_frame.pack(fill="both", expand=True)
            self.root.geometry("560x500")
            self.btn_log.configure(text="Згорнути ▴")
        self.log_visible = not self.log_visible

    # ── Thread-safe UI helpers ─────────────────────────────────
    def ui(self, fn, *args):
        self.root.after(0, lambda: fn(*args))

    def _hide_progress(self):
        """Stop AND remove the progress bar — once the app is running (or
        setup failed) a leftover half-filled bar just looks broken."""
        def _h():
            try:
                self.progress.stop()
                self.progress.pack_forget()
            except Exception:
                pass
        self.root.after(0, _h)

    def set_status(self, text: str):
        self.root.after(0, lambda: self.status.configure(text=text))

    def log(self, line: str):
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", line.rstrip() + "\n")
            if int(self.log_text.index("end-1c").split(".")[0]) > MAX_LOG_LINES:
                self.log_text.delete("1.0", "200.0")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _append)

    def mark_step(self, idx: int, state: str):
        """state: 'run' | 'ok' | 'skip'"""
        def _m():
            lbl = self.step_labels[idx]
            name = self.STEPS[idx]
            if state == "run":
                lbl.configure(text=f" ▸ {name}…", foreground="#1a6b5a")
            elif state == "ok":
                lbl.configure(text=f" ✓ {name}", foreground="#2e7d32")
            else:
                lbl.configure(text=f" ✓ {name} (готово)", foreground="#999")
        self.root.after(0, _m)

    # ── Setup / launch worker ──────────────────────────────────
    def _run(self, cmd: list, step_name: str) -> int:
        """Run a command, stream output into the log. Returns exit code."""
        self.log(f"$ {' '.join(str(c) for c in cmd)}")
        try:
            p = subprocess.Popen(
                cmd, cwd=str(ROOT), env=CHILD_ENV,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError as exc:
            self.log(f"[ПОМИЛКА] {exc}")
            return 1
        assert p.stdout is not None
        for line in p.stdout:
            self.log(line)
        p.wait()
        if p.returncode != 0:
            self.log(f"[ПОМИЛКА] «{step_name}» завершився з кодом {p.returncode}")
        return p.returncode

    def _worker(self):
        try:
            self._do_setup_and_launch()
        except Exception as exc:  # last-resort guard — show, don't vanish
            self.log(f"[КРИТИЧНО] {exc}")
            self.set_status(f"Помилка: {exc}")
            self._hide_progress()

    def _do_setup_and_launch(self):
        self.ui(self.progress.start, 12)

        # ── Already running? (another window / autostart) ──────
        if server_responds():
            self.external = True
            for i in range(4):
                self.mark_step(i, "skip")
            self.set_status(f"PriceScout вже запущено — {URL}")
            self._hide_progress()
            self.root.after(0, lambda: self.btn_open.configure(state="normal"))
            webbrowser.open(URL)
            return

        first_run = not SETUP_MARK.exists()

        # 1. venv
        if not VENV_PY.exists():
            self.mark_step(0, "run")
            self.set_status("Створюємо віртуальне середовище…")
            if self._run([sys.executable, "-m", "venv", str(VENV_DIR)], self.STEPS[0]) != 0:
                self._fail("Не вдалося створити середовище Python.")
                return
            first_run = True
        self.mark_step(0, "ok" if first_run else "skip")

        # 2 + 3. dependencies + browser (first run only)
        if first_run:
            self.mark_step(1, "run")
            self.set_status("Встановлюємо компоненти (одноразово, кілька хвилин)…")
            # `uv` downloads packages in parallel — several times faster than
            # plain pip on this dependency set (pandas/numpy/lxml/scrapling).
            # The venv's bundled pip is used only to bootstrap uv; if uv
            # can't be installed or fails, fall back to plain pip so setup
            # never becomes LESS reliable, only faster.
            deps_rc = 1
            if self._run([str(VENV_PY), "-m", "pip", "install", "--quiet", "uv"],
                         "uv (прискорювач встановлення)") == 0:
                deps_rc = self._run(
                    [str(VENV_PY), "-m", "uv", "pip", "install",
                     "--python", str(VENV_PY), "-r", "requirements.txt"],
                    self.STEPS[1])
            if deps_rc != 0:
                self.log("uv недоступний — встановлюємо через звичайний pip…")
                deps_rc = self._run(
                    [str(VENV_PY), "-m", "pip", "install", "-r", "requirements.txt"],
                    self.STEPS[1])
            if deps_rc != 0:
                self._fail("Не вдалося встановити компоненти. Перевірте інтернет і запустіть ще раз.")
                return
            self.mark_step(1, "ok")

            self.mark_step(2, "run")
            self.set_status("Завантажуємо браузер для збору цін…")
            rc = 1
            if SCRAPLING_EXE.exists():
                rc = self._run([str(SCRAPLING_EXE), "install"], self.STEPS[2])
            if rc != 0:
                rc = self._run([str(VENV_PY), "-m", "playwright", "install", "chromium"],
                               self.STEPS[2])
            if rc != 0:
                self._fail("Не вдалося завантажити браузер. Перевірте інтернет і запустіть ще раз.")
                return
            self.mark_step(2, "ok")
            SETUP_MARK.touch()
        else:
            self.mark_step(1, "skip")
            self.mark_step(2, "skip")

        # 4. launch the server
        self.mark_step(3, "run")
        self.set_status("Запускаємо сервер…")
        self.proc = subprocess.Popen(
            [str(VENV_PY), "app.py"], cwd=str(ROOT), env=CHILD_ENV,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._pump_server_log, daemon=True).start()

        # Wait until the HTTP endpoint answers (up to ~90 s — antivirus
        # scans can slow the very first import storm).
        for _ in range(180):
            if self.proc.poll() is not None:
                self._fail("Сервер завершився одразу після запуску — див. «Детальніше».")
                return
            if server_responds():
                break
            time.sleep(0.5)
        else:
            self._fail("Сервер не відповів вчасно — див. «Детальніше».")
            return

        self.mark_step(3, "ok")
        self.set_status(f"PriceScout запущено — {URL}   (закриття вікна зупинить програму)")
        self._hide_progress()
        self.root.after(0, lambda: (self.btn_open.configure(state="normal"),
                                    self.btn_stop.configure(state="normal")))
        webbrowser.open(URL)

    def _pump_server_log(self):
        p = self.proc
        if p is None or p.stdout is None:
            return
        for line in p.stdout:
            self.log(line)

    def _fail(self, msg: str):
        self.set_status(f"⚠ {msg}")
        self._hide_progress()
        self.root.after(0, lambda: self.btn_log.focus_set())
        if not self.log_visible:
            self.root.after(0, self.toggle_log)

    # ── Stop / close ───────────────────────────────────────────
    def stop_server(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.status.configure(text="Зупинено. Закрийте вікно або запустіть START.bat знову.")
        self.btn_stop.configure(state="disabled")
        self.btn_open.configure(state="disabled")

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askokcancel(
                    "PriceScout",
                    "Закрити вікно і зупинити PriceScout?"):
                return
            self.stop_server()
        self.root.destroy()


def main():
    if sys.version_info < (3, 10):
        root = tk.Tk(); root.withdraw()
        messagebox.showerror(
            "PriceScout",
            "Потрібен Python 3.10 або новіший.\n"
            f"Встановлено: {sys.version.split()[0]}\n\n"
            "Завантажте з https://www.python.org/downloads/ "
            "і поставте галочку «Add python.exe to PATH».")
        return
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
