"""batch_add_items(): new item ids must never collide with existing ones.

Regression: ids used to be ``%Y%m%d%H%M%S`` + list index, so two imports in
the same second generated the same id; INSERT OR IGNORE then skipped the new
item and the project was linked to a DIFFERENT, older item.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from core import item_db


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(item_db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(item_db, "_wal_enabled", False)
    item_db.init_db()
    return item_db


def _freeze_clock(monkeypatch):
    fixed = datetime(2026, 1, 1, 12, 0, 0, 0)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(item_db, "datetime", FrozenDateTime)


def test_two_imports_in_the_same_instant_link_their_own_items(db, monkeypatch):
    p1 = db.create_project("first")["id"]
    p2 = db.create_project("second")["id"]
    _freeze_clock(monkeypatch)   # both imports now see the SAME timestamp

    added1, linked1, _ = db.batch_add_items([{"label": "Матеріал А"}], project_id=p1)
    added2, linked2, _ = db.batch_add_items([{"label": "Матеріал Б"}], project_id=p2)

    assert (added1, linked1, added2, linked2) == (1, 1, 1, 1)
    labels = sorted(i["label"] for i in db.load_items())
    assert labels == ["Матеріал А", "Матеріал Б"]
    assert [i["label"] for i in db.get_project_items(p1)] == ["Матеріал А"]
    assert [i["label"] for i in db.get_project_items(p2)] == ["Матеріал Б"]


def test_existing_label_is_reused_not_duplicated(db):
    p = db.create_project("p")["id"]
    db.batch_add_items([{"label": "Цемент"}])
    added, linked, skipped = db.batch_add_items(
        [{"label": "Цемент"}, {"label": "Пісок"}], project_id=p)
    assert (added, linked, skipped) == (1, 2, 0)
    assert [i["label"] for i in db.get_project_items(p)] == ["Цемент", "Пісок"]
    assert len(db.load_items()) == 2
