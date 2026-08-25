from __future__ import annotations

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDoubleSpinBox, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..choices import load_master_choice_catalog
from ..pdf_export import export_checklist_pdf
from ..theme import status_color
from .dialogs import BulkAssignmentDialog, CustomTaskDialog, MasterImportDialog, person_display_label
from .widgets import (
    GROUP_MAJOR_ROLE, GROUP_MINOR_ROLE, AppComboBox, FastEditableTable, configure_editable_table,
    fit_table_to_view,
)
from .pdf_export_dialog import configure_pdf_icon_button, export_pdf_from_page

STATUSES = ["미착수", "진행중", "확인요청", "완료", "보류", "해당없음"]

# 업체 콤보에서 프리랜서 그룹을 고유하게 식별하는 sentinel.
# contacts.id 는 정수이므로 문자열 sentinel 과 충돌하지 않는다.
# 프리랜서는 업체(vendor)가 없는 개인(PERSON, company_id IS NULL)이므로
# event_tasks.vendor_id 는 NULL 로 유지하고 assignee_id 로만 표현한다.
FREELANCER_KEY = "__FREELANCER__"

# 콤보 업체 목록에서 숨길 업체 이름. DB에 이미 '(업체 미정)' 이라는 시드 업체가 존재해
# '미지정' 항목과 중복되므로 업체 선택 콤보에서는 제외한다. 실제 업무에 배정돼 있어도
# 데이터는 건드리지 않고 표시만 '미지정'으로 처리한다.
HIDDEN_VENDOR_NAME = "(업체 미정)"


class EventsPage(QWidget):
    edit_requested = Signal(int)
    changed = Signal(int)

    def __init__(self, service, db, parent=None):
        super().__init__(parent)
        self.service = service
        self.db = db
        self.event_id: int | None = None
        self.loading = False
        self._loaded_event_id: int | None = None
        self._current_tasks = []
        self._freelancer_ids: set[int] = set()
        self._hide_vendor_ids: set[int] = set()
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 32)
        root.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(10)
        title = QLabel("체크리스트")
        title.setObjectName("PageTitle")
        self.description = QLabel("선택한 행사의 업무 상태와 일정을 관리합니다.")
        self.description.setObjectName("PageDescription")
        self.summary = QLabel("")
        self.summary.setObjectName("ChecklistCount")
        top.addWidget(title, 0, Qt.AlignmentFlag.AlignBottom)
        top.addWidget(self.description, 0, Qt.AlignmentFlag.AlignBottom)
        top.addWidget(self.summary, 0, Qt.AlignmentFlag.AlignBottom)
        top.addStretch()
        self.import_button = QPushButton("기본항목에서 항목 가져오기")
        self.import_button.clicked.connect(self.import_master)
        self.import_button.setProperty("quiet", True)
        top.addWidget(self.import_button)
        self.edit_event_button = QPushButton("행사 정보 수정")
        self.edit_event_button.clicked.connect(lambda: self.event_id and self.edit_requested.emit(self.event_id))
        self.edit_event_button.setProperty("quiet", True)
        top.addWidget(self.edit_event_button)
        self.fit_button = QPushButton("열 너비 맞춤")
        self.fit_button.clicked.connect(lambda: fit_table_to_view(self.table))
        top.addWidget(self.fit_button)
        root.addLayout(top)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("항목·세부내용·메모 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_tasks)
        self.status_filter = AppComboBox()
        self.status_filter.addItem("모든 상태", "")
        for status in STATUSES:
            self.status_filter.addItem(status, status)
        self.status_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.major_filter = AppComboBox()
        self.major_filter.addItem("모든 대분류", "")
        for major in load_master_choice_catalog(self.db).majors:
            self.major_filter.addItem(major, major)
        self.major_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.vendor_filter = AppComboBox()
        self.vendor_filter.addItem("모든 업체", None)
        self.vendor_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.pm_filter = AppComboBox()
        self.pm_filter.addItem("모든 담당자(PM)", None)
        self.pm_filter.currentIndexChanged.connect(self.refresh_tasks)
        self.bulk_assign_button = QPushButton("선택 행 담당 지정")
        self.bulk_assign_button.setProperty("checklistAction", True)
        self.bulk_assign_button.clicked.connect(self.assign_selected)
        actions.addWidget(self.search, 1)
        actions.addWidget(self.status_filter)
        actions.addWidget(self.major_filter)
        actions.addWidget(self.vendor_filter)
        actions.addWidget(self.pm_filter)
        actions.addWidget(self.bulk_assign_button)
        self.add_button = QPushButton("+ 직접 항목 추가")
        self.add_button.setProperty("checklistAction", True)
        self.add_button.setProperty("primary", True)
        self.add_button.setMinimumWidth(144)
        self.add_button.clicked.connect(self.add_custom)
        actions.addWidget(self.add_button)
        self.remove_button = QPushButton("선택 항목 제외")
        self.remove_button.setProperty("checklistAction", True)
        self.remove_button.setProperty("attention", True)
        self.remove_button.setMinimumWidth(130)
        self.remove_button.clicked.connect(self.remove_selected)
        actions.addWidget(self.remove_button)
        self.removed_toggle = QPushButton("제외 항목 보기")
        self.removed_toggle.setProperty("checklistAction", True)
        self.removed_toggle.setCheckable(True)
        self.removed_toggle.setProperty("quiet", True)
        self.removed_toggle.toggled.connect(self._removed_view_toggled)
        actions.addWidget(self.removed_toggle)
        self.pdf_button = QPushButton()
        self.pdf_button.setProperty("checklistAction", True)
        configure_pdf_icon_button(self.pdf_button, size=44)
        self.pdf_button.clicked.connect(self.export_pdf)
        actions.addWidget(self.pdf_button)
        for widget in (
            self.search, self.status_filter, self.major_filter, self.vendor_filter, self.pm_filter,
        ):
            widget.setProperty("checklistCompact", True)
        root.addLayout(actions)

        self.table = FastEditableTable(0, 14)
        self.table.setHorizontalHeaderLabels([
            "순서", "대분류", "중분류", "항목", "세부내용", "수량", "단위", "상태", "작업 시작일", "마감일",
            "담당자(PM)", "업체", "업체담당자", "업체담당자 전화번호",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)  # zebra 는 _apply_row_zebra 로 명시 제어
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        configure_editable_table(
            self.table, [48, 92, 116, 190, 570, 64, 72, 112, 125, 125, 155, 145, 165, 150],
            grouped=True, wrap_columns=(2, 3),
        )
        self.table.setProperty("fitWrapColumns", [2, 3])  # 중분류, 항목
        self.table.set_fixed_columns({0: 48})
        self.table.set_left_columns({4})  # 세부내용은 좌측 정렬
        self.table.cellDoubleClicked.connect(self._open_cell_editor)
        self.table.enable_row_drag(self._handle_row_drag)
        self.table.enable_major_float(1)  # 대분류가 화면 밖으로 벗어나도 이름을 상단에 고정 표시
        root.addWidget(self.table, 1)

    def set_event(self, event_id: int | None, *, force: bool = False):
        if not force and self._loaded_event_id == event_id:
            return
        self.event_id = event_id
        event = self.service.get_event(event_id) if event_id else None
        self.description.setText(f"{event['name']}의 업무 상태와 일정을 관리합니다." if event else "행사를 선택하세요.")
        self.refresh_tasks()
        self._loaded_event_id = event_id

    def export_pdf(self):
        export_pdf_from_page(self, self.db, self.event_id, "checklist", export_checklist_pdf)

    def invalidate(self):
        self._loaded_event_id = None

    def refresh_events(self, selected_event_id: int | None = None):
        self.set_event(selected_event_id if selected_event_id is not None else self.event_id)

    def import_master(self):
        if not self.event_id:
            return
        masters = self.db.query(
            """SELECT m.*, COALESCE(t.is_removed,0) is_removed FROM master_items m
               LEFT JOIN event_tasks t ON t.event_id=? AND t.master_item_id=m.id
               WHERE t.id IS NULL OR t.is_removed=1 ORDER BY m.sort_order""", (self.event_id,))
        if not masters:
            total = self.db.one("SELECT COUNT(*) count FROM master_items")["count"]
            QMessageBox.information(
                self,
                "기본항목",
                f"현재 행사에 기본 항목 {total}개가 모두 포함되어 있습니다.\n\n"
                "설정 > 기본 항목에서 새 항목을 추가하거나, 체크리스트에서 항목을 제외하면 다시 가져올 수 있습니다.",
            )
            return
        dialog = MasterImportDialog(masters, self)
        if dialog.exec():
            try:
                added, restored = self.service.add_master_tasks(self.event_id, dialog.selected_ids())
            except Exception as exc:
                QMessageBox.critical(self, "가져오기 실패", f"기본 항목을 가져오지 못했습니다.\n\n{exc}")
                return
            QMessageBox.information(self, "가져오기 완료", f"새로 추가 {added}개 · 기존 기록 복원 {restored}개")
            self.removed_toggle.setChecked(False)
            self.refresh_tasks()
            self.changed.emit(self.event_id)

    def add_custom(self):
        if not self.event_id:
            return
        choices = load_master_choice_catalog(self.db)
        dialog = CustomTaskDialog(
            self.service.get_event(self.event_id), self,
            category_choices=choices, unit_choices=choices.units,
        )
        if dialog.exec():
            try:
                self.service.add_custom_task(self.event_id, **dialog.values())
            except Exception as exc:
                QMessageBox.critical(self, "항목 추가 실패", f"항목을 추가하지 못했습니다.\n\n{exc}")
                return
            self.refresh_tasks()
            self.changed.emit(self.event_id)

    def remove_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            action = "복원" if self.removed_toggle.isChecked() else "제외"
            QMessageBox.information(self, "항목 선택", f"{action}할 항목 행을 선택하세요.")
            return
        removed_view = self.removed_toggle.isChecked()
        action = "복원" if removed_view else "제외"
        answer = QMessageBox.question(
            self, f"항목 {action}", f"선택한 {len(ids)}개 항목을 {action}할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.set_task_removed(ids, not removed_view)
        except Exception as exc:
            QMessageBox.critical(self, f"항목 {action} 실패", str(exc))
            return
        self.refresh_tasks()
        self.changed.emit(self.event_id or 0)

    def assign_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            QMessageBox.information(self, "항목 선택", "담당자를 지정할 항목 행을 선택하세요.\nCtrl 또는 Shift를 누르면 여러 행을 선택할 수 있습니다.")
            return
        event = self.service.get_event(self.event_id)
        vendors = self.db.query("SELECT * FROM contacts WHERE kind='VENDOR' ORDER BY name,id")
        people = self.db.query("SELECT * FROM contacts WHERE kind='PERSON' ORDER BY name,id")
        dialog = BulkAssignmentDialog(event, vendors, people, len(ids), self)
        if not dialog.exec():
            return
        try:
            changed_count = self.service.bulk_assign_tasks(self.event_id, ids, **dialog.values())
        except Exception as exc:
            QMessageBox.critical(self, "담당 일괄 지정 실패", str(exc))
            return
        self.refresh_tasks()
        self.changed.emit(self.event_id or 0)
        QMessageBox.information(self, "일괄 지정 완료", f"선택한 {changed_count}개 항목에 적용했습니다.")

    def _removed_view_toggled(self, checked: bool):
        if self.remove_button is not None:
            self.remove_button.setText("선택 항목 복원" if checked else "선택 항목 제외")
        self.bulk_assign_button.setEnabled(not checked)
        self.refresh_tasks()

    def _selected_task_ids(self):
        ids = []
        # 사용자는 행 머리글뿐 아니라 셀 범위를 드래그해서 선택한다. selectedRows()
        # 는 완전한 행 선택만 반환하므로, 선택된 셀이 하나라도 있는 모든 행을 모은다.
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        for row in selected_rows:
            item = self.table.item(row, 3)
            if item:
                ids.append(int(item.data(Qt.ItemDataRole.UserRole)))
        return list(dict.fromkeys(ids))

    def refresh_tasks(self):
        self.loading = True
        self._sync_major_filter()
        self._sync_assignment_filters()
        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.reset_spans()
        self.table.setRowCount(0)
        if not self.event_id:
            self.summary.setText("행사를 선택하세요")
            self.loading = False
            self.table.blockSignals(False)
            self.table.setUpdatesEnabled(True)
            return
        tasks = [dict(row) for row in self.service.list_tasks(
            self.event_id, self.search.text().strip(), self.status_filter.currentData() or "",
            self.major_filter.currentData() or "", include_removed=self.removed_toggle.isChecked(),
            vendor_id=self.vendor_filter.currentData(), pm_assignee_id=self.pm_filter.currentData())]
        if self.removed_toggle.isChecked():
            tasks = [row for row in tasks if row["is_removed"]]
        self._current_tasks = tasks
        event = self.service.get_event(self.event_id)
        # 설정에서 추가한 업체와 담당자를 별도의 행사 참여자 편집 없이 바로
        # 선택할 수 있도록 전체 연락처를 한 번 읽고 업체별로 나눈다.
        vendors = self.db.query("SELECT * FROM contacts WHERE kind='VENDOR' ORDER BY name,id")
        # '(업체 미정)' 시드 업체는 업체 선택 목록에서 숨기되, 이미 배정된 업무 표시 처리용으로 id 는 보관한다.
        visible_vendors = [v for v in vendors if v["name"] != HIDDEN_VENDOR_NAME]
        hidden_vendor_ids = {int(v["id"]) for v in vendors if v["name"] == HIDDEN_VENDOR_NAME}
        all_assignees = self.db.query(
            """SELECT p.*,v.name company_name FROM contacts p
              LEFT JOIN contacts v ON v.id=p.company_id
              WHERE p.kind='PERSON' ORDER BY p.name,COALESCE(v.name,''),p.id"""
        )
        assignees_by_vendor = {
            int(vendor["id"]): [row for row in all_assignees if row["company_id"] == vendor["id"]]
            for vendor in visible_vendors
        }
        freelancers = [row for row in all_assignees if row["company_id"] is None]
        # 특정 assignee 가 프리랜서인지 빠르게 판단하기 위한 id → person 매핑.
        freelancer_ids = {int(row["id"]) for row in freelancers}
        pm_assignees = [
            row for row in all_assignees
            if event and event["pm_vendor_id"] and row["company_id"] == event["pm_vendor_id"]
        ]
        self.table.clearContents(); self.table.setRowCount(len(tasks))
        self._vendors = visible_vendors
        self._hide_vendor_ids = hidden_vendor_ids
        self._all_assignees = all_assignees
        self._freelancers = freelancers
        self._freelancer_ids = freelancer_ids
        self._assignees_by_vendor = assignees_by_vendor
        self._pm_assignees = pm_assignees
        for row_index, task in enumerate(tasks):
            task_id = int(task["id"])
            order = QTableWidgetItem(str(row_index + 1))
            order.setData(Qt.ItemDataRole.UserRole, task_id)
            order.setFlags(order.flags() & ~(Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable))
            self.table.setItem(row_index, 0, order)
            for column, text in ((1, task["major"]), (2, task["minor"])):
                group = QTableWidgetItem("")  # 분류 이름은 병합 셀 위젯이 표시한다.
                group.setData(GROUP_MAJOR_ROLE, task["major"])
                group.setData(GROUP_MINOR_ROLE, task["minor"])
                group.setData(Qt.ItemDataRole.UserRole, task_id)
                group.setFlags(group.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column, group)
            name = QTableWidgetItem(task["name"]); name.setData(Qt.ItemDataRole.UserRole, task_id)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tooltip = task["detail"] or "세부내용 없음"
            if task["is_removed"]: tooltip += f"\n제외 사유: {task['removed_reason'] or '미입력'}"
            name.setToolTip(tooltip); self.table.setItem(row_index, 3, name)
            detail = QTableWidgetItem(task["detail"] or "")
            detail.setData(Qt.ItemDataRole.UserRole, task_id)
            detail.setFlags(detail.flags() & ~Qt.ItemFlag.ItemIsEditable)
            detail.setToolTip(task["detail"] or "세부내용 없음")
            self.table.setItem(row_index, 4, detail)
            quantity = QTableWidgetItem(str(int(task["quantity"] or 0)))
            quantity.setData(Qt.ItemDataRole.UserRole, task_id)
            quantity.setData(int(Qt.ItemDataRole.UserRole) + 1, task["quantity"])
            quantity.setFlags(quantity.flags() & ~Qt.ItemFlag.ItemIsEditable)
            quantity.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row_index, 5, quantity)
            unit = QTableWidgetItem(task["unit"] or "식")
            unit.setData(Qt.ItemDataRole.UserRole, task_id)
            unit.setData(int(Qt.ItemDataRole.UserRole) + 1, task["unit"] or "식")
            unit.setFlags(unit.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 6, unit)
            status = QTableWidgetItem(task["status"]); status.setData(Qt.ItemDataRole.UserRole, task_id)
            status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable); self._style_status_item(status, task["status"])
            self.table.setItem(row_index, 7, status)
            assignee_name = next(
                (self._assignee_label(x) for x in all_assignees if x["id"] == task["assignee_id"]),
                "미지정",
            )
            pm_name = next((x["name"] for x in pm_assignees if x["id"] == task["pm_assignee_id"]), "미지정")
            for column, text, data in [
                (8, task["planned_start"] or "미입력", task["planned_start"]),
                (9, task["due_date"] or "미입력", task["due_date"]),
                (10, pm_name, task["pm_assignee_id"]),
            ]:
                cell = QTableWidgetItem(text); cell.setData(Qt.ItemDataRole.UserRole, task_id)
                cell.setData(int(Qt.ItemDataRole.UserRole) + 1, data); cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row_index, column, cell)
            # 프리랜서 할당(assignee 가 업체 소속이 아닌 개인)이면 업체칸은 '프리랜서'로 표시.
            is_freelancer = int(task["assignee_id"]) in self._freelancer_ids if task["assignee_id"] else False
            # 숨긴 '(업체 미정)' 업체가 배정된 업무는 '미지정'으로 표시.
            vendor_is_hidden = task["vendor_id"] and int(task["vendor_id"]) in self._hide_vendor_ids
            vendor_text = (
                "프리랜서" if is_freelancer
                else ("미지정" if vendor_is_hidden else (task["vendor_name"] or "미지정"))
            )
            vendor = QTableWidgetItem(vendor_text)
            vendor.setData(Qt.ItemDataRole.UserRole, task_id)
            # 숨긴 '(업체 미정)' 업체는 '미지정'(None)으로 취급해 콤보에서 매칭되지 않게 한다.
            vendor_cell_value = FREELANCER_KEY if is_freelancer else (None if vendor_is_hidden else task["vendor_id"])
            vendor.setData(int(Qt.ItemDataRole.UserRole) + 1, vendor_cell_value)
            vendor.setFlags(vendor.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 11, vendor)
            contact = QTableWidgetItem(assignee_name); contact.setData(Qt.ItemDataRole.UserRole, task_id)
            contact.setData(int(Qt.ItemDataRole.UserRole) + 1, task["assignee_id"])
            contact.setFlags(contact.flags() & ~Qt.ItemFlag.ItemIsEditable); self.table.setItem(row_index, 12, contact)
            phone = QTableWidgetItem(task["assignee_phone"] or "")
            phone.setData(Qt.ItemDataRole.UserRole, task_id); phone.setFlags(phone.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row_index, 13, phone)
            self.table.setRowHeight(row_index, 48)
        self.table.apply_category_spans(1, 2)
        self._apply_zebra_stripes()
        from .widgets import install_category_cell_widgets
        install_category_cell_widgets(self.table, 1, 2, self._edit_category_name, self._move_category)
        self.table._update_major_float()
        self.summary.setText(f"{len(tasks)}개 항목" + (" · 제외 기록" if self.removed_toggle.isChecked() else ""))
        self.loading = False
        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)
        self.table.viewport().update()

    def _sync_major_filter(self):
        current = self.major_filter.currentData() or ""
        majors = load_master_choice_catalog(self.db).majors
        existing = tuple(self.major_filter.itemData(index) for index in range(1, self.major_filter.count()))
        if existing == majors:
            return
        self.major_filter.blockSignals(True)
        self.major_filter.clear()
        self.major_filter.addItem("모든 대분류", "")
        for major in majors:
            self.major_filter.addItem(major, major)
        self.major_filter.setCurrentIndex(max(0, self.major_filter.findData(current)))
        self.major_filter.blockSignals(False)

    def _sync_assignment_filters(self):
        if not self.event_id:
            vendors = []
            pm_assignees = []
        else:
            vendors = self.db.query(
                """SELECT DISTINCT c.id,c.name FROM event_tasks t
                  JOIN contacts c ON c.id=t.vendor_id
                  WHERE t.event_id=? AND t.is_removed=0
                    AND c.name <> ?
                  ORDER BY c.name,c.id""",
                (self.event_id, HIDDEN_VENDOR_NAME),
            )
            pm_assignees = self.db.query(
                """SELECT DISTINCT c.id,c.name FROM event_tasks t
                   JOIN contacts c ON c.id=t.pm_assignee_id
                   WHERE t.event_id=? AND t.is_removed=0 ORDER BY c.name,c.id""",
                (self.event_id,),
            )
        self._replace_filter_items(self.vendor_filter, "모든 업체", vendors)
        self._replace_filter_items(self.pm_filter, "모든 담당자(PM)", pm_assignees)

    @staticmethod
    def _replace_filter_items(combo, all_label, rows):
        current = combo.currentData()
        values = tuple((row["name"], int(row["id"])) for row in rows)
        existing = tuple((combo.itemText(index), combo.itemData(index)) for index in range(1, combo.count()))
        if existing == values:
            return
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(all_label, None)
        for label, value in values:
            combo.addItem(label, value)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    @staticmethod
    def _style_status_item(item: QTableWidgetItem, status: str) -> None:
        fg, bg = status_color(status)
        item.setForeground(QColor(fg)); item.setBackground(QColor(bg))
        font = item.font(); font.setBold(True); item.setFont(font)

    ZEBRA_EVEN = QColor("#FFFFFF")
    ZEBRA_ODD = QColor("#F4F6F8")

    def _apply_zebra_stripes(self) -> None:
        """중분류(또는 대분류) 그룹이 시작될 때마다 흰색부터 새로 줄무늬를 칠한다.

        각 그룹은 흰색(첫 행)에서 시작해 내부에서 흰색/연한회색이 교대되므로,
        분류를 이동해도 그룹 내부의 색 패턴이 깨지지 않고(그룹 자체가 이동할 뿐),
        새 위치에서도 흰색부터 정돈되게 보인다. 진행상태(7열) 셀은 상태 색을 유지한다.
        """
        total = self.table.rowCount()
        if total == 0:
            return
        offset = 0
        prev_group = None
        for row in range(total):
            group = None
            item = self.table.item(row, 2)  # 중분류 열
            if item is not None:
                minor = item.data(GROUP_MINOR_ROLE)
                major = item.data(GROUP_MAJOR_ROLE)
                group = (major, minor)
            if group != prev_group:
                offset = 0  # 새 그룹 시작 → 흰색부터
                prev_group = group
            bg = self.ZEBRA_EVEN if offset % 2 == 0 else self.ZEBRA_ODD
            for column in range(self.table.columnCount()):
                if column == 7:
                    continue  # 상태 색 유지
                cell = self.table.item(row, column)
                if cell is not None:
                    cell.setBackground(bg)
            offset += 1

    def _task_for_row(self, row: int):
        return self._current_tasks[row] if 0 <= row < len(self._current_tasks) else None

    @staticmethod
    def _assignee_label(person) -> str:
        return person_display_label(person)

    def _is_freelancer_task(self, task) -> bool:
        """task 의 담당자가 프리랜서(업체 소속이 아닌 개인)인지 여부."""
        return bool(task["assignee_id"]) and int(task["assignee_id"]) in self._freelancer_ids

    def _handle_row_drag(self, source_row: int, target_row: int, before: bool) -> bool:
        """드래그 드롭으로 항목 순서를 변경한다.

        같은 중분류 내에서는 순서만 바꾸고, 중분류·대분류가 달라지는 자리에 놓으면
        분류 변경 안내 후 승인받아 반영한다. 승인되면 DB sort_order 를 재배치하고
        화면을 재조회한다.
        """
        if self.loading or not self.event_id:
            return False
        source = self._task_for_row(source_row)
        target = self._task_for_row(target_row) if target_row < len(self._current_tasks) else None
        if source is None or target is None or int(source["id"]) == int(target["id"]):
            return False
        if source.get("is_removed") or target.get("is_removed"):
            return False
        same_major = source["major"] == target["major"]
        same_minor = same_major and source["minor"] == target["minor"]
        try:
            if same_minor:
                self.service.reorder_tasks(self.event_id, int(source["id"]), int(target["id"]), before=before)
            else:
                ret = QMessageBox.question(
                    self, "분류 변경",
                    f"'{source['name']}' 항목의 분류가\n"
                    f"[{source['major']} > {source['minor']}] 에서\n"
                    f"[{target['major']} > {target['minor']}] (으)로 바뀝니다.\n"
                    f"이동하시겠습니까?",
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return False
                self.service.reorder_tasks(
                    self.event_id, int(source["id"]), int(target["id"]),
                    new_major=target["major"], new_minor=target["minor"], before=before,
                )
        except Exception as exc:
            QMessageBox.warning(self, "순서 변경 실패", str(exc))
            return False
        self.refresh_tasks()
        self.table.play_reorder_animation()
        self.changed.emit(self.event_id or 0)
        return True

    def _freelancer_state_from_cell(self, row: int) -> bool:
        """업체(column 11) 셀이 '프리랜서'로 설정되어 있는지 여부.
        방금 프리랜서 그룹을 골라 assignee 가 아직 안 정해진 상태도 처리한다."""
        cell = self.table.item(row, 11)
        if cell is None:
            return self._is_freelancer_task(self._task_for_row(row))
        return cell.data(int(Qt.ItemDataRole.UserRole) + 1) == FREELANCER_KEY

    def _edit_category_name(self, major: str, minor: str | None) -> None:
        """분류 이름을 더블클릭으로 변경한다. (대분류 또는 중분류)"""
        if self.loading or not self.event_id:
            return
        current = major if minor is None else minor
        label = "대분류" if minor is None else "중분류"
        text, ok = QInputDialog.getText(self, f"{label} 이름 변경", f"새 {label} 이름:", text=current)
        if not ok:
            return
        text = text.strip()
        if not text or text == current:
            return
        try:
            if minor is None:
                self.service.rename_category(self.event_id, old_major=major, new_major=text)
            else:
                self.service.rename_category(self.event_id, old_major=major, old_minor=minor, new_minor=text)
        except Exception as exc:
            QMessageBox.warning(self, "분류 이름 변경 실패", str(exc))
            return
        self.refresh_tasks()
        self.table.play_reorder_animation()
        self.changed.emit(self.event_id or 0)

    def _move_category(self, source_major: str, source_minor: str | None,
                       target_major: str, target_minor: str | None, before: bool = True) -> None:
        """분류 그룹을 목표 분류 앞(before) 또는 뒤(after)로 이동한다 (핸들 드래그)."""
        if self.loading or not self.event_id:
            return
        if (source_major, source_minor) == (target_major, target_minor):
            return
        try:
            self.service.move_category(
                self.event_id,
                major=source_major, minor=source_minor,
                target_major=target_major, target_minor=target_minor,
                before=before,
            )
        except Exception as exc:
            QMessageBox.warning(self, "분류 이동 실패", str(exc))
            return
        self.refresh_tasks()
        self.table.play_reorder_animation()
        self.changed.emit(self.event_id or 0)

    def _open_cell_editor(self, row: int, column: int) -> None:
        if self.loading or column not in {3, 4, 5, 6, 7, 8, 9, 10, 11, 12}:
            return
        task = self._task_for_row(row)
        if not task or task["is_removed"]:
            return
        if column in {3, 4}:
            field = "name" if column == 3 else "detail"
            self.table.open_text_editor(
                row, column, task[field] or "",
                lambda value: self._commit_text(row, task, column, field, value),
            )
        elif column == 5:
            self.table.open_number_editor(row, column, task["quantity"],
                                          lambda value: self._commit_quantity(row, task, value))
        elif column == 6:
            choices = [(unit, unit) for unit in load_master_choice_catalog(self.db).units]
            self.table.open_choice_editor(row, column, choices, task["unit"] or "식",
                                          lambda value: self._commit_unit(row, task, value), editable=True)
        elif column == 7:
            choices = [(status, status) for status in STATUSES]
            self.table.open_choice_editor(row, column, choices, task["status"],
                                          lambda value: self._commit_status(row, task, value))
        elif column in {8, 9}:
            field = "planned_start" if column == 8 else "due_date"
            self.table.open_date_editor(row, column, task[field],
                                        lambda value: self._commit_date(row, task, column, field, value))
        elif column == 10:
            choices = [("미지정", None)] + [(x["name"], x["id"]) for x in self._pm_assignees]
            self.table.open_choice_editor(row, column, choices, task["pm_assignee_id"],
                                          lambda value: self._commit_simple(row, task, column, "pm_assignee_id", value, choices))
        elif column == 11:
            # 업체 콤보: 프리랜서 그룹을 맨 위(미지정 다음)에 두고 그 뒤에 업체를 나열한다.
            choices = [("미지정", None), ("프리랜서", FREELANCER_KEY)] + [(x["name"], x["id"]) for x in self._vendors]
            cell = self.table.item(row, 11)
            cell_data = cell.data(int(Qt.ItemDataRole.UserRole) + 1) if cell is not None else None
            current = FREELANCER_KEY if self._freelancer_state_from_cell(row) else cell_data
            self.table.open_choice_editor(row, column, choices, current,
                                          lambda value: self._commit_vendor(row, task, value, choices))
        elif column == 12:
            # 프리랜서 상태이면 프리랜서 개인 목록을, 아니면 선택한 업체 소속 담당자 목록을 보여준다.
            if self._freelancer_state_from_cell(row):
                rows = self._freelancers
            else:
                rows = self._assignees_by_vendor.get(int(task["vendor_id"]), []) if task["vendor_id"] else []
            choices = [("미지정", None)] + [(self._assignee_label(x), x["id"]) for x in rows]
            self.table.open_choice_editor(row, column, choices, task["assignee_id"],
                                          lambda value: self._commit_vendor_contact(row, task, value, choices))

    def _commit_quantity(self, row, task, value):
        value = int(value or 0)
        self.service.update_task(int(task["id"]), quantity=value)
        task["quantity"] = value
        cell = self.table.item(row, 5)
        cell.setText(str(value))
        cell.setData(int(Qt.ItemDataRole.UserRole) + 1, value)
        self.changed.emit(self.event_id or 0)

    def _commit_unit(self, row, task, value):
        self.service.update_task(int(task["id"]), unit=value or "식")
        task["unit"] = value or "식"
        cell = self.table.item(row, 6)
        cell.setText(task["unit"])
        cell.setData(int(Qt.ItemDataRole.UserRole) + 1, task["unit"])
        self.changed.emit(self.event_id or 0)

    def _commit_text(self, row, task, column, field, value):
        if field == "name" and not value:
            QMessageBox.warning(self, "입력 확인", "항목명은 비워둘 수 없습니다.")
            return False
        self.service.update_task(int(task["id"]), **{field: value})
        task[field] = value
        cell = self.table.item(row, column)
        cell.setText(value)
        if field == "detail":
            cell.setToolTip(value or "세부내용 없음")
            self.table.item(row, 3).setToolTip(value or "세부내용 없음")
        self.changed.emit(self.event_id or 0)

    def _commit_simple(self, row, task, column, field, value, choices):
        self.service.update_task(int(task["id"]), **{field: value}); task[field] = value
        text = next((label for label, data in choices if data == value), "미지정")
        cell = self.table.item(row, column); cell.setText(text); cell.setData(int(Qt.ItemDataRole.UserRole) + 1, value)
        self.changed.emit(self.event_id or 0)

    def _commit_status(self, row, task, value):
        self.service.update_task(int(task["id"]), status=value); task["status"] = value
        cell = self.table.item(row, 7); cell.setText(value); self._style_status_item(cell, value)
        self.changed.emit(self.event_id or 0)

    def _commit_date(self, row, task, column, field, value):
        try:
            self.service.update_task(int(task["id"]), **{field: value})
        except ValueError as exc:
            QMessageBox.warning(self, "날짜 확인", str(exc)); return False
        task[field] = value
        self.table.item(row, column).setText(value or "미입력")
        self.changed.emit(self.event_id or 0)

    def _commit_vendor_contact(self, row, task, value, choices):
        self._commit_simple(row, task, 12, "assignee_id", value, choices)
        person = next((x for x in self._all_assignees if x["id"] == value), None)
        task["assignee_phone"] = person["phone"] if person else ""
        self.table.item(row, 13).setText(task["assignee_phone"] or "")

    def _commit_vendor(self, row, task, vendor_id, choices):
        task_id = int(task["id"]); assignee_id = task["assignee_id"]
        is_freelancer = vendor_id == FREELANCER_KEY
        # 프리랜서는 업체(vendor)가 없으므로 vendor_id 는 NULL 로 저장한다.
        fields = {"vendor_id": None if is_freelancer else vendor_id}
        if assignee_id:
            if is_freelancer:
                # 프리랜서로 전환: 업체소속 담당자는 미지정으로 정리하고 프리랜서 개인을 새로 고르게 한다.
                if assignee_id not in self._freelancer_ids:
                    fields["assignee_id"] = None; task["assignee_id"] = None
                    task["assignee_phone"] = ""; self.table.item(row, 12).setText("미지정"); self.table.item(row, 13).setText("")
            else:
                rows = self._assignees_by_vendor.get(int(vendor_id), []) if vendor_id else []
                allowed = {int(x["id"]) for x in rows}
                if int(assignee_id) not in allowed:
                    QMessageBox.information(self, "담당자 변경 안내", "새 업체 소속과 맞지 않는 기존 담당자를 미지정으로 전환합니다.")
                    fields["assignee_id"] = None; task["assignee_id"] = None
                    task["assignee_phone"] = ""; self.table.item(row, 12).setText("미지정"); self.table.item(row, 13).setText("")
        self.service.update_task(task_id, **fields); task["vendor_id"] = None if is_freelancer else vendor_id
        cell = self.table.item(row, 11); cell.setText("프리랜서" if is_freelancer else next((x for x, data in choices if data == vendor_id), "미지정"))
        cell.setData(int(Qt.ItemDataRole.UserRole) + 1, vendor_id); self.changed.emit(self.event_id or 0)

    def _update(self, task_id, **values):
        if self.loading: return
        self.service.update_task(task_id, **values); self.changed.emit(self.event_id or 0)
