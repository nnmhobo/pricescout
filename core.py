"""PriceScout — shared state, constants, helpers."""

import json
import re
from datetime import datetime
from pathlib import Path

EXPORTS_DIR    = Path("exports")
DEBUG_DIR      = Path("debug")
LAST_RUN_FILE  = Path("last_run.json")


def ensure_debug_dir():
    DEBUG_DIR.mkdir(exist_ok=True)


def ensure_exports_dir():
    EXPORTS_DIR.mkdir(exist_ok=True)


# ── Persist last run results ──────────────────────────────────

def save_last_run(results: list, label: str, last_run: str):
    try:
        LAST_RUN_FILE.write_text(
            json.dumps({"results": results, "label": label, "last_run": last_run},
                       ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass


def load_last_run() -> dict:
    if LAST_RUN_FILE.exists():
        try:
            return json.loads(LAST_RUN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


# ── In-memory run state ───────────────────────────────────────

def _make_state():
    saved = load_last_run()
    return {
        "running":        False,
        "stop_requested": False,
        "log":            [],
        "results":        saved.get("results", []),
        "last_run":       saved.get("last_run"),
        "error":          None,
        "label":          saved.get("label", ""),
        "parallel_items": None,
        "limit":          None,
        "total_items":    None,
    }

state = _make_state()


def log(msg: str):
    ts    = datetime.now().strftime("%H:%M:%S")
    entry = f"[{ts}] {msg}"
    state["log"].append(entry)
    print(entry)


# ── Helpers ───────────────────────────────────────────────────

def normalize_label(raw: str) -> str:
    result = re.sub(r'(\d)\s*[*×xX]\s*(\d)', r'\1x\2', raw)
    result = re.sub(r'(\d)\s*(кг|мм|см|м)\b', r'\1\2', result, flags=re.IGNORECASE)
    return result.strip()