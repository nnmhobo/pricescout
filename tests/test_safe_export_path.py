"""Path-traversal guard for the export download/delete routes.

`_safe_export_path` must:
  - resolve a clean name inside EXPORTS_DIR;
  - return None for any name that would escape the directory.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from routes.exports import _safe_export_path
from core.core import EXPORTS_DIR


def test_returns_path_inside_exports_dir():
    p = _safe_export_path("prices_20260518.xlsx")
    assert p is not None
    assert p.parent.resolve() == EXPORTS_DIR.resolve()


def test_rejects_dotdot():
    # The regex strips the slashes, so "../etc/passwd" collapses to a
    # benign filename inside EXPORTS_DIR — but the bare traversal tokens
    # must be rejected outright (defence in depth).
    assert _safe_export_path("..") is None
    assert _safe_export_path(".") is None


def test_traversal_collapses_to_safe_name():
    # "../etc/passwd" -> "..etcpasswd" after sanitisation: a normal filename
    # in EXPORTS_DIR. Verify the resolved path stays inside the dir.
    p = _safe_export_path("../etc/passwd")
    assert p is not None
    assert p.parent.resolve() == EXPORTS_DIR.resolve()


def test_rejects_empty_after_sanitisation():
    # Only characters stripped by the regex -> empty string -> rejected.
    assert _safe_export_path("///") is None
