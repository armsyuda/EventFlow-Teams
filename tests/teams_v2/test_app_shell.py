from pathlib import Path
import time
from unittest.mock import Mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidgetItem

from eventflow_teams_v2.api import Organization
from eventflow_teams_v2 import app as teams_app
from eventflow_teams_v2.app import CompanyManagementPage, CompanyMembersPage, TeamsV2Window, _launch_options, _write_update_health_file
from eventflow_teams_v2.config import TeamsV2Config
from eventflow_teams_v2.session import Session
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


def test_update_restart_arguments_write_a_health_file(tmp_path: Path) -> None:
    health = tmp_path / "health.ok"
    options = _launch_options(["--update-health-file", str(health), "--restarting-after-update"])
    assert options.restarting_after_update
    _write_update_health_file(options.update_health_file)
    assert health.read_text(encoding="ascii") == "ok"


def test_packaged_teams_client_checks_for_updates_on_launch(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    called = Mock()
    monkeypatch.setattr(teams_app, "is_packaged_app", lambda: True)
    monkeypatch.setattr(TeamsV2Window, "_check_updates_on_launch", called)
    window = TeamsV2Window(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path))
    for _ in range(20):
        app.processEvents(); time.sleep(0.06)
        if called.called: break
    assert called.called
    window.deleteLater()


def test_company_lookup_failure_offers_retry_without_forcing_logout(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = TeamsV2Window(TeamsV2Config("https://example.supabase.co", "publishable", tmp_path))
    window.organizations._automatic_retries = 2
    window.organizations._failed("회사 서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")

    assert not window.organizations.retry_button.isHidden()
    assert "로그아웃" not in window.organizations.message.text()
    window.deleteLater()


def test_company_permission_editor_uses_simple_read_and_edit_rows() -> None:
    QApplication.instance() or QApplication([])
    page = CompanyMembersPage(Mock(), Organization("org", "회사", "OWNER"))
    page.members = [{"user_id": "pm", "display_name": "PM", "email": "pm@example.com", "role": "PM", "status": "ACTIVE", "overrides": []}]
    page.table.setRowCount(1)
    for column, value in enumerate(("PM", "프로젝트 담당자", "● 사용 가능")):
        page.table.setItem(0, column, QTableWidgetItem(value))
    page._select_row(0, 0)

    assert page.table.currentRow() == 0
    assert page.selected_caption.text() == "선택한 직원 · 1번"
    assert page.person.text() == "PM"
    assert page.permission_scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    assert page.permission_scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert len(page.permission_rows) == 6
    assert "participants.view" not in page.permission_boxes
    assert "backup.create" not in page.permission_boxes
    assert "members.manage" not in page.permission_boxes
    checklist_view, checklist_edit, _, _ = page.permission_rows[1]
    assert checklist_edit is not None
    checklist_view.setChecked(False); assert not checklist_edit.isChecked()
    checklist_edit.setChecked(True); assert checklist_view.isChecked()
    page.deleteLater()


def test_company_management_cards_keep_compact_actions_on_the_right() -> None:
    QApplication.instance() or QApplication([])
    page = CompanyManagementPage(Organization("org", "회사", "OWNER"))
    buttons = {button.text(): button for button in page.findChildren(QPushButton)}
    assert buttons["회사 코드 복사"].width() == 156
    assert buttons["직원·권한 관리"].width() == 156
    assert buttons["게스트 초대 관리"].width() == 156
    page.deleteLater()


def test_company_selection_opens_local_ui_against_v2_workspace(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    config = TeamsV2Config("https://example.supabase.co", "publishable", tmp_path)
    window = TeamsV2Window(config)
    window.api.session = Session("access", "refresh", "user-a")
    monkeypatch.setattr(window.api, "permissions", lambda _organization_id: {"events.view", "checklist.view"})
    monkeypatch.setattr(window.api, "workspace_snapshot", lambda _organization_id: {
        "cursor": 0, "events": [], "event_tasks": [], "vendors": [], "people": [],
        "master_items": [], "event_vendors": [], "event_freelancers": [],
    })

    window._open_workspace(Organization("org-a", "테스트 회사", "OWNER"))
    for _ in range(50):
        app.processEvents()
        if window.local_window and window.local_window.isEnabled():
            break
        time.sleep(0.01)

    assert window.workspace_db is not None
    assert window.workspace_db.path == tmp_path / "workspaces" / "user-a" / "org-a" / "data" / "event_checklist.db"
    assert window.stack.currentWidget() is window.local_window
    assert window.local_window is not None and window.local_window.isEnabled()
    assert window.sync_text.text() == "동기화 완료"
    assert not hasattr(window, "company_text")
    assert not hasattr(window, "account_menu")
    assert window.local_window.save_button.text() == "회사변경"
    window._close_workspace()
    window.deleteLater()


def test_cached_workspace_opens_without_replacing_unsent_local_changes(tmp_path: Path, monkeypatch) -> None:
    app = QApplication.instance() or QApplication([])
    config = TeamsV2Config("https://example.supabase.co", "publishable", tmp_path)
    window = TeamsV2Window(config); window.api.session = Session("access", "refresh", "user-a")
    organization = Organization("org-a", "테스트 회사", "OWNER")
    calls = {"snapshot": 0, "changes": 0}
    monkeypatch.setattr(window.api, "permissions", lambda _organization_id: {"events.view", "checklist.view"})
    def snapshot(_organization_id):
        calls["snapshot"] += 1
        return {"cursor": 5, "events": [], "event_tasks": [], "vendors": [], "people": [], "master_items": [], "event_vendors": [], "event_freelancers": []}
    monkeypatch.setattr(window.api, "workspace_snapshot", snapshot)
    monkeypatch.setattr(window.api, "workspace_changes", lambda _organization_id, _cursor: calls.__setitem__("changes", calls["changes"] + 1) or {"cursor": 5, "changes": []})
    window._open_workspace(organization)
    for _ in range(50):
        app.processEvents(); time.sleep(0.01)
        if window.local_window and window.local_window.isEnabled(): break
    assert window.workspace_db is not None
    assert window.workspace_db.one("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1")["remote_cursor"] == "5"
    assert window.workspace_db.pending_outbox() == []
    window._close_workspace()
    reopened = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    assert reopened.pending_outbox() == []
    reopened.close()

    window._open_workspace(organization)
    for _ in range(200):
        app.processEvents(); time.sleep(0.01)
        if calls["changes"]: break
    assert calls == {"snapshot": 1, "changes": 1}, window.sync_text.text()
    assert window.local_window is not None and window.local_window.isEnabled()
    window._close_workspace(); window.deleteLater()
