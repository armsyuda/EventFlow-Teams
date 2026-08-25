from __future__ import annotations

import pytest

from event_checklist.database import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "event_checklist.db")
    yield database
    database.close()

