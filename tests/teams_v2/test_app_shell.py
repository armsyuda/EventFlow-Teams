from pathlib import Path
import time
from unittest.mock import Mock

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidgetItem, QWidget

from eventflow_teams_v2.api import Organization
from eventflow_teams_v2.app import _update_health_file
from eventflow_teams_v2.app import CompanyManagementPage, CompanyMembersPage, OrganizationPage, TeamsV2Window
from eventflow_teams_v2.staff_pages import EmployeeWorkPage
from eventflow_teams_v2.config import TeamsV2Config
from eventflow_teams_v2.session import Session
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


class _CompanyChoiceShowProbe(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.parents_at_show: list[QWidget | None] = []

    def eventFilter(self, watched, event):  # noqa: N802 - Qt API
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.objectName() == "TeamsCompanyChoice"
        ):
            self.parents_at_show.append(watched.parentWidget())
        return False


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


def test_company_permission_editor_requires_explicit_save_and_uses_atomic_api() -> None:
    QApplication.instance() or QApplication([])
    api = Mock(); page = CompanyMembersPage(api, Organization("org", "회사", "OWNER"))
    page.members = [{"user_id": "member", "display_name": "직원", "email": "member@example.com", "role": "MEMBER", "status": "ACTIVE", "overrides": []}]
    api.company_members.return_value = page.members
    page.table.setRowCount(1)
    page._select_row(0, 0)

    assert not page.apply.isEnabled()
    page.status.setCurrentIndex(page.status.findData("SUSPENDED"))
    assert page.apply.isEnabled()
    assert "저장 전" in page.save_state.text()
    page.apply_changes()

    api.save_company_member_access.assert_called_once()
    assert "서버에 저장했습니다" in page.message.text()
    page.deleteLater()


def test_company_selection_uses_one_direct_button_per_company() -> None:
    QApplication.instance() or QApplication([])
    page = OrganizationPage(Mock())
    selected: list[str] = []
    page.selected.connect(lambda organization: selected.append(organization.id))
    page._loaded([Organization("jmt", "JMT", "OWNER")])

    assert len(page.company_buttons) == 1
    assert page.company_buttons[0].text() == "JMT"
    assert page.company_buttons[0].parentWidget() is page.company_list
    assert not page.company_buttons[0].isWindow()
    page.company_buttons[0].click()
    assert selected == ["jmt"]
    page.deleteLater()


def test_company_choice_never_shows_as_an_independent_window() -> None:
    app = QApplication.instance() or QApplication([])
    page = OrganizationPage(Mock())
    probe = _CompanyChoiceShowProbe()
    app.installEventFilter(probe)
    try:
        page.show()
        app.processEvents()
        page._loaded([Organization("jmt", "JMT", "OWNER")])
        app.processEvents()
        assert probe.parents_at_show == [page.company_list]
        assert page.company_buttons[0].window() is page.window()
    finally:
        app.removeEventFilter(probe)
        page.close()
        page.deleteLater()


def test_employee_work_page_has_explicit_staff_refresh() -> None:
    QApplication.instance() or QApplication([])
    refreshed: list[bool] = []
    page = EmployeeWorkPage(Mock(query=lambda *_args: []), lambda _task_id: None, on_refresh_staff=lambda: refreshed.append(True))
    page.refresh_button.click()

    assert refreshed == [True]
    assert not page.refresh_button.isEnabled()
    page.staff_refresh_finished()
    assert page.refresh_button.isEnabled()
    page.deleteLater()


def test_company_management_cards_keep_compact_actions_on_the_right() -> None:
    QApplication.instance() or QApplication([])
    page = CompanyManagementPage(Organization("org", "회사", "OWNER"))
    buttons = {button.text(): button for button in page.findChildren(QPushButton)}
    assert buttons["직원·권한 관리"].width() == 156
    assert buttons["게스트 초대 관리"].width() == 156
    page.deleteLater()


def test_company_management_shows_selectable_join_code_and_copies_it() -> None:
    app = QApplication.instance() or QApplication([]); api = Mock(); api.company_join_code.return_value = "A2B3C"
    page = CompanyManagementPage(Organization("org", "회사", "OWNER"), api)
    page.load_join_code()

    assert page.join_code.text() == "A2B3C"
    assert page.join_code.isReadOnly()
    assert page.copy_join_code.isEnabled()
    page._copy_join_code()
    assert app.clipboard().text() == "A2B3C"
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
    monkeypatch.setattr(window.api, "staff_directory", lambda _organization_id: [])
    monkeypatch.setattr(window.api, "personal_schedules", lambda _organization_id: [])

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
    assert window.local_window.parentWidget() is window.stack
    assert window.local_window.windowType() == Qt.WindowType.Widget
    assert window.local_window not in QApplication.topLevelWidgets()
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
    monkeypatch.setattr(window.api, "staff_directory", lambda _organization_id: [])
    monkeypatch.setattr(window.api, "personal_schedules", lambda _organization_id: [])
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


def test_update_health_file_argument_is_read_only_when_complete(tmp_path):
    health = tmp_path / "health.ok"
    assert _update_health_file(["--update-health-file", str(health)]) == health
    assert _update_health_file(["--update-health-file"]) is None
    assert _update_health_file([]) is None
