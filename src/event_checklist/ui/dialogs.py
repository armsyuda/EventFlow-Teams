from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QTextEdit, QTreeWidget,
    QRadioButton, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .widgets import (
    AddableChoiceField, AppComboBox, DirectDateEdit, UnitComboBox,
    configure_money_spin, configure_quantity_spin,
)

KEEP_ASSIGNMENT = "__KEEP_ASSIGNMENT__"


def person_display_label(person) -> str:
    """Return a person label without repeating the already-visible company name."""
    parts = [str(person["name"] or "").strip()]
    for field in ("job_title", "role_note"):
        try:
            value = str(person[field] or "").strip()
        except (IndexError, KeyError):
            value = ""
        if value:
            parts.append(value)
    return " · ".join(part for part in parts if part)


class EventDialog(QDialog):
    def __init__(self, masters, event=None, vendors=(), freelancers=(),
                 selected_vendor_ids=(), selected_freelancer_ids=(), previous_events=(),
                 previous_task_loader=None, parent=None):
        super().__init__(parent)
        self.masters = list(masters)
        # QObject.event() is a native Qt virtual method. Never shadow it with data.
        self.event_record = event
        self.previous_events = list(previous_events)
        self.previous_task_loader = previous_task_loader
        self.source_event_id: int | None = None
        self.copy_settlement_prices = False
        self._tree_source = "masters"
        self.setWindowTitle("행사 수정" if event else "새 행사")
        self.resize(900 if event else 1180, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        content = QHBoxLayout()
        content.setSpacing(14)
        left_panel = QWidget()
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        content.addWidget(left_panel, 5)
        root.addLayout(content, 1)

        title = QLabel("행사 기본 정보")
        title.setObjectName("SectionTitle")
        left.addWidget(title)
        form = QFormLayout()
        form.setSpacing(4)
        self.name_edit = QLineEdit(event["name"] if event else "")
        self.name_edit.setPlaceholderText("예: 제33회 시민의 날")
        self.start_edit = DirectDateEdit()
        self.start_edit.setDate(QDate.fromString(event["start_date"], "yyyy-MM-dd") if event else QDate.currentDate())
        self.end_edit = DirectDateEdit()
        self.end_edit.setDate(QDate.fromString(event["end_date"], "yyyy-MM-dd") if event and event["end_date"] else self.start_edit.date())
        self.location_edit = QLineEdit(event["location"] if event else "")
        self.organizer_edit = QLineEdit(event["organizer"] if event else "")
        self.budget_edit = QDoubleSpinBox()
        self.budget_edit.setRange(0, 999_999_999_999)
        configure_money_spin(self.budget_edit)
        if event and event["budget"] is not None:
            self.budget_edit.setValue(event["budget"])
        self.budget_tax_mode = AppComboBox()
        self.budget_tax_mode.addItem("선택하세요", "UNSET")
        self.budget_tax_mode.addItem("부가세 포함", "INCLUDED")
        self.budget_tax_mode.addItem("부가세 별도", "EXCLUDED")
        if event:
            index = self.budget_tax_mode.findData(event["budget_tax_mode"])
            self.budget_tax_mode.setCurrentIndex(max(0, index))
        self.pm_vendor = AppComboBox()
        self.pm_vendor.addItem("미지정", None)
        for vendor in vendors:
            self.pm_vendor.addItem(vendor["name"], vendor["id"])
        if event:
            self.pm_vendor.setCurrentIndex(max(0, self.pm_vendor.findData(event["pm_vendor_id"])))
        form.addRow("행사명 *", self.name_edit)
        form.addRow("행사 시작일 *", self.start_edit)
        form.addRow("행사 마감일 *", self.end_edit)
        form.addRow("장소", self.location_edit)
        form.addRow("주최 / 주관", self.organizer_edit)
        form.addRow("예산", self.budget_edit)
        form.addRow("예산 부가세", self.budget_tax_mode)
        form.addRow("PM 업체", self.pm_vendor)
        left.addLayout(form)

        participants = QHBoxLayout()
        vendor_box = QVBoxLayout()
        vendor_box.addWidget(QLabel("참여 업체"))
        self.vendor_list = QListWidget()
        self.vendor_list.setMinimumHeight(170 if event else 70)
        self._populate_check_list(self.vendor_list, vendors, set(selected_vendor_ids))
        vendor_box.addWidget(self.vendor_list)
        freelancer_box = QVBoxLayout()
        freelancer_box.addWidget(QLabel("참여 프리랜서"))
        self.freelancer_list = QListWidget()
        self.freelancer_list.setMinimumHeight(170 if event else 70)
        self._populate_check_list(self.freelancer_list, freelancers, set(selected_freelancer_ids), show_role=True)
        freelancer_box.addWidget(self.freelancer_list)
        participants.addLayout(vendor_box, 1)
        participants.addLayout(freelancer_box, 1)
        left.addLayout(participants, 1)

        if not event:
            row = QHBoxLayout()
            guide = QLabel("선택한 업무는 날짜 없이 생성됩니다. 작업 시작일과 마감일은 체크리스트에서 직접 입력하세요.")
            guide.setWordWrap(True)
            guide.setObjectName("InfoGuide")
            left.addWidget(guide)
            item_panel = QFrame()
            item_panel.setObjectName("EventItemsPanel")
            item_layout = QVBoxLayout(item_panel)
            item_layout.setContentsMargins(16, 16, 16, 16)
            item_layout.setSpacing(10)
            section = QLabel("행사 항목 선택")
            section.setObjectName("SectionTitle")
            row.addWidget(section)
            row.addStretch()
            self.previous_button = QPushButton("이전 행사에서 가져오기")
            self.previous_button.setEnabled(bool(self.previous_events and self.previous_task_loader))
            self.previous_button.setToolTip(
                "이전 행사의 항목을 가져옵니다. 담당자, 업체, 일정과 진행상태는 복사하지 않습니다."
            )
            all_button = QPushButton("전체 선택")
            none_button = QPushButton("전체 해제")
            row.addWidget(self.previous_button)
            row.addWidget(all_button)
            row.addWidget(none_button)
            item_layout.addLayout(row)
            self.tree = QTreeWidget()
            self.tree.setMinimumWidth(470)
            self.tree.setHeaderLabels(["분류 / 항목"])
            self.tree.setColumnWidth(0, 420)
            self._populate_tree()
            self.previous_button.clicked.connect(self._open_previous_event_import)
            all_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
            none_button.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
            item_layout.addWidget(self.tree, 1)
            content.addWidget(item_panel, 4)
        else:
            self.tree = None
            note = QLabel("행사 날짜를 바꿔도 체크리스트에 직접 입력한 작업 일정은 유지됩니다.")
            note.setWordWrap(True)
            note.setObjectName("Muted")
            left.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("저장")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _populate_tree(self) -> None:
        self.tree.clear()
        self._tree_source = "masters"
        self.source_event_id = None
        self.copy_settlement_prices = False
        self.tree.setHeaderLabels(["분류 / 항목"])
        parents: dict[tuple[str, str], QTreeWidgetItem] = {}
        major_items: dict[str, QTreeWidgetItem] = {}
        for item in self.masters:
            major = item["major"]
            minor = item["minor"]
            major_item = major_items.get(major)
            if major_item is None:
                major_item = QTreeWidgetItem(self.tree, [major])
                major_item.setFlags(major_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                major_item.setCheckState(0, Qt.CheckState.Checked)
                major_items[major] = major_item
            parent = parents.get((major, minor))
            if parent is None:
                parent = QTreeWidgetItem(major_item, [minor])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                parent.setCheckState(0, Qt.CheckState.Checked)
                parents[(major, minor)] = parent
            child = QTreeWidgetItem(parent, [item["name"]])
            child.setData(0, Qt.ItemDataRole.UserRole, item["id"])
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
        self.tree.expandToDepth(1)

    def _open_previous_event_import(self) -> None:
        chooser = PreviousEventImportDialog(self.previous_events, self)
        if not chooser.exec():
            return
        source_event_id, copy_prices = chooser.values()
        tasks = list(self.previous_task_loader(source_event_id))
        if not tasks:
            QMessageBox.information(self, "가져올 항목 없음", "선택한 행사에는 가져올 항목이 없습니다.")
            return
        self._populate_previous_tree(tasks, source_event_id, copy_prices)

    def _populate_previous_tree(self, tasks, source_event_id: int, copy_prices: bool) -> None:
        self.tree.clear()
        self._tree_source = "previous"
        self.source_event_id = int(source_event_id)
        self.copy_settlement_prices = bool(copy_prices)
        mode = "항목 + 정산 단가" if copy_prices else "항목만 · 단가 0원"
        source_name = next(
            (row["name"] for row in self.previous_events if int(row["id"]) == self.source_event_id),
            "이전 행사",
        )
        self.tree.setHeaderLabels([f"{source_name}  |  {mode}"])
        parents: dict[tuple[str, str], QTreeWidgetItem] = {}
        major_items: dict[str, QTreeWidgetItem] = {}
        for task in tasks:
            major, minor = task["major"], task["minor"]
            major_item = major_items.get(major)
            if major_item is None:
                major_item = QTreeWidgetItem(self.tree, [major])
                major_item.setFlags(major_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                major_item.setCheckState(0, Qt.CheckState.Checked)
                major_items[major] = major_item
            parent = parents.get((major, minor))
            if parent is None:
                parent = QTreeWidgetItem(major_item, [minor])
                parent.setFlags(parent.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                parent.setCheckState(0, Qt.CheckState.Checked)
                parents[(major, minor)] = parent
            child = QTreeWidgetItem(parent, [task["name"]])
            child.setData(0, Qt.ItemDataRole.UserRole, int(task["id"]))
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Checked)
        self.tree.expandToDepth(1)

    def _set_all(self, state: Qt.CheckState) -> None:
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, state)

    def selected_ids(self) -> list[int]:
        if self.tree is None:
            return []
        result: list[int] = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            item_id = item.data(0, Qt.ItemDataRole.UserRole)
            if item_id and item.checkState(0) == Qt.CheckState.Checked:
                result.append(int(item_id))
            iterator += 1
        return result

    def import_values(self) -> dict:
        if self._tree_source != "previous":
            return {}
        return {
            "source_event_id": self.source_event_id,
            "source_task_ids": self.selected_ids(),
            "copy_settlement_prices": self.copy_settlement_prices,
        }

    def values(self) -> dict:
        start = self.start_edit.date().toPython()
        end = self.end_edit.date().toPython()
        budget = self.budget_edit.value() or None
        return {
            "name": self.name_edit.text().strip(),
            "start_date": start,
            "end_date": end,
            "location": self.location_edit.text().strip(),
            "organizer": self.organizer_edit.text().strip(),
            "budget": budget,
            "budget_tax_mode": self.budget_tax_mode.currentData(),
            "pm_vendor_id": self.pm_vendor.currentData(),
        }

    @staticmethod
    def _populate_check_list(widget: QListWidget, rows, selected: set[int], show_role: bool = False) -> None:
        for row in rows:
            label = person_display_label(row) if show_role else row["name"]
            item = QListWidgetItem(label)
            if show_role:
                try:
                    job_title = (row["job_title"] or "").strip()
                except (IndexError, KeyError):
                    job_title = ""
                role = (row["role_note"] or "").strip()
                item.setToolTip(
                    f"이름: {row['name']}\n직책: {job_title or '미입력'}\n역할: {role or '미입력'}"
                )
            item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if int(row["id"]) in selected else Qt.CheckState.Unchecked)
            widget.addItem(item)

    @staticmethod
    def _checked_ids(widget: QListWidget) -> list[int]:
        return [int(widget.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(widget.count())
                if widget.item(i).checkState() == Qt.CheckState.Checked]

    def selected_vendor_ids(self) -> list[int]:
        return self._checked_ids(self.vendor_list)

    def selected_freelancer_ids(self) -> list[int]:
        return self._checked_ids(self.freelancer_list)

    def _validate(self) -> None:
        values = self.values()
        if not values["name"]:
            QMessageBox.warning(self, "입력 확인", "행사명을 입력하세요.")
            self.name_edit.setFocus()
            return
        if values["end_date"] < values["start_date"]:
            QMessageBox.warning(self, "입력 확인", "행사 마감일은 행사 시작일보다 빠를 수 없습니다.")
            self.end_edit.setFocus()
            return
        if values["budget"] and values["budget_tax_mode"] == "UNSET":
            QMessageBox.warning(self, "입력 확인", "총예산이 있으면 부가세 포함 또는 별도를 선택하세요.")
            self.budget_tax_mode.setFocus()
            return
        if self.tree is not None and not self.selected_ids():
            QMessageBox.warning(self, "입력 확인", "하나 이상의 항목을 선택하세요.")
            return
        self.accept()


from PySide6.QtWidgets import QTreeWidgetItemIterator  # noqa: E402


class PreviousEventImportDialog(QDialog):
    def __init__(self, events, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이전 행사에서 가져오기")
        self.resize(520, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        title = QLabel("기준이 될 이전 행사를 선택하세요")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.event_combo = AppComboBox()
        for event in events:
            period = event["start_date"]
            if event["end_date"]:
                period += f" ~ {event['end_date']}"
            self.event_combo.addItem(f"{event['name']}  ·  {period}", int(event["id"]))
        layout.addWidget(self.event_combo)

        mode_title = QLabel("가져오기 방식")
        mode_title.setObjectName("FieldLabel")
        layout.addWidget(mode_title)
        self.item_only = QRadioButton("항목만 가져오기")
        self.item_only.setToolTip("항목 구조를 가져오고 단가는 모두 0원으로 시작합니다.")
        self.with_settlement = QRadioButton("항목과 정산 가져오기")
        self.with_settlement.setToolTip("항목 구조와 이전 행사의 단가를 가져옵니다.")
        self.item_only.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.item_only)
        self.mode_group.addButton(self.with_settlement)
        layout.addWidget(self.item_only)
        layout.addWidget(self.with_settlement)
        note = QLabel("두 방식 모두 수량은 1, 진행상태는 미착수, 작업 일정과 담당자·업체는 미지정으로 생성됩니다.")
        note.setWordWrap(True)
        note.setObjectName("InfoGuide")
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("항목 불러오기")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[int, bool]:
        return int(self.event_combo.currentData()), self.with_settlement.isChecked()


class MasterImportDialog(QDialog):
    def __init__(self, masters, parent=None):
        super().__init__(parent)
        self.setWindowTitle("기본항목 가져오기")
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("가져올 기본항목을 선택하세요")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["분류 / 항목", "상태"])
        parents = {}
        for row in masters:
            key = (row["major"], row["minor"])
            parent_item = parents.get(key)
            if parent_item is None:
                parent_item = QTreeWidgetItem(self.tree, [f"{key[0]} / {key[1]}"])
                parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
                parent_item.setCheckState(0, Qt.CheckState.Unchecked)
                parents[key] = parent_item
            state = "제외 기록 복원" if row["is_removed"] else "새로 추가"
            child = QTreeWidgetItem(parent_item, [row["name"], state])
            child.setToolTip(0, row["detail"] or "세부내용 없음")
            child.setData(0, Qt.ItemDataRole.UserRole, int(row["id"]))
            child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            child.setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.expandToDepth(0)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("가져오기")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_ids(self) -> list[int]:
        ids = []
        iterator = QTreeWidgetItemIterator(self.tree)
        while iterator.value():
            item = iterator.value()
            value = item.data(0, Qt.ItemDataRole.UserRole)
            if value and item.checkState(0) == Qt.CheckState.Checked:
                ids.append(int(value))
            iterator += 1
        return ids

    def _accept(self):
        if not self.selected_ids():
            QMessageBox.warning(self, "선택 확인", "하나 이상의 항목을 선택하세요.")
            return
        self.accept()


class CustomTaskDialog(QDialog):
    def __init__(self, event, parent=None, category_choices=None, unit_choices=None):
        super().__init__(parent)
        self.setWindowTitle("직접 항목 추가")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        self._minors_by_major = dict(category_choices.minors_by_major) if category_choices else {}
        self.major = AddableChoiceField(
            list(category_choices.majors) if category_choices else ["시스템", "시설", "행사", "홍보", "운영"],
            add_label="+ 새 대분류", dialog_title="새 대분류 추가", prompt="대분류 이름",
        )
        self.minor = AddableChoiceField(
            add_label="+ 새 중분류", dialog_title="새 중분류 추가", prompt="중분류 이름",
        )
        self.major.combo.activated.connect(self._major_selected)
        self.major.value_added.connect(lambda value: self._reload_minors(value))
        self._reload_minors(self.major.currentText())
        self.name = QLineEdit()
        self.detail = QTextEdit()
        self.detail.setMaximumHeight(90)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 999_999_999)
        configure_quantity_spin(self.quantity)
        self.quantity.setValue(1)
        self.unit = UnitComboBox("식", choices=unit_choices)
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 999_999_999_999)
        configure_money_spin(self.price)
        self.vat = AppComboBox()
        self.vat.addItem("VAT 10%", "TAXABLE")
        self.vat.addItem("면세", "EXEMPT")
        for label, widget in [("대분류 *", self.major), ("중분류 *", self.minor), ("항목 *", self.name),
                              ("세부내용", self.detail),
                              ("수량", self.quantity), ("단위", self.unit), ("행사 단가", self.price), ("VAT", self.vat)]:
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.major.currentText().strip() or not self.minor.currentText().strip() or not self.name.text().strip():
            QMessageBox.warning(self, "입력 확인", "대분류, 중분류, 항목을 모두 입력하세요.")
            return
        self.accept()

    def values(self) -> dict:
        return {"major": self.major.currentText().strip(), "minor": self.minor.currentText().strip(),
                "name": self.name.text().strip(), "detail": self.detail.toPlainText().strip(),
                "planned_start": None, "due_date": None,
                "quantity": int(self.quantity.value()), "unit": self.unit.currentText().strip() or "식",
                "unit_price": int(self.price.value()) or None, "vat_type": self.vat.currentData()}

    def _major_selected(self, *_args):
        self._reload_minors(self.major.currentText())

    def _reload_minors(self, major: str, keep_current: bool = False):
        self._active_major = major.strip()
        current = self.minor.currentText().strip() if keep_current else ""
        self.minor.combo.blockSignals(True)
        self.minor.clear()
        self.minor.addItems(list(self._minors_by_major.get(major.strip(), ())))
        if current:
            self.minor.setCurrentText(current)
        self.minor.combo.blockSignals(False)
        self.minor.setToolTip("선택한 대분류의 기존 중분류를 고르거나 새 이름을 직접 입력할 수 있습니다.")


class ContactDialog(QDialog):
    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("담당자 추가" if kind == "PERSON" else "업체 추가")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.phone_edit = QLineEdit()
        self.job_title_edit = QLineEdit()
        self.note_edit = QLineEdit()
        form.addRow("이름 *" if kind == "PERSON" else "업체명 *", self.name_edit)
        if kind == "PERSON":
            form.addRow("직책", self.job_title_edit)
            form.addRow("연락처", self.phone_edit)
            form.addRow("역할", self.note_edit)
        else:
            form.addRow("업종", self.note_edit)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        if not self.name_edit.text().strip():
            target = "이름" if self.kind == "PERSON" else "업체명"
            QMessageBox.warning(self, "입력 확인", f"{target}을 입력하세요.")
            return
        self.accept()

    def values(self):
        return {
            "name": self.name_edit.text().strip(),
            "phone": self.phone_edit.text().strip() if self.kind == "PERSON" else "",
            "job_title": self.job_title_edit.text().strip() if self.kind == "PERSON" else "",
            "role_note": self.note_edit.text().strip(),
        }


class MasterItemDialog(QDialog):
    def __init__(self, item=None, people=(), vendors=(), parent=None, category_choices=None):
        super().__init__(parent)
        self.item = item
        self.setWindowTitle("기본 항목 수정" if item else "기본 항목 추가")
        self.resize(620, 660)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        form = QFormLayout()
        self._minors_by_major = dict(category_choices.minors_by_major) if category_choices else {}
        self.major = AddableChoiceField(
            list(category_choices.majors) if category_choices else ["시스템", "시설", "행사", "홍보", "운영"],
            add_label="+ 새 대분류", dialog_title="새 대분류 추가", prompt="대분류 이름",
        )
        self.minor = AddableChoiceField(
            add_label="+ 새 중분류", dialog_title="새 중분류 추가", prompt="중분류 이름",
        )
        self.major.combo.activated.connect(self._major_selected)
        self.major.value_added.connect(lambda value: self._reload_minors(value))
        self.name = QLineEdit(item["name"] if item else "")
        self.detail = QTextEdit(item["detail"] if item else "")
        self.detail.setMaximumHeight(100)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 999_999_999)
        configure_quantity_spin(self.quantity)
        self.quantity.setValue((item["quantity"] or 0) if item else 0)
        self.unit = AddableChoiceField(
            category_choices.units if category_choices else (),
            item["unit"] if item and item["unit"] else "식",
            add_label="+ 새 단위", dialog_title="새 단위 추가", prompt="단위 이름",
        )
        self.base_unit_price = QDoubleSpinBox()
        self.base_unit_price.setRange(0, 999_999_999_999)
        configure_money_spin(self.base_unit_price)
        self.base_unit_price.setValue((item["base_unit_price"] or 0) if item else 0)
        self.vat_type = AppComboBox()
        self.vat_type.addItem("VAT 10%", "TAXABLE")
        self.vat_type.addItem("면세", "EXEMPT")
        self.vendor = AppComboBox()
        self.vendor.addItem("미지정", None)
        for contact in vendors:
            self.vendor.addItem(contact["name"], contact["id"])
        self.assignee = AppComboBox()
        self.assignee.addItem("미지정", None)
        for contact in people:
            self.assignee.addItem(contact["name"], contact["id"])
        if item:
            self.major.setCurrentText(item["major"])
            self._reload_minors(item["major"], item["minor"])
            self.vendor.setCurrentIndex(max(0, self.vendor.findData(item["default_vendor_id"])))
            self.assignee.setCurrentIndex(max(0, self.assignee.findData(item["default_assignee_id"])))
            self.vat_type.setCurrentIndex(max(0, self.vat_type.findData(item["default_vat_type"])))
        else:
            self._reload_minors(self.major.currentText())
        self.major.setToolTip("기존 대분류를 고르거나 새 이름을 직접 입력할 수 있습니다.")
        self.unit.setToolTip("기존 단위를 고르거나 새 단위를 직접 입력할 수 있습니다.")
        form.addRow("대분류 *", self.major)
        form.addRow("중분류 *", self.minor)
        form.addRow("항목 *", self.name)
        form.addRow("세부내용", self.detail)
        form.addRow("수량", self.quantity)
        form.addRow("단위", self.unit)
        form.addRow("기준 단가(공급가)", self.base_unit_price)
        form.addRow("VAT", self.vat_type)
        form.addRow("기본 업체", self.vendor)
        form.addRow("기본 담당", self.assignee)
        layout.addLayout(form)
        guide = QLabel("작업 시작일과 마감일은 행사를 만든 뒤 체크리스트에서 직접 입력합니다.")
        guide.setObjectName("InfoGuide"); guide.setWordWrap(True); layout.addWidget(guide)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _major_selected(self, *_args):
        self._reload_minors(self.major.currentText())

    def _reload_minors(self, major: str, current: str = ""):
        self._active_major = major.strip()
        self.minor.combo.blockSignals(True)
        self.minor.clear()
        self.minor.addItems(list(self._minors_by_major.get(major.strip(), ())))
        if current.strip():
            self.minor.setCurrentText(current.strip())
        self.minor.combo.blockSignals(False)
        self.minor.setToolTip("선택한 대분류의 기존 중분류를 고르거나 새 이름을 직접 입력할 수 있습니다.")

    def _accept(self):
        if not self.major.currentText().strip() or not self.minor.currentText().strip() or not self.name.text().strip():
            QMessageBox.warning(self, "입력 확인", "대분류, 중분류, 항목명을 모두 입력하세요.")
            return
        self.accept()

    def values(self):
        return {
            "major": self.major.currentText().strip(),
            "minor": self.minor.currentText().strip(),
            "name": self.name.text().strip(),
            "detail": self.detail.toPlainText().strip(),
            "quantity": int(self.quantity.value()) or None,
            "unit": self.unit.currentText().strip() or "식",
            "base_unit_price": int(self.base_unit_price.value()) or None,
            "default_vat_type": self.vat_type.currentData(),
            "default_vendor_id": self.vendor.currentData(),
            "default_assignee_id": self.assignee.currentData(),
        }


class BulkAssignmentDialog(QDialog):
    def __init__(self, event, vendors, people, selected_count: int, parent=None):
        super().__init__(parent)
        self.event_record = event
        self.vendors = list(vendors)
        self.people = list(people)
        self.setWindowTitle("선택 행 담당 일괄 지정")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel(f"선택한 {selected_count}개 항목에 일괄 적용")
        title.setObjectName("SectionTitle")
        guide = QLabel("변경할 항목만 선택하세요. ‘변경 안 함’은 기존 값을 유지합니다.")
        guide.setObjectName("InfoGuide"); guide.setWordWrap(True)
        layout.addWidget(title); layout.addWidget(guide)

        form = QFormLayout()
        self.pm_assignee = AppComboBox()
        self.pm_assignee.addItem("변경 안 함", KEEP_ASSIGNMENT)
        self.pm_assignee.addItem("미지정", None)
        pm_vendor_id = event["pm_vendor_id"] if event else None
        for person in self.people:
            if pm_vendor_id and person["company_id"] == pm_vendor_id:
                self.pm_assignee.addItem(person_display_label(person), person["id"])

        self.vendor = AppComboBox()
        self.vendor.addItem("변경 안 함", KEEP_ASSIGNMENT)
        self.vendor.addItem("미지정", None)
        for vendor in self.vendors:
            self.vendor.addItem(vendor["name"], vendor["id"])
        self.vendor.currentIndexChanged.connect(self._reload_vendor_people)

        self.vendor_assignee = AppComboBox()
        self._reload_vendor_people()
        form.addRow("담당자(PM)", self.pm_assignee)
        form.addRow("업체", self.vendor)
        form.addRow("업체담당자", self.vendor_assignee)
        layout.addLayout(form)

        note = QLabel("업체를 변경하면 업체담당자는 선택한 업체의 담당자만 표시됩니다.")
        note.setObjectName("Muted"); note.setWordWrap(True); layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reload_vendor_people(self, *_args):
        vendor_id = self.vendor.currentData()
        self.vendor_assignee.blockSignals(True)
        self.vendor_assignee.clear()
        if vendor_id == KEEP_ASSIGNMENT:
            self.vendor_assignee.addItem("변경 안 함", KEEP_ASSIGNMENT)
            self.vendor_assignee.setEnabled(False)
        else:
            self.vendor_assignee.addItem("미지정", None)
            if vendor_id is not None:
                for person in self.people:
                    if person["company_id"] == vendor_id:
                        self.vendor_assignee.addItem(person_display_label(person), person["id"])
            self.vendor_assignee.setEnabled(vendor_id is not None)
        self.vendor_assignee.blockSignals(False)

    def values(self):
        result = {}
        pm_assignee_id = self.pm_assignee.currentData()
        vendor_id = self.vendor.currentData()
        if pm_assignee_id != KEEP_ASSIGNMENT:
            result["pm_assignee_id"] = pm_assignee_id
        if vendor_id != KEEP_ASSIGNMENT:
            result["vendor_id"] = vendor_id
            result["assignee_id"] = self.vendor_assignee.currentData()
        return result

    def _accept(self):
        if not self.values():
            QMessageBox.information(self, "지정할 내용", "변경할 담당자 또는 업체를 선택하세요.")
            return
        self.accept()


class TaskDetailsDialog(QDialog):
    def __init__(self, task, parent=None, unit_choices=None):
        super().__init__(parent)
        self.task = task
        self.setWindowTitle("업무 상세 수정")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel(task["name"])
        title.setObjectName("SectionTitle")
        category = QLabel(f"{task['major']} / {task['minor']}")
        category.setObjectName("Muted")
        layout.addWidget(title)
        layout.addWidget(category)
        form = QFormLayout()
        self.detail = QTextEdit(task["detail"])
        self.detail.setPlaceholderText("업무의 세부내용을 입력하세요.")
        self.detail.setMaximumHeight(120)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0, 999_999_999)
        configure_quantity_spin(self.quantity)
        self.quantity.setValue(task["quantity"] or 0)
        self.unit = UnitComboBox(task["unit"] or "식", choices=unit_choices)
        self.note = QTextEdit(task["note"])
        self.note.setPlaceholderText("이 행사에서만 사용하는 메모를 입력하세요.")
        self.note.setMaximumHeight(140)
        form.addRow("세부내용", self.detail)
        form.addRow("수량", self.quantity)
        form.addRow("단위", self.unit)
        form.addRow("메모", self.note)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {
            "detail": self.detail.toPlainText().strip(),
            "quantity": int(self.quantity.value()) or None,
            "unit": self.unit.currentText().strip() or "식",
            "note": self.note.toPlainText().strip(),
        }
