from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from ..backup import create_backup, restore_backup
from .. import __version__
from ..config import install_dir
from ..install_service import current_executable, is_fixed_installation, is_packaged_app
from ..export import default_excel_filename, export_excel, next_available_excel_path
from .contacts_page import ContactsPage
from .excel_export_dialog import ExcelExportDialog
from .master_page import MasterPage


class SettingsPage(QWidget):
    restored = Signal()
    contacts_changed = Signal()

    def __init__(self, db, backup_directory: Path, parent=None):
        super().__init__(parent)
        self.db = db
        self.backup_directory = backup_directory
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 32)
        root.setSpacing(14)
        title = QLabel("설정")
        title.setObjectName("PageTitle")
        description = QLabel("프로젝트마다 공통으로 사용하는 기본 항목, 업체·담당자와 데이터를 관리합니다.")
        description.setObjectName("PageDescription")
        root.addWidget(title)
        root.addWidget(description)
        self.tabs = QTabWidget()
        self.master_page = MasterPage(db, embedded=True)
        self.contacts_page = ContactsPage(db, embedded=True)
        self.contacts_page.changed.connect(self.contacts_changed)
        self.tabs.addTab(self.master_page, "기본 항목")
        self.tabs.addTab(self.contacts_page, "업체 · 담당자")
        self.tabs.addTab(self._data_page(), "데이터 관리")
        self.tabs.addTab(self._about_page(), "앱 정보")
        root.addWidget(self.tabs, 1)

    def _data_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.addWidget(self._section("데이터 저장 위치", str(self.db.path), []))
        layout.addWidget(self._section("백업", "변경사항은 즉시 저장되며, 10분마다 전체 자동 백업을 만들고 최근 10개를 보관합니다. 수동 백업은 자동으로 삭제되지 않습니다.", [
            ("지금 백업", self.backup_now, True), ("백업에서 복원", self.restore_now, False),
        ]))
        layout.addWidget(self._section(
            "내보내기",
            "체크리스트 또는 정산내역을 PDF와 같은 디자인의 Excel 파일로 저장합니다.",
            [("Excel 내보내기", self.export_xlsx, True)],
        ))
        layout.addStretch()
        return page

    def _about_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.addWidget(self._section(
            "이벤트 플로우 · 이플",
            f"프로젝트 준비 체크리스트, 일정과 예산 배분을 한곳에서 관리하는 Windows 로컬 프로그램입니다.\n"
            f"버전 {__version__}\n설치 위치: "
            f"{current_executable().parent if is_packaged_app() and is_fixed_installation() else install_dir()}",
            [],
        ))
        layout.addWidget(self._section(
            "앱 업데이트",
            "앱을 시작할 때 GitHub 공개 릴리스를 확인합니다. 새 버전이 있으면 자동으로 내려받아 "
            "현재 설치 파일을 교체하고 다시 시작합니다. 프로젝트 데이터와 백업은 그대로 유지됩니다.",
            [],
        ))
        layout.addStretch()
        return page

    def _section(self, title_text, description_text, actions):
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        title = QLabel(title_text)
        title.setObjectName("SectionTitle")
        description = QLabel(description_text)
        description.setObjectName("Muted")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)
        if actions:
            row = QHBoxLayout()
            row.addStretch()
            for text, callback, primary in actions:
                button = QPushButton(text)
                if primary:
                    button.setProperty("primary", True)
                button.clicked.connect(callback)
                row.addWidget(button)
            layout.addLayout(row)
        return card

    def refresh(self):
        self.master_page.refresh()
        self.contacts_page.refresh()

    def backup_now(self):
        path, _ = QFileDialog.getSaveFileName(self, "백업 저장", str(self.backup_directory / "event_flow_backup.db"), "Database (*.db)")
        if path:
            result = create_backup(self.db, Path(path))
            QMessageBox.information(self, "백업 완료", f"백업을 저장했습니다.\n{result}")

    def restore_now(self):
        path, _ = QFileDialog.getOpenFileName(self, "백업 선택", str(self.backup_directory), "Database (*.db)")
        if not path:
            return
        answer = QMessageBox.warning(
            self, "복원 확인", "현재 데이터가 선택한 백업으로 교체됩니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            safety = create_backup(self.db, self.backup_directory)
            restore_backup(self.db, Path(path))
            QMessageBox.information(self, "복원 완료", f"복원 전 데이터는 다음 위치에 백업했습니다.\n{safety}")
            self.restored.emit()

    def export_xlsx(self):
        dialog = ExcelExportDialog(self.db, self)
        if not dialog.exec():
            return
        values = dialog.values()
        event = self.db.one("SELECT * FROM events WHERE id=?", (values["event_id"],))
        filename = default_excel_filename(
            event, values["kind"], values["options"], major=values["major"], minor=values["minor"],
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Excel 내보내기", filename, "Excel (*.xlsx)",
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if not path:
            return
        destination = Path(path)
        if destination.suffix.lower() != ".xlsx":
            destination = destination.with_suffix(".xlsx")
        destination = next_available_excel_path(destination)
        try:
            result = export_excel(
                self.db, destination, int(values["event_id"]), values["kind"], values["options"],
                values["major"], values["minor"],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Excel 내보내기 실패", f"Excel 파일을 만들지 못했습니다.\n\n{exc}")
            return
        QMessageBox.information(self, "내보내기 완료", f"Excel 파일을 저장했습니다.\n{result}")
