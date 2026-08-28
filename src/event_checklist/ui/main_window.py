from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QButtonGroup, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QMainWindow

from ..backup import create_manual_backup, create_rotating_auto_backup
from ..config import backup_dir
from .. import __version__
from ..services import EventService
from ..update_service import UpdateInfo, download_update, fetch_latest_release, is_packaged_app, launch_installer, version_tuple
from .calendar_page import CalendarPage
from .dashboard_page import DashboardPage
from .dialogs import EventDialog
from .events_page import EventsPage
from .settings_page import SettingsPage
from .settlement_page import SettlementPage
from .startup_splash import StartupSplash
from .title_bar import TitleBar, app_icon


class UpdateCheckThread(QThread):
    finished_with_result = Signal(object)
    failed = Signal(str)
    def run(self):
        try: self.finished_with_result.emit(fetch_latest_release())
        except Exception as exc: self.failed.emit(str(exc))


class UpdateDownloadThread(QThread):
    downloaded = Signal(object)
    failed = Signal(str)
    def __init__(self, info, parent=None): super().__init__(parent); self.info = info
    def run(self):
        try: self.downloaded.emit(download_update(self.info))
        except Exception as exc: self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self, db, parent=None, enable_update_check: bool = True):
        super().__init__(parent)
        self.db = db
        self.service = EventService(db)
        self.selected_event_id: int | None = None
        self.setWindowTitle("이벤트 플로우")
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(1440, 900)
        self.setMinimumSize(1120, 700)

        outer = QWidget(); outer.setObjectName("AppRoot")
        outer_layout = QVBoxLayout(outer); outer_layout.setContentsMargins(1, 1, 1, 1); outer_layout.setSpacing(0)
        self.title_bar = TitleBar(self); outer_layout.addWidget(self.title_bar)
        content = QWidget(); content_layout = QHBoxLayout(content); content_layout.setContentsMargins(0, 0, 0, 0); content_layout.setSpacing(0)
        self.sidebar = self._build_sidebar(); content_layout.addWidget(self.sidebar)
        self.stack = QStackedWidget(); content_layout.addWidget(self.stack, 1)
        outer_layout.addWidget(content, 1); self.setCentralWidget(outer)

        self.dashboard = DashboardPage(self.service)
        self.events = EventsPage(self.service, db)
        self.calendar = CalendarPage(self.service, db)
        self.settlement = SettlementPage(self.service, db)
        self.settings = SettingsPage(db, backup_dir())
        for page in [self.dashboard, self.events, self.calendar, self.settlement, self.settings]:
            self.stack.addWidget(page)

        self.dashboard.create_requested.connect(self.create_event)
        self.dashboard.event_selected.connect(self.select_event)
        self.dashboard.edit_requested.connect(self.edit_event)
        self.dashboard.delete_requested.connect(self.delete_event)
        self.dashboard.clear_requested.connect(lambda: self.select_event(None))
        self.events.edit_requested.connect(self.edit_event)
        self.events.changed.connect(self.refresh_dynamic)
        self.settlement.changed.connect(self.refresh_dynamic)
        self.calendar.changed.connect(self.refresh_dynamic)
        self.settings.contacts_changed.connect(self.refresh_dynamic)
        self.settings.restored.connect(lambda: self.select_event(None))
        self.title_bar.update_button.clicked.connect(self.install_available_update)
        self.available_update: UpdateInfo | None = None
        self.update_check_thread = None
        self.update_download_thread = None
        self.update_progress = None
        self.update_in_progress = False
        self.undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self.undo_shortcut.activated.connect(self.undo_last_change)
        self.redo_shortcut = QShortcut(QKeySequence.StandardKey.Redo, self)
        self.redo_shortcut.activated.connect(self.redo_last_change)
        self.auto_backup_timer = QTimer(self)
        self.auto_backup_timer.setInterval(10 * 60 * 1000)
        self.auto_backup_timer.timeout.connect(self._automatic_backup)
        self.auto_backup_timer.start()
        self.select_event(None)
        if is_packaged_app() and enable_update_check: QTimer.singleShot(700, self.check_updates)
        else: self.title_bar.set_update_status()

    def toggle_sidebar(self) -> None:
        self.set_sidebar_visible(not self.sidebar.isVisible())

    def set_sidebar_visible(self, visible: bool) -> None:
        self.sidebar.setVisible(visible)
        self.title_bar.set_sidebar_visible(visible)

    def _build_sidebar(self):
        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(212)
        layout = QVBoxLayout(sidebar); layout.setContentsMargins(16, 20, 16, 20); layout.setSpacing(8)
        self._sidebar_layout = layout
        title = QLabel("이플"); title.setObjectName("AppTitle")
        subtitle = QLabel("이벤트 플로우"); subtitle.setObjectName("Muted"); subtitle.setContentsMargins(8, 0, 0, 18)
        layout.addWidget(title); layout.addWidget(subtitle)
        names = ["대시보드", "체크리스트", "달력", "정산내역", "설정"]
        self.nav_group = QButtonGroup(sidebar); self.nav_group.setExclusive(True); self.nav_buttons = []
        self.global_menu = QWidget(sidebar); self.global_menu.setObjectName("SidebarGlobalMenu")
        self.global_menu_layout = QVBoxLayout(self.global_menu); self.global_menu_layout.setContentsMargins(0, 0, 0, 0); self.global_menu_layout.setSpacing(8)
        layout.addWidget(self.global_menu)
        self.global_separator = QFrame(); self.global_separator.setFrameShape(QFrame.Shape.HLine); self.global_separator.setObjectName("SidebarSeparator"); layout.addWidget(self.global_separator)
        self.project_menu = QWidget(sidebar); self.project_menu.setObjectName("SidebarProjectMenu")
        self.project_menu_layout = QVBoxLayout(self.project_menu); self.project_menu_layout.setContentsMargins(0, 0, 0, 0); self.project_menu_layout.setSpacing(8)
        for index, name in enumerate(names[:4]):
            button = QPushButton(name); button.setCheckable(True); button.setProperty("nav", True)
            button.clicked.connect(lambda _checked=False, value=index: self._navigate(value))
            self.nav_group.addButton(button, index); self.nav_buttons.append(button); self.project_menu_layout.addWidget(button)
        layout.addWidget(self.project_menu)
        self.project_separator = QFrame(); self.project_separator.setFrameShape(QFrame.Shape.HLine); self.project_separator.setObjectName("SidebarSeparator"); layout.addWidget(self.project_separator)
        layout.addStretch()
        self.company_menu = QWidget(sidebar); self.company_menu.setObjectName("SidebarCompanyMenu")
        self.company_menu_layout = QVBoxLayout(self.company_menu); self.company_menu_layout.setContentsMargins(0, 0, 0, 0); self.company_menu_layout.setSpacing(8)
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("SidebarSaveButton")
        self.save_button.setToolTip("현재 전체 데이터를 복구용 저장본으로 보관")
        self.save_button.clicked.connect(self.save_full_backup)
        self.company_menu_layout.addWidget(self.save_button)
        settings = QPushButton(names[4]); settings.setCheckable(True); settings.setProperty("nav", True)
        settings.clicked.connect(lambda _checked=False: self._navigate(4))
        self.nav_group.addButton(settings, 4); self.nav_buttons.append(settings); self.company_menu_layout.addWidget(settings)
        layout.addWidget(self.company_menu)
        return sidebar

    def install_teams_staff_page(self, page) -> None:
        """Append a V2-only company work board without changing Local routes."""
        if hasattr(self, "staff_work_page"):
            return
        self.staff_work_page = page
        index = self.stack.count()
        self.stack.addWidget(page)
        button = QPushButton("직원업무"); button.setCheckable(True); button.setProperty("nav", True)
        button.clicked.connect(lambda _checked=False, value=index: self._navigate(value))
        self.nav_group.addButton(button, index); self.nav_buttons.append(button)
        self.global_menu_layout.addWidget(button)

    def add_company_global_nav_button(self, button: QPushButton) -> None:
        """Place company-wide routes above project routes and keep one active route."""
        button.setCheckable(True); button.setProperty("nav", True)
        self.nav_group.addButton(button)
        self.global_menu_layout.addWidget(button)

    def add_company_management_nav_button(self, button: QPushButton) -> None:
        """Company administration remains the last navigation control."""
        button.setCheckable(True); button.setProperty("nav", True)
        self.nav_group.addButton(button)
        self.company_menu_layout.addWidget(button)

    def open_teams_task(self, task_id: int) -> None:
        row = self.db.one("SELECT event_id FROM event_tasks WHERE id=?", (task_id,))
        if not row:
            return
        self.select_event(int(row["event_id"]))
        self.nav_buttons[1].click()

    def save_full_backup(self) -> None:
        try:
            result = create_manual_backup(self.db, backup_dir())
            self.db.mark_backed_up()
        except Exception as exc:
            QMessageBox.critical(self, "저장 실패", f"전체 데이터를 저장하지 못했습니다.\n\n{exc}")
            return
        QMessageBox.information(self, "저장 완료", f"현재 전체 데이터를 저장했습니다.\n{result}")

    def _automatic_backup(self) -> None:
        if not self.db.is_dirty:
            return
        try:
            create_rotating_auto_backup(self.db, backup_dir(), keep=10)
        except Exception:
            return
        self.db.mark_backed_up()

    def undo_last_change(self) -> None:
        if self.db.undo():
            self._refresh_after_history_change()

    def redo_last_change(self) -> None:
        if self.db.redo():
            self._refresh_after_history_change()

    def _refresh_after_history_change(self) -> None:
        current_index = self.stack.currentIndex()
        event_id = self.selected_event_id
        if event_id and not self.service.get_event(event_id):
            event_id = None
        self.selected_event_id = event_id
        event = self.service.get_event(event_id) if event_id else None
        for index in (1, 2, 3):
            self.nav_buttons[index].setEnabled(bool(event))
        self.title_bar.set_event_name(event["name"] if event else None)
        self.events.event_id = event_id; self.events.invalidate()
        self.calendar.event_id = event_id
        self.settlement.event_id = event_id; self.settlement.invalidate()
        self.dashboard.set_event(event_id)
        if not event:
            current_index = 0
        if current_index == 1: self.events.set_event(event_id)
        elif current_index == 2: self.calendar.set_event(event_id)
        elif current_index == 3: self.settlement.set_event(event_id)
        elif current_index == 4: self.settings.refresh()
        self.nav_buttons[current_index].setChecked(True)
        self.stack.setCurrentIndex(current_index)

    def _navigate(self, index):
        if index in (1, 2, 3) and not self.selected_event_id:
            return
        if self.stack.currentIndex() == index:
            return
        self.stack.setCurrentIndex(index)
        if index == 0: self.dashboard.set_event(self.selected_event_id)
        elif index == 1: self.events.set_event(self.selected_event_id)
        elif index == 2: self.calendar.set_event(self.selected_event_id)
        elif index == 3: self.settlement.set_event(self.selected_event_id)
        elif index == 4: self.settings.refresh()
        elif hasattr(self, "staff_work_page") and self.stack.widget(index) is self.staff_work_page: self.staff_work_page.refresh()

    def select_event(self, event_id: int | None):
        event = self.service.get_event(event_id) if event_id else None
        previous_event_id = self.selected_event_id
        self.selected_event_id = int(event_id) if event else None
        for index in (1, 2, 3): self.nav_buttons[index].setEnabled(bool(event))
        self.title_bar.set_event_name(event["name"] if event else None)
        self.dashboard.set_event(self.selected_event_id)
        # 선택 직후에는 대시보드만 그린다. 나머지 무거운 화면은 해당 메뉴를
        # 처음 눌렀을 때 로드해 행사 선택 응답을 즉시 유지한다.
        if previous_event_id != self.selected_event_id:
            self.events.event_id = self.selected_event_id
            self.events.invalidate()
            self.calendar.event_id = self.selected_event_id
            self.settlement.event_id = self.selected_event_id
            if self.selected_event_id:
                QTimer.singleShot(50, lambda eid=self.selected_event_id: self._preload_checklist(eid))
                QTimer.singleShot(250, lambda eid=self.selected_event_id: self._preload_settlement(eid))
        self.nav_buttons[0].setChecked(True); self.stack.setCurrentIndex(0)

    def _preload_checklist(self, event_id: int) -> None:
        """Build the selected checklist while the dashboard is visible."""
        if self.selected_event_id == event_id and self.events._loaded_event_id != event_id:
            self.events.set_event(event_id)

    def _preload_settlement(self, event_id: int) -> None:
        if self.selected_event_id == event_id and self.settlement._loaded_event_id != event_id:
            self.settlement.set_event(event_id)

    def _contacts_for_event_dialog(self):
        vendors = self.db.query("SELECT * FROM contacts WHERE kind='VENDOR' ORDER BY name")
        freelancers = self.db.query("SELECT * FROM contacts WHERE kind='PERSON' AND company_id IS NULL ORDER BY name")
        return vendors, freelancers

    def create_event(self):
        masters = self.db.query("SELECT * FROM master_items ORDER BY sort_order")
        vendors, freelancers = self._contacts_for_event_dialog()
        dialog = EventDialog(
            masters, vendors=vendors, freelancers=freelancers,
            previous_events=self.service.list_events(), previous_task_loader=self.service.list_tasks,
            parent=self,
        )
        if not dialog.exec(): return
        import_values = dialog.import_values()
        try:
            event_id = self.service.create_event(**dialog.values(),
                                                 selected_master_ids=[] if import_values else dialog.selected_ids(),
                                                 vendor_ids=dialog.selected_vendor_ids(),
                                                 freelancer_ids=dialog.selected_freelancer_ids(),
                                                 **import_values)
        except Exception as exc:
            QMessageBox.critical(self, "행사 생성 실패", str(exc)); return
        self.select_event(event_id); self.nav_buttons[1].click()

    def edit_event(self, event_id):
        event = self.service.get_event(event_id)
        if not event: return
        vendors, freelancers = self._contacts_for_event_dialog()
        participants = self.service.event_participants(event_id)
        dialog = EventDialog([], event=event, vendors=vendors, freelancers=freelancers,
                             selected_vendor_ids=[row["id"] for row in participants["vendors"]],
                             selected_freelancer_ids=[row["id"] for row in participants["freelancers"]], parent=self)
        if not dialog.exec(): return
        try:
            with self.db.history_action():
                self.service.update_event(event_id, **dialog.values(), rebase_auto=True)
                self.service.set_event_participants(event_id, dialog.selected_vendor_ids(), dialog.selected_freelancer_ids())
        except Exception as exc:
            QMessageBox.critical(self, "행사 수정 실패", str(exc)); return
        self.events.invalidate()
        self.settlement.invalidate()
        self.select_event(event_id)
        QTimer.singleShot(0, lambda eid=event_id: self._preload_checklist(eid))
        QTimer.singleShot(30, lambda eid=event_id: self._preload_settlement(eid))

    def delete_event(self, event_id):
        event = self.service.get_event(event_id)
        if not event: return
        answer = QMessageBox.warning(
            self, "행사 삭제 확인", f"'{event['name']}' 행사와 체크리스트를 삭제할까요?\n삭제 전에 필요한 경우 데이터 관리에서 백업하세요.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.service.delete_event(event_id); self.select_event(None)

    def refresh_dynamic(self, _event_id=0):
        if not self.selected_event_id: return
        # 보이지 않는 화면까지 즉시 다시 만드는 대신 다음 메뉴 진입 때 최신
        # 데이터를 읽는다. 현재 화면은 각 페이지가 변경 직후 자체 갱신한다.
        sender = self.sender()
        if sender is not self.events:
            self.events.invalidate()
            QTimer.singleShot(0, lambda eid=self.selected_event_id: self._preload_checklist(eid))
        if sender is not self.settlement:
            self.settlement.invalidate()
            QTimer.singleShot(30, lambda eid=self.selected_event_id: self._preload_settlement(eid))

    def refresh_all(self, event_id=None): self.select_event(event_id)

    def check_updates(self):
        if self.update_check_thread and self.update_check_thread.isRunning(): return
        self.title_bar.set_update_checking()
        self.update_check_thread = UpdateCheckThread(self)
        self.update_check_thread.finished_with_result.connect(self._update_check_finished)
        self.update_check_thread.failed.connect(self._update_check_failed)
        self.update_check_thread.start()

    def _update_check_failed(self, message):
        self.available_update = None
        self.title_bar.set_update_error(message)
        QMessageBox.warning(self, "업데이트 확인 실패", message)

    def _update_check_finished(self, info):
        update_available = bool(info and version_tuple(info.version) > version_tuple(__version__))
        self.available_update = info if update_available else None
        self.title_bar.set_update_status(info, update_available)
        if update_available:
            QTimer.singleShot(250, self.install_available_update)

    def install_available_update(self):
        if self.update_in_progress:
            return
        info = self.available_update
        if not info:
            self.check_updates()
            return
        if not info.asset_url:
            message = (
                f"새 버전 {info.version}은 공개되어 있지만 자동 업데이트를 설치할 수 없습니다.\n\n"
                "확인된 원인\nGitHub Release에 EventFlow-Windows.zip 파일이 없습니다.\n\n"
                "확인 방법\n해당 Release에 Windows ZIP 파일을 첨부한 뒤 다시 확인하세요.\n\n"
                f"Release 주소: {info.release_url}"
            )
            self.title_bar.set_update_error(message)
            QMessageBox.warning(self, "업데이트 파일 누락", message)
            return
        self.update_in_progress = True
        self.setEnabled(False)
        self.update_progress = StartupSplash()
        self.update_progress.setWindowTitle("이플 업데이트")
        self.update_progress.show()
        self.update_progress.set_status(f"새 버전 {info.version}을 내려받고 있습니다…")
        self.update_download_thread = UpdateDownloadThread(info, self)
        self.update_download_thread.downloaded.connect(self._update_downloaded)
        self.update_download_thread.failed.connect(self._update_failed)
        self.update_download_thread.start()

    def _update_downloaded(self, archive):
        if self.update_progress:
            self.update_progress.set_status("설치를 준비하고 있습니다. 잠시 후 자동으로 다시 시작합니다…")
        try: launch_installer(archive, self.available_update, os.getpid())
        except Exception as exc:
            self._update_failed(str(exc)); return
        QTimer.singleShot(700, QApplication.quit)

    def _update_failed(self, message):
        if self.update_progress:
            self.update_progress.close()
            self.update_progress = None
        self.update_in_progress = False
        self.setEnabled(True)
        QMessageBox.critical(self, "업데이트 실패", message)

    def closeEvent(self, event):
        self._automatic_backup()
        super().closeEvent(event)

    def nativeEvent(self, event_type, message):
        if event_type == b"windows_generic_MSG" and not self.isMaximized():
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:  # WM_NCHITTEST
                point = self.mapFromGlobal(self.cursor().pos()); border = 7
                left, right = point.x() < border, point.x() >= self.width() - border
                top, bottom = point.y() < border, point.y() >= self.height() - border
                hit = 0
                if top and left: hit = 13
                elif top and right: hit = 14
                elif bottom and left: hit = 16
                elif bottom and right: hit = 17
                elif left: hit = 10
                elif right: hit = 11
                elif top: hit = 12
                elif bottom: hit = 15
                if hit: return True, hit
        return super().nativeEvent(event_type, message)
