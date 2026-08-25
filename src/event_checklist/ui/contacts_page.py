from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .dialogs import ContactDialog
from .widgets import FastEditableTable, configure_data_table, fit_table_to_view


class ContactsPage(QWidget):
    changed = Signal()

    def __init__(self, db, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.db = db
        root = QVBoxLayout(self)
        root.setContentsMargins(12 if embedded else 32, 12 if embedded else 28, 12 if embedded else 32, 12 if embedded else 32)
        root.setSpacing(14)
        if not embedded:
            title = QLabel("업체 · 담당자")
            title.setObjectName("PageTitle")
            root.addWidget(title)
        guide = QLabel("업체를 선택하면 해당 업체 소속 담당자를 관리할 수 있습니다. 소속이 없는 사람은 프리랜서에 등록하세요.")
        guide.setObjectName("InfoGuide")
        guide.setWordWrap(True)
        root.addWidget(guide)
        tabs = QTabWidget()
        tabs.addTab(self._companies_tab(), "업체별 담당자")
        tabs.addTab(self._freelancers_tab(), "프리랜서")
        root.addWidget(tabs, 1)
        self.refresh()

    def _table(self, headers, widths):
        table = FastEditableTable(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        configure_data_table(table, widths)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(
            lambda row, column, source=table: self._open_contact_editor(source, row, column)
        )
        return table

    def _open_contact_editor(self, table, row: int, column: int):
        cell = table.item(row, column)
        if cell is None:
            return
        item_id = int(cell.data(Qt.ItemDataRole.UserRole))
        if table is self.vendor_table:
            fields = {0: "name", 1: "role_note"}
        else:
            fields = {0: "name", 1: "job_title", 2: "phone", 3: "role_note"}
        field = fields.get(column)
        if field is None:
            return

        def commit(value):
            if field == "name" and not value:
                QMessageBox.warning(self, "입력 확인", "이름은 비워둘 수 없습니다.")
                return False
            try:
                self.db.execute(f"UPDATE contacts SET {field}=? WHERE id=?", (value, item_id))
            except Exception as exc:
                QMessageBox.warning(self, "수정 실패", f"연락처를 수정하지 못했습니다.\n\n{exc}")
                return False
            cell.setText(value)
            self.changed.emit()

        table.open_text_editor(row, column, cell.text(), commit)

    def _companies_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QHBoxLayout()
        add_vendor = QPushButton("+ 업체 추가")
        add_vendor.setProperty("primary", True)
        delete_vendor = QPushButton("업체 삭제")
        delete_vendor.setProperty("danger", True)
        add_person = QPushButton("+ 소속 담당자 추가")
        actions.addWidget(add_vendor)
        actions.addWidget(delete_vendor)
        actions.addStretch()
        actions.addWidget(add_person)
        layout.addLayout(actions)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.vendor_table = self._table(["업체명", "업종"], [240, 310])
        self.company_people = self._table(["담당자", "직책", "연락처", "역할"], [150, 130, 160, 220])
        splitter.addWidget(self.vendor_table)
        splitter.addWidget(self.company_people)
        splitter.setSizes([520, 620])
        layout.addWidget(splitter, 1)
        self.vendor_table.itemSelectionChanged.connect(self._refresh_company_people)
        add_vendor.clicked.connect(lambda: self.add_contact("VENDOR"))
        delete_vendor.clicked.connect(lambda: self.delete_selected(self.vendor_table, "VENDOR"))
        add_person.clicked.connect(self.add_company_person)
        return page

    def _freelancers_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        actions = QHBoxLayout()
        actions.addStretch()
        fit = QPushButton("열 너비 맞춤")
        add = QPushButton("+ 프리랜서 추가")
        add.setProperty("primary", True)
        delete = QPushButton("선택 삭제")
        delete.setProperty("danger", True)
        actions.addWidget(delete)
        actions.addWidget(fit)
        actions.addWidget(add)
        layout.addLayout(actions)
        self.freelancer_table = self._table(["이름", "직책", "연락처", "역할"], [190, 150, 190, 310])
        layout.addWidget(self.freelancer_table, 1)
        add.clicked.connect(lambda: self.add_contact("PERSON", None))
        delete.clicked.connect(lambda: self.delete_selected(self.freelancer_table, "PERSON"))
        fit.clicked.connect(lambda: fit_table_to_view(self.freelancer_table))
        return page

    def refresh(self):
        vendors = self.db.query("SELECT * FROM contacts WHERE kind='VENDOR' ORDER BY name")
        self._fill(self.vendor_table, vendors, vendor=True)
        freelancers = self.db.query("SELECT * FROM contacts WHERE kind='PERSON' AND company_id IS NULL ORDER BY name")
        self._fill(self.freelancer_table, freelancers)
        if vendors and self.vendor_table.currentRow() < 0:
            self.vendor_table.selectRow(0)
        self._refresh_company_people()

    def _fill(self, table, rows, *, vendor: bool = False):
        table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            values = [item["name"], item["role_note"]] if vendor else [
                item["name"], item["job_title"], item["phone"], item["role_note"],
            ]
            for c, value in enumerate(values):
                cell = QTableWidgetItem(value or "")
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                table.setItem(r, c, cell)
            table.setRowHeight(r, 42)

    def _selected_vendor_id(self):
        row = self.vendor_table.currentRow()
        return self.vendor_table.item(row, 0).data(Qt.ItemDataRole.UserRole) if row >= 0 else None

    def _refresh_company_people(self):
        vendor_id = self._selected_vendor_id()
        rows = self.db.query("SELECT * FROM contacts WHERE kind='PERSON' AND company_id=? ORDER BY name", (vendor_id,)) if vendor_id else []
        self._fill(self.company_people, rows)

    def add_contact(self, kind: str, company_id=None):
        dialog = ContactDialog(kind, self)
        if not dialog.exec():
            return
        values = dialog.values()
        try:
            self.db.execute(
                "INSERT INTO contacts(kind,name,phone,job_title,role_note,company_id) VALUES (?,?,?,?,?,?)",
                (kind, values["name"], values["phone"], values["job_title"], values["role_note"], company_id),
            )
        except Exception as exc:
            QMessageBox.warning(self, "추가 실패", f"연락처를 추가하지 못했습니다.\n\n{exc}")
            return
        self.refresh()
        self.changed.emit()

    def add_company_person(self):
        vendor_id = self._selected_vendor_id()
        if not vendor_id:
            QMessageBox.information(self, "업체 선택", "담당자를 추가할 업체를 먼저 선택하세요.")
            return
        self.add_contact("PERSON", vendor_id)

    def delete_selected(self, table, kind):
        row = table.currentRow()
        if row < 0:
            return
        item_id = table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        name = table.item(row, 0).text()
        if QMessageBox.question(self, "삭제 확인", f"'{name}'을(를) 삭제할까요?") == QMessageBox.StandardButton.Yes:
            self.db.execute("DELETE FROM contacts WHERE id=? AND kind=?", (item_id, kind))
            self.refresh()
            self.changed.emit()
