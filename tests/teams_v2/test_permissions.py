from pathlib import Path

from PySide6.QtWidgets import QApplication

from event_checklist.ui.main_window import MainWindow
from eventflow_teams_v2.permissions import TeamsPermissionController
from eventflow_teams_v2.workspace import WorkspaceDatabase, workspace_database_path


def test_viewer_policy_blocks_local_editing_without_changing_local_ui(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    window = MainWindow(database, enable_update_check=False)

    policy = TeamsPermissionController(window, {"dashboard.view", "events.view", "checklist.view", "calendar.view"}, "VIEWER")
    policy.apply()

    assert not window.events.add_button.isEnabled()
    assert not window.events.bulk_assign_button.isEnabled()
    assert not window.events.table.editTriggers()
    assert not window.settlement.budget.isEnabled()
    assert not window.settings.tabs.isTabEnabled(0)
    assert not window.settings.tabs.isTabEnabled(1)
    window.close(); database.close()


def test_company_admin_policy_keeps_permitted_local_controls_active(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "user-a", "org-a"), user_id="user-a", organization_id="org-a")
    window = MainWindow(database, enable_update_check=False)
    permissions = {
        "events.create", "events.edit", "events.archive", "checklist.edit", "checklist.assign", "checklist.structure",
        "settlement.edit", "master_items.view", "master_items.edit", "contacts.view", "contacts.edit", "backup.create", "backup.restore", "exports.use",
    }

    TeamsPermissionController(window, permissions, "OWNER").apply()

    assert window.events.add_button.isEnabled()
    assert window.events.bulk_assign_button.isEnabled()
    assert window.settlement.budget.isEnabled()
    assert window.settings.tabs.isTabEnabled(0)
    assert window.settings.tabs.isTabEnabled(1)
    window.close(); database.close()


def test_guest_policy_keeps_only_allowed_project_reading_surface(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    database = WorkspaceDatabase(workspace_database_path(tmp_path, "guest", "org-a"), user_id="guest", organization_id="org-a")
    window = MainWindow(database, enable_update_check=False)
    TeamsPermissionController(window, {"dashboard.view", "events.view", "checklist.view"}, "GUEST").apply()

    assert not window.events.add_button.isEnabled()
    assert not window.events.bulk_assign_button.isEnabled()
    assert not window.settings.tabs.isTabEnabled(0)
    assert not window.settings.tabs.isTabEnabled(1)
    assert not window.settings.tabs.isTabEnabled(2)
    window.close(); database.close()
