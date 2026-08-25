from __future__ import annotations


def test_undo_redo_restores_immediately_saved_changes(db, tmp_path):
    db.enable_history(tmp_path / "history", limit=50)
    original = db.one("SELECT name FROM contacts WHERE id=1")["name"]

    db.execute("UPDATE contacts SET name=? WHERE id=1", ("변경된 담당자",))
    assert db.one("SELECT name FROM contacts WHERE id=1")["name"] == "변경된 담당자"
    assert db.can_undo and not db.can_redo

    assert db.undo()
    assert db.one("SELECT name FROM contacts WHERE id=1")["name"] == original
    assert db.can_redo

    assert db.redo()
    assert db.one("SELECT name FROM contacts WHERE id=1")["name"] == "변경된 담당자"


def test_history_is_limited_and_new_edit_clears_redo(db, tmp_path):
    db.enable_history(tmp_path / "history", limit=3)
    for index in range(5):
        db.execute("UPDATE contacts SET phone=? WHERE id=1", (str(index),))
    undo_count = 0
    while db.undo():
        undo_count += 1
    assert undo_count == 3

    assert db.redo()
    db.execute("UPDATE contacts SET phone='새 분기' WHERE id=1")
    assert not db.can_redo


def test_settings_changes_do_not_fill_data_undo_history(db, tmp_path):
    db.enable_history(tmp_path / "history", limit=50)
    db.set_setting("calendar_side_visible", "0")
    assert not db.can_undo
