from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .dialogs import MasterItemDialog
from .widgets import (
    GROUP_MAJOR_ROLE, GROUP_MINOR_ROLE, FastEditableTable, configure_editable_table,
    fit_table_to_view,
)
from ..choices import load_master_choice_catalog


class MasterPage(QWidget):
    def __init__(self, db, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.db = db
        self.loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(12 if embedded else 32, 12 if embedded else 28, 12 if embedded else 32, 12 if embedded else 32)
        root.setSpacing(16)
        title = QLabel("기본 항목")
        title.setObjectName("PageTitle")
        description = QLabel("새 프로젝트에 복사될 기본 업무를 관리합니다. 기존 프로젝트는 바뀌지 않습니다.")
        description.setObjectName("PageDescription")
        if not embedded:
            root.addWidget(title)
            root.addWidget(description)
        top = QHBoxLayout()
        self.toolbar_layout = top
        self.search = QLineEdit()
        self.search.setPlaceholderText("분류·항목·세부내용 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        self.add_button = QPushButton("+ 항목 추가")
        self.add_button.setProperty("primary", True)
        self.add_button.setFixedWidth(124)
        self.add_button.clicked.connect(self.add_item)
        self.edit_button = QPushButton("선택 수정")
        self.edit_button.setFixedWidth(92)
        self.edit_button.clicked.connect(self.edit_selected)
        self.delete_button = QPushButton("선택 삭제")
        self.delete_button.setProperty("quiet", True)
        self.delete_button.setFixedWidth(92)
        self.delete_button.clicked.connect(self.delete_selected)
        self.fit_columns_button = QPushButton("열 너비 맞춤")
        self.fit_columns_button.setFixedWidth(112)
        self.fit_columns_button.setToolTip("현재 창 크기에 맞춰 열 너비를 자동으로 정리합니다.")
        self.fit_columns_button.clicked.connect(lambda: fit_table_to_view(self.table))
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        top.addWidget(self.add_button)
        top.addWidget(self.edit_button)
        top.addWidget(self.delete_button)
        top.addWidget(self.fit_columns_button)
        root.addLayout(top)
        self.table = FastEditableTable(0, 11)
        self.table.set_money_columns({7})
        self.table.setHorizontalHeaderLabels([
            "순서", "대분류", "중분류", "항목", "세부내용", "수량", "단위", "기준 단가", "VAT",
            "업체", "담당",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        configure_editable_table(
            self.table, [52, 92, 116, 180, 260, 76, 88, 120, 90, 150, 150], grouped=True
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.table.set_fixed_columns({0: 52})
        self.table.cellChanged.connect(self._cell_changed)
        self.table.cellDoubleClicked.connect(self._open_cell_editor)
        root.addWidget(self.table, 1)
        note = QLabel("기본 항목에는 일정 규칙을 저장하지 않습니다. 프로젝트별 작업 시작일과 마감일은 체크리스트에서 직접 입력합니다.")
        note.setObjectName("InfoGuide"); note.setWordWrap(True)
        root.addWidget(note)
        self.refresh()

    def rows(self):
        text = self.search.text().strip()
        if text:
            value = f"%{text}%"
            return self.db.query(
                """SELECT m.*,v.name default_vendor_name,p.name default_assignee_name
                   FROM master_items m
                   LEFT JOIN contacts v ON v.id=m.default_vendor_id
                   LEFT JOIN contacts p ON p.id=m.default_assignee_id
                   WHERE m.major LIKE ? OR m.minor LIKE ? OR m.name LIKE ? OR m.detail LIKE ?
                   ORDER BY
                     (SELECT MIN(g.sort_order) FROM master_items g WHERE g.major=m.major),
                     (SELECT MIN(g.sort_order) FROM master_items g WHERE g.major=m.major AND g.minor=m.minor),
                     m.sort_order, m.id""",
                (value, value, value, value),
            )
        return self.db.query(
            """SELECT m.*,v.name default_vendor_name,p.name default_assignee_name
               FROM master_items m
               LEFT JOIN contacts v ON v.id=m.default_vendor_id
               LEFT JOIN contacts p ON p.id=m.default_assignee_id
               ORDER BY
                 (SELECT MIN(g.sort_order) FROM master_items g WHERE g.major=m.major),
                 (SELECT MIN(g.sort_order) FROM master_items g WHERE g.major=m.major AND g.minor=m.minor),
                 m.sort_order, m.id"""
        )

    def refresh(self):
        self.loading = True
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        rows = self.rows()
        self.table.reset_spans()
        self.table.clearContents()
        self.table.setRowCount(len(rows))
        people, vendors = self._contacts()
        self._people, self._vendors = people, vendors
        for r, item in enumerate(rows):
            order = QTableWidgetItem(str(r + 1))
            order.setData(Qt.ItemDataRole.UserRole, item["id"])
            order.setFlags(order.flags() & ~(Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable))
            self.table.setItem(r, 0, order)
            quantity = "" if item["quantity"] is None else f"{item['quantity']:g}"
            values = [item["major"], item["minor"], item["name"], item["detail"], quantity]
            for c, value in enumerate(values, 1):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                if c in {1, 2}:
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, cell)
            for group_column in (1, 2):
                group = self.table.item(r, group_column)
                group.setData(GROUP_MAJOR_ROLE, item["major"])
                group.setData(GROUP_MINOR_ROLE, item["minor"])
            unit = QTableWidgetItem(item["unit"] or "식"); unit.setData(Qt.ItemDataRole.UserRole, item["id"])
            unit.setFlags(unit.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(r, 6, unit)
            price = QTableWidgetItem("" if item["base_unit_price"] is None else f"{item['base_unit_price']:,}")
            price.setData(Qt.ItemDataRole.UserRole, item["id"])
            self.table.setItem(r, 7, price)
            for c, text, data in [
                (8, "10%" if item["default_vat_type"] == "TAXABLE" else "면세", item["default_vat_type"]),
                (9, item["default_vendor_name"] or "미지정", item["default_vendor_id"]),
                (10, item["default_assignee_name"] or "미지정", item["default_assignee_id"]),
            ]:
                cell = QTableWidgetItem(text); cell.setData(Qt.ItemDataRole.UserRole, item["id"])
                cell.setData(int(Qt.ItemDataRole.UserRole) + 1, data); cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, cell)
            self.table.setRowHeight(r, 48)
        self.table.apply_category_spans(1, 2)
        self.count.setText(f"{len(rows)}개 항목")
        self.table.blockSignals(False)
        self.loading = False
        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()

    def _open_cell_editor(self, row: int, column: int) -> None:
        if column not in {6, 8, 9, 10}:
            return
        cell = self.table.item(row, column)
        if cell is None:
            return
        item_id = int(cell.data(Qt.ItemDataRole.UserRole))
        current = cell.data(int(Qt.ItemDataRole.UserRole) + 1) if column != 6 else cell.text()
        specs = {
            6: ([(unit, unit) for unit in load_master_choice_catalog(self.db).units], "unit", True),
            8: ([("10%", "TAXABLE"), ("면세", "EXEMPT")], "default_vat_type", False),
            9: ([("미지정", None)] + [(x["name"], x["id"]) for x in self._vendors], "default_vendor_id", False),
            10: ([("미지정", None)] + [(x["name"], x["id"]) for x in self._people], "default_assignee_id", False),
        }
        choices, field, editable = specs[column]

        def commit(value):
            self._update_field(item_id, field, value)
            label = value if editable else next((text for text, data in choices if data == value), "미지정")
            cell.setText(str(label)); cell.setData(int(Qt.ItemDataRole.UserRole) + 1, value)

        self.table.open_choice_editor(row, column, choices, current, commit, editable=editable)

    def _update_field(self, item_id: int, field: str, value) -> None:
        if self.loading:
            return
        allowed = {"default_vendor_id", "default_assignee_id", "default_vat_type", "unit"}
        if field not in allowed:
            return
        self.db.execute(f"UPDATE master_items SET {field}=? WHERE id=?", (value, item_id))

    def _cell_changed(self, row: int, column: int) -> None:
        if self.loading:
            return
        cell = self.table.item(row, column)
        if cell is None:
            return
        if column == 0:
            return
        if column not in {1, 2, 3, 4, 5, 7}:
            return
        item_id = cell.data(Qt.ItemDataRole.UserRole)
        fields = {1: "major", 2: "minor", 3: "name", 4: "detail", 5: "quantity", 7: "base_unit_price"}
        field = fields[column]
        raw = cell.text().strip()
        try:
            if field in {"major", "minor", "name"} and not raw:
                raise ValueError("대분류, 중분류와 항목명은 비워둘 수 없습니다.")
            value = raw
            if field == "quantity":
                value = None if not raw else float(raw.replace(",", ""))
                if value is not None and value < 0:
                    raise ValueError("수량은 0 이상으로 입력하세요.")
            elif field == "base_unit_price":
                value = None if not raw else int(raw.replace(",", ""))
                if value is not None and value < 0:
                    raise ValueError("기준 단가는 0 이상으로 입력하세요.")
            if field == "major":
                old_major = str(cell.data(GROUP_MAJOR_ROLE) or "")
                if value != old_major:
                    self.db.execute("UPDATE master_items SET major=? WHERE major=?", (value, old_major))
                self.refresh()
                return
            if field == "minor":
                old_major = str(cell.data(GROUP_MAJOR_ROLE) or "")
                old_minor = str(cell.data(GROUP_MINOR_ROLE) or "")
                if value != old_minor:
                    self.db.execute(
                        "UPDATE master_items SET minor=? WHERE major=? AND minor=?",
                        (value, old_major, old_minor),
                    )
                self.refresh()
                return
            self.db.execute(f"UPDATE master_items SET {field}=? WHERE id=?", (value, item_id))
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "입력 확인", str(exc) if str(exc) else "올바른 값을 입력하세요.")
            self.refresh()

    def edit_selected(self, *_args):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "항목 선택", "수정할 기본 항목을 선택하세요.")
            return
        item_id = self.table.item(row, 3).data(Qt.ItemDataRole.UserRole)
        item = self.db.one("SELECT * FROM master_items WHERE id=?", (item_id,))
        people, vendors = self._contacts()
        dialog = MasterItemDialog(
            item, people=people, vendors=vendors, parent=self,
            category_choices=load_master_choice_catalog(self.db),
        )
        if dialog.exec():
            values = dialog.values()
            self.db.execute(
                """UPDATE master_items SET major=?,minor=?,name=?,detail=?,quantity=?,unit=?,
                   base_unit_price=?,default_vat_type=?,default_vendor_id=?,default_assignee_id=?
                   WHERE id=?""",
                (*values.values(), item_id),
            )
            self.refresh()

    def _contacts(self):
        people = self.db.query("SELECT id,name FROM contacts WHERE kind='PERSON' ORDER BY name")
        vendors = self.db.query("SELECT id,name FROM contacts WHERE kind='VENDOR' ORDER BY name")
        return people, vendors

    def add_item(self):
        people, vendors = self._contacts()
        dialog = MasterItemDialog(
            people=people, vendors=vendors, parent=self,
            category_choices=load_master_choice_catalog(self.db),
        )
        if not dialog.exec():
            return
        values = dialog.values()
        next_values = self.db.one("SELECT COALESCE(MAX(id),0)+1 next_id,COALESCE(MAX(sort_order),0)+1 next_order FROM master_items")
        self.db.execute(
            """INSERT INTO master_items(
               id,major,minor,name,detail,quantity,unit,base_unit_price,default_vat_type,
               default_vendor_id,default_assignee_id,sort_order,active
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)""",
            (next_values["next_id"], *values.values(), next_values["next_order"]),
        )
        self.refresh()

    def delete_selected(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "항목 선택", "삭제할 기본 항목을 선택하세요.")
            return
        item_id = self.table.item(row, 3).data(Qt.ItemDataRole.UserRole)
        name = self.table.item(row, 3).text()
        answer = QMessageBox.warning(
            self, "기본 항목 삭제 확인",
            f"'{name}'을(를) 기본 항목에서 삭제할까요?\n이미 생성된 프로젝트의 업무는 그대로 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.db.execute("DELETE FROM master_items WHERE id=?", (item_id,))
            self.refresh()
