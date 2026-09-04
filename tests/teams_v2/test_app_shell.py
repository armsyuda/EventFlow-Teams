from pathlib import Path
import time
from types import SimpleNamespace
from unittest.mock import Mock

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton, QTableWidgetItem, QWidget
from PySide6.QtTest import QTest

from event_checklist.ui.main_window import MainWindow
from eventflow_teams_v2.api import Organization
from eventflow_teams_v2.app import _update_health_file
from eventflow_teams_v2.app import CompanyManagementPage, CompanyMembersPage, OrganizationPage, TeamsV2Window
from eventflow_teams_v2.company_pages import CompanyCalendarPage
from eventflow_teams_v2.notification_page import NotificationPage
from eventflow_teams_v2.company_workspace import CompanyWorkspace
from eventflow_teams_v2.my_space_page import MySpacePage
from eventflow_teams_v2.staff_pages import EmployeeWorkPage
from eventflow_teams_v2.config import TeamsV2Config
from eventflow_teams_v2.session import Session
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path
from eventflow_teams_v2.work_card import WorkCard


def test_unified_work_card_opens_detail_from_the_whole_card() -> None:
    app=QApplication.instance() or QApplication([]); opened=[]
    card=WorkCard({"id":"task-a","name":"현장 확인","work_kind":"CHECKLIST","status":"미착수"},open_detail=lambda task:opened.append(task["id"]),drag_payload=None)
    card.resize(320,100); card.show(); app.processEvents(); QTest.mouseDClick(card,Qt.MouseButton.LeftButton); app.processEvents()
    assert opened==["task-a"]
    assert not any(label.text()=="더블클릭하여 상세 보기" for label in card.findChildren(QLabel))
    card.close(); card.deleteLater()


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


def test_company_member_removal_requires_confirmation_and_preserves_the_account(monkeypatch) -> None:
    QApplication.instance() or QApplication([])
    api = Mock(); api.session = Session("token", "refresh", "owner")
    page = CompanyMembersPage(api, Organization("org", "회사", "OWNER"))
    member = {"user_id": "member", "display_name": "직원", "email": "member@example.com", "role": "MEMBER", "status": "ACTIVE", "overrides": []}
    page.members = [member]; api.company_members.return_value = []
    page.table.setRowCount(1); page._select_row(0, 0)

    assert page.remove.isEnabled()
    assert "업무 이력" in page.remove.toolTip()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes)
    page.remove_member()

    api.remove_company_member.assert_called_once_with("org", "member")
    assert "계정과 기존 업무 이력은 보존" in page.message.text()
    page.deleteLater()


def test_company_member_removal_never_enables_for_an_owner() -> None:
    QApplication.instance() or QApplication([])
    api = Mock(); api.session = Session("token", "refresh", "owner")
    page = CompanyMembersPage(api, Organization("org", "회사", "OWNER"))
    page.members = [{"user_id": "owner-b", "display_name": "대표", "email": "owner@example.com", "role": "OWNER", "status": "ACTIVE", "overrides": []}]
    page.table.setRowCount(1); page._select_row(0, 0)

    assert not page.remove.isEnabled()
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


def test_refresh_all_keeps_the_current_checklist_page(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    event_id = database.conn.execute("INSERT INTO events(name,start_date) VALUES(?,?)", ("프로젝트", "2026-09-04")).lastrowid
    database.conn.commit()
    window = MainWindow(database, enable_update_check=False)
    window.select_event(event_id)
    window.nav_buttons[1].click()

    assert window.stack.currentWidget() is window.events
    window.refresh_all(event_id)

    assert window.selected_event_id == event_id
    assert window.stack.currentWidget() is window.events
    assert window.nav_buttons[1].isChecked()
    window.close(); database.close()


def test_member_assignment_refreshes_dependents_without_leaving_checklist(tmp_path: Path) -> None:
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    CompanyWorkspace(database)
    event_id = database.conn.execute("INSERT INTO events(name,start_date) VALUES(?,?)", ("프로젝트", "2026-09-04")).lastrowid
    task_id = database.conn.execute("INSERT INTO event_tasks(event_id,major,minor,name,status,sort_order) VALUES(?,?,?,?,?,?)", (event_id, "운영", "일반", "업무", "미착수", 1)).lastrowid
    database.conn.execute("INSERT INTO teams_v2_entity_map(entity_type,local_id,remote_id,remote_version) VALUES(?,?,?,?)", ("EVENT_TASK", task_id, "remote-task", 1))
    database.conn.commit()
    saved = {"id": "remote-task", "event_id": "remote-event", "work_scope": "PROJECT", "work_kind": "CHECKLIST", "major": "운영", "minor": "일반", "name": "업무", "status": "미착수", "assigned_member_user_id": "staff-b", "row_version": 2}
    local_window = Mock(); local_window.staff_work_page = Mock()
    shell = SimpleNamespace(
        current_organization=SimpleNamespace(id="org-a"), workspace_db=database,
        company_workspace=CompanyWorkspace(database), api=Mock(assign_task_member=Mock(return_value=saved)),
        local_window=local_window, company_calendar_page=Mock(), my_space_page=Mock(), _show_toast=Mock(),
    )
    task = dict(database.one("SELECT * FROM event_tasks WHERE id=?", (task_id,)))

    assert TeamsV2Window._save_task_member(shell, task, "staff-b", transfer=False)
    local_window.refresh_all.assert_not_called()
    local_window.staff_work_page.refresh.assert_called_once()
    shell.company_calendar_page.refresh.assert_called_once()
    shell.my_space_page.refresh.assert_called_once()
    assert database.one("SELECT assigned_member_user_id FROM event_tasks WHERE id=?", (task_id,))["assigned_member_user_id"] == "staff-b"
    database.close()


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


def test_company_calendar_hides_personal_schedules_for_a_selected_project(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    CompanyWorkspace(database)
    event_id = database.conn.execute(
        "INSERT INTO events(name,start_date) VALUES(?,?)", ("선택 프로젝트", "2026-08-01")
    ).lastrowid
    database.conn.execute(
        "INSERT INTO teams_v2_entity_map(entity_type,local_id,remote_id) VALUES('EVENT',?,?)", (event_id, "project-a")
    )
    database.conn.execute(
        "INSERT INTO teams_v3_work_items(remote_id,event_id,work_scope,major,minor,name,status,planned_start,due_date) VALUES(?,?,?,?,?,?,?,?,?)",
        ("work-a", "project-a", "PROJECT", "운영", "일반", "프로젝트 업무", "미착수", "2026-08-10", "2026-08-11"),
    )
    database.conn.execute(
        "INSERT INTO teams_v2_personal_schedules(id,member_user_id,start_date,end_date,title) VALUES(?,?,?,?,?)",
        ("personal-a", "staff-a", "2026-08-10", "2026-08-11", "개인 휴가"),
    )
    database.conn.commit()
    page = CompanyCalendarPage(database)

    assert [schedule["title"] for schedule in page.timeline.personal_schedules] == ["개인 휴가"]
    page.project.setCurrentIndex(page.project.findData("project-a"))

    assert [task["name"] for task in page.timeline.tasks] == ["프로젝트 업무"]
    assert page.timeline.personal_schedules == []
    assert not page.personal.isEnabled()
    assert page.personal.text() == "개인 일정 제외"

    page.project.setCurrentIndex(page.project.findData("__COMPANY__"))
    assert [schedule["title"] for schedule in page.timeline.personal_schedules] == ["개인 휴가"]
    assert page.personal.isEnabled()
    page.deleteLater(); database.close()


def test_company_calendar_task_card_shows_assignee_name(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database=WorkspaceDatabase(workspace_database_path(tmp_path,"user-a","org-a"),user_id="user-a",organization_id="org-a"); CompanyWorkspace(database)
    page=CompanyCalendarPage(database)
    card=page._task_card({"name":"현장 준비","major":"운영","status":"미착수","work_scope":"PROJECT","event_id":None,"member_name":"김담당"})
    assert any("담당자 · 김담당" in label.text() for label in card.findChildren(QLabel))
    page.deleteLater(); database.close()


def test_notification_page_keeps_history_and_supports_unread_filter() -> None:
    QApplication.instance() or QApplication([]); calls=[]
    notices=[{"id":"n1","title":"업무 변경","message":"마감일을 변경했습니다.","project_name":"행사 A","created_at":"2026-09-04T10:00:00+09:00","read_at":None}]
    page=NotificationPage(lambda unread:(calls.append(unread) or notices),lambda _id:True,lambda _id:True,lambda _notice:None)
    page.refresh(); assert page.list.count()==1 and "업무 변경" in page.list.itemWidget(page.list.item(0)).findChildren(QLabel)[0].text()
    page.unread.setChecked(True); assert calls[-1] is True
    page.deleteLater()


def test_my_space_unifies_company_and_project_work_without_a_duplicate_work_list(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    CompanyWorkspace(database)
    database.conn.executemany(
        "INSERT INTO teams_v3_work_items(remote_id,event_id,work_scope,work_kind,major,minor,name,status,planned_start,due_date,assigned_member_user_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("company-own", None, "COMPANY", "COMPANY_SELF", "사내 업무", "일반", "내 사내 업무", "미착수", "2026-08-10", "2026-08-11", "user-a", "user-a"),
            ("company-other", None, "COMPANY", "COMPANY_SELF", "사내 업무", "일반", "동료 사내 업무", "진행중", "2026-08-10", "2026-08-11", "user-b", "user-b"),
            ("project-work", "project-a", "PROJECT", "PROJECT_ADDITIONAL", "프로젝트 추가 업무", "일반", "프로젝트 업무", "미착수", "2026-08-10", "2026-08-11", "user-a", "user-a"),
        ],
    )
    database.conn.commit()
    page = MySpacePage(
        database, "user-a", lambda _values, _schedule_id=None: True, lambda _item: True,
        lambda _items: None, lambda _items: None, lambda _id, _values: True,
        lambda _values, _work: True, lambda _work: True,
        lambda _values, _work: True, lambda _work: True, lambda _checklist: True,
    )
    page.refresh()

    assert page.management_stack.currentWidget() is page.work_panel
    page.schedule_tab.click()
    assert page.management_stack.currentWidget() is page.schedule_panel
    page.work_tab.click()
    assert page.management_stack.currentWidget() is page.work_panel
    task_labels = [label.text() for label in page.tasks.findChildren(QLabel)]
    assert "내 사내 업무" in task_labels and "동료 사내 업무" not in task_labels
    assert "프로젝트 업무" in task_labels
    assert not hasattr(page, "company_work")
    assert not hasattr(page, "company_category")
    assert [page.checklist_scope.text(), page.project_scope.text(), page.company_scope.text()] == ["체크리스트 업무", "프로젝트 추가 업무", "사내 업무"]
    assert "background:#FFFFFF" in page.scope_tabs.styleSheet()
    assert "border:1px solid #AAB8C8" in page.scope_tabs.styleSheet()
    assert "QFrame#WorkScopeTabs { background:transparent; border:none; }" in page.scope_tabs.styleSheet()
    assert page.scope_tabs.layout().contentsMargins().left() == 0
    assert "QPushButton:checked" in page.scope_tabs.styleSheet()
    assert page._work_scope is None
    assert not page.work_submit.isEnabled()
    assert not any(button.isChecked() for button in (page.checklist_scope, page.project_scope, page.company_scope))
    assert page.project_field.isHidden() and page.checklist_field.isHidden() and page.work_details.isHidden()
    page.checklist_scope.click()
    assert page.work_submit.isEnabled()
    assert not page.project_field.isHidden() and not page.checklist_field.isHidden() and page.work_details.isHidden()
    page.company_scope.click()
    assert page.project_field.isHidden() and page.checklist_field.isHidden() and not page.work_details.isHidden()
    page._clear_work_form()
    assert page._work_scope is None and not page.work_submit.isEnabled()
    assert not any(button.isChecked() for button in (page.checklist_scope, page.project_scope, page.company_scope))
    page.deleteLater(); database.close()


def test_employee_work_cards_include_all_three_work_kinds(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    CompanyWorkspace(database)
    database.conn.execute(
        "INSERT INTO teams_v2_staff_members(user_id,display_name,role,status,color_hex) VALUES(?,?,?,?,?)",
        ("user-a", "직원 A", "MEMBER", "ACTIVE", "#A7D4F0"),
    )
    database.conn.executemany(
        "INSERT INTO teams_v3_work_items(remote_id,event_id,work_scope,work_kind,major,minor,name,status,assigned_member_user_id) VALUES(?,?,?,?,?,?,?,?,?)",
        [
            ("checklist", "project-a", "PROJECT", "CHECKLIST", "운영", "일반", "체크 업무", "미착수", "user-a"),
            ("additional", "project-a", "PROJECT", "PROJECT_ADDITIONAL", "추가", "일반", "추가 업무", "진행중", "user-a"),
            ("company", None, "COMPANY", "COMPANY_SELF", "사내 업무", "일반", "사내 업무", "미착수", "user-a"),
        ],
    )
    database.conn.commit()
    page = EmployeeWorkPage(database, lambda _task_id: None, current_user_id="user-a")
    page.refresh()

    active = page._member_work("user-a", completed=False)
    assert {row["work_kind"] for row in active} == {"CHECKLIST", "PROJECT_ADDITIONAL", "COMPANY_SELF"}
    labels = [label.text() for label in page.findChildren(QLabel)]
    assert any("체크리스트 업무" in text for text in labels)
    assert any("프로젝트 추가 업무" in text for text in labels)
    assert any("사내 업무" in text for text in labels)
    page.deleteLater(); database.close()


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
    assert window.local_window.nav_buttons[2].text() == "달력"
    assert window.local_window.nav_buttons[2].isHidden()
    assert window.company_calendar_page is not None
    assert not any(button.text() == "사내 업무" and button.property("nav") for button in window.local_window.findChildren(QPushButton))
    assert any(button.text() == "전체 달력" and not button.isHidden() for button in window.local_window.findChildren(QPushButton))
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
