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

MAX_LOG_LINES = 2000


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
        r.geometry("560x300")
        r.minsize(520, 260)
        r.protocol("WM_DELETE_WINDOW", self.on_close)

        head = ttk.Frame(r, padding=(16, 12, 16, 4))
        head.pack(fill="x")
        ttk.Label(head, text="PriceScout", font=("Georgia", 18, "bold")).pack(anchor="w")
        ttk.Label(head, text="Моніторинг цін будматеріалів",
                  foreground="#777").pack(anchor="w")

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
            self.root.geometry("560x300")
            self.btn_log.configure(text="Детальніше ▾")
        else:
            self.log_frame.pack(fill="both", expand=True)
            self.root.geometry("560x460")
            self.btn_log.configure(text="Згорнути ▴")
        self.log_visible = not self.log_visible

    # ── Thread-safe UI helpers ─────────────────────────────────
    def ui(self, fn, *args):
        self.root.after(0, lambda: fn(*args))

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
            self.ui(self.progress.stop)

    def _do_setup_and_launch(self):
        self.ui(self.progress.start, 12)

        # ── Already running? (another window / autostart) ──────
        if server_responds():
            self.external = True
            for i in range(4):
                self.mark_step(i, "skip")
            self.set_status(f"PriceScout вже запущено — {URL}")
            self.ui(self.progress.stop)
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
        self.ui(self.progress.stop)
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
        self.ui(self.progress.stop)
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
