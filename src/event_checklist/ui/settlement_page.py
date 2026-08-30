from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QDoubleSpinBox, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..theme import TOKENS
from ..choices import load_master_choice_catalog
from ..pdf_export import export_settlement_pdf
from .dialogs import BulkAssignmentDialog
from .pdf_export_dialog import configure_pdf_icon_button, export_pdf_from_page
from .widgets import (
    GROUP_MAJOR_ROLE, GROUP_MINOR_ROLE, AppComboBox, FastEditableTable, KpiCard,
    configure_editable_table, configure_money_spin, fit_table_to_view,
)


def money(value) -> str:
    return f"{int(value or 0):,}원"


class SettlementPage(QWidget):
    changed = Signal(int)

    def __init__(self, service, db, parent=None):
        super().__init__(parent)
        self.service = service
        self.db = db
        self.event_id: int | None = None
        self._loaded_event_id: int | None = None
        self.loading = False
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 32)
        root.setSpacing(14)
        top = QHBoxLayout()
        box = QVBoxLayout()
        title = QLabel("정산내역")
        title.setObjectName("PageTitle")
        self.description = QLabel("프로젝트를 선택하면 예산과 항목 합계를 비교할 수 있습니다.")
        self.description.setObjectName("PageDescription")
        box.addWidget(title)
        box.addWidget(self.description)
        top.addLayout(box)
        top.addStretch()
        top.addWidget(QLabel("입력 예산"))
        self.budget = QDoubleSpinBox()
        self.budget.setRange(0, 999_999_999_999)
        configure_money_spin(self.budget)
        self.budget.setMinimumWidth(180)
        self.budget.editingFinished.connect(self._save_budget)
        self.tax_mode = AppComboBox()
        self.tax_mode.addItem("VAT 포함/별도 선택", "UNSET")
        self.tax_mode.addItem("VAT 포함 예산", "INCLUDED")
        self.tax_mode.addItem("VAT 별도 예산", "EXCLUDED")
        self.tax_mode.currentIndexChanged.connect(self._save_budget)
        fit = QPushButton("열 너비 맞춤")
        fit.clicked.connect(lambda: fit_table_to_view(self.table))
        self.bulk_assign_button = QPushButton("선택 행 담당 지정")
        self.bulk_assign_button.clicked.connect(self.assign_selected)
        self.pdf_button = QPushButton()
        configure_pdf_icon_button(self.pdf_button)
        self.pdf_button.clicked.connect(self.export_pdf)
        top.addWidget(self.budget)
        top.addWidget(self.tax_mode)
        top.addWidget(self.bulk_assign_button)
        top.addWidget(fit)
        top.addWidget(self.pdf_button)
        root.addLayout(top)

        cards = QGridLayout()
        self.cards = {}
        for column, (key, label) in enumerate([
            ("budget", "입력 예산"), ("supply", "공급가 합계"), ("vat", "VAT"),
            ("total", "VAT 포함 합계"), ("difference", "예산 차이"),
        ]):
            card = KpiCard(label)
            self.cards[key] = card
            cards.addWidget(card, 0, column)
        root.addLayout(cards)
        self.warning = QLabel("")
        self.warning.setObjectName("InfoGuide")
        self.warning.setWordWrap(True)
        root.addWidget(self.warning)
        self.table = FastEditableTable(0, 12)
        self.table.set_money_columns({5, 6, 8, 9})
        self.table.setHorizontalHeaderLabels([
            "대분류", "중분류", "항목", "수량", "단위", "프로젝트 단가", "공급가",
            "VAT 구분", "VAT", "합계", "업체", "메모",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        configure_editable_table(
            self.table, [90, 110, 180, 90, 80, 130, 130, 105, 110, 130, 150, 270],
            grouped=True, anchor_column=0, wrap_columns=(1, 2),
        )
        self.table.setProperty("fitWrapColumns", [1, 2])  # 중분류, 항목
        self.table.set_left_columns({11})  # 메모는 좌측 정렬
        self.table.cellDoubleClicked.connect(self._open_cell_editor)
        self.table.enable_row_drag(self._handle_row_drag)
        root.addWidget(self.table, 1)

    def _selected_task_ids(self):
        ids = []
        selected_rows = sorted({index.row() for index in self.table.selectionModel().selectedIndexes()})
        for row in selected_rows:
            cell = self.table.item(row, 2)
            task_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
            if task_id is not None and int(task_id) in self._items:
                ids.append(int(task_id))
        return list(dict.fromkeys(ids))

    def assign_selected(self):
        ids = self._selected_task_ids()
        if not ids:
            QMessageBox.information(self, "항목 선택", "담당자를 지정할 정산 항목 행을 선택하세요.\nCtrl 또는 Shift를 누르면 여러 행을 선택할 수 있습니다.")
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
        self.refresh()
        self.changed.emit(self.event_id or 0)
        QMessageBox.information(self, "일괄 지정 완료", f"선택한 {changed_count}개 항목에 적용했습니다.")

    def set_event(self, event_id: int | None, *, force: bool = False):
        if not force and self._loaded_event_id == event_id:
            return
        self.event_id = event_id
        self.refresh()
        self._loaded_event_id = event_id

    def export_pdf(self):
        export_pdf_from_page(self, self.db, self.event_id, "settlement", export_settlement_pdf)

    def invalidate(self):
        self._loaded_event_id = None

    def refresh(self):
        self.loading = True
        self.table.setUpdatesEnabled(False); self.table.blockSignals(True)
        self.table.reset_spans()
        self.table.clearContents(); self.table.setRowCount(0)
        if not self.event_id:
            self.loading = False
            self.table.blockSignals(False); self.table.setUpdatesEnabled(True)
            return
        summary = self.service.settlement_summary(self.event_id)
        self._apply_summary_header(summary)
        vendors = self.db.query("SELECT * FROM contacts WHERE kind='VENDOR' ORDER BY name,id")
        self._vendors = vendors; self._items = {}; self._task_rows = {}; self._subtotal_rows = {}
        self._task_by_row: dict[int, int] = {}
        current_major = None
        for item in summary["items"]:
            if current_major is not None and item["major"] != current_major:
                self._add_subtotal_row(current_major, summary["categories"][current_major])
            current_major = item["major"]
            self._add_item_row(item, vendors)
        if current_major is not None:
            self._add_subtotal_row(current_major, summary["categories"][current_major])
        self._add_total_row(summary)
        self.table.apply_category_spans(0, 1)
        self._apply_zebra_stripes()
        from .widgets import install_category_cell_widgets
        install_category_cell_widgets(self.table, 0, 1, self._edit_category_name, self._move_category)
        self.loading = False
        self.table.blockSignals(False); self.table.setUpdatesEnabled(True); self.table.viewport().update()

    def _apply_zebra_stripes(self) -> None:
        """중분류(대분류=0, 중분류=1 열) 그룹이 시작될 때마다 흰색부터 줄무늬 재시작.

        항목 행만 흰색/연한회색 교대로 칠하고, 소계/합계 행은 기존 배경을 유지한다.
        분류를 이동해도 그룹 내부 색 패턴이 유지되고 새 위치에서 흰색부터 정돈된다.
        """
        total = self.table.rowCount()
        if total == 0:
            return
        offset = 0
        prev_group = None
        for row in range(total):
            item = self.table.item(row, 1)  # 중분류 열
            if item is None or item.data(GROUP_MINOR_ROLE) is None:
                continue  # 소계/합계 행 등 — 배경 유지
            group = (item.data(GROUP_MAJOR_ROLE), item.data(GROUP_MINOR_ROLE))
            if group != prev_group:
                offset = 0
                prev_group = group
            bg = QColor("#FFFFFF") if offset % 2 == 0 else QColor("#F4F6F8")
            for column in range(self.table.columnCount()):
                cell = self.table.item(row, column)
                if cell is not None:
                    cell.setBackground(bg)
            offset += 1

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
        self.refresh()
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
        self.refresh()
        self.table.play_reorder_animation()
        self.changed.emit(self.event_id or 0)

    def _handle_row_drag(self, source_row: int, target_row: int, before: bool) -> bool:
        """드래그 드롭으로 항목 순서를 변경한다(체크리스트와 동일 규칙).

        같은 중분류 내에서는 순서만 바꾸고, 중분류·대분류가 달라지면 안내 후
        승인받아 반영한다. 소계·합계 행은 task 행이 아니므로 드래그 대상이 아니다.
        """
        if self.loading or not self.event_id:
            return False
        src_id = self._task_by_row.get(source_row)
        tgt_id = self._task_by_row.get(target_row)
        if src_id is None or tgt_id is None or src_id == tgt_id:
            return False
        src = self._items[src_id]; tgt = self._items[tgt_id]
        same_major = src["major"] == tgt["major"]
        same_minor = same_major and src["minor"] == tgt["minor"]
        try:
            if same_minor:
                self.service.reorder_tasks(self.event_id, src_id, tgt_id, before=before)
            else:
                ret = QMessageBox.question(
                    self, "분류 변경",
                    f"'{src['name']}' 항목의 분류가\n"
                    f"[{src['major']} > {src['minor']}] 에서\n"
                    f"[{tgt['major']} > {tgt['minor']}] (으)로 바뀝니다.\n"
                    f"이동하시겠습니까?",
                )
                if ret != QMessageBox.StandardButton.Yes:
                    return False
                self.service.reorder_tasks(
                    self.event_id, src_id, tgt_id,
                    new_major=tgt["major"], new_minor=tgt["minor"], before=before,
                )
        except Exception as exc:
            QMessageBox.warning(self, "순서 변경 실패", str(exc))
            return False
        self.refresh()
        self.changed.emit(self.event_id or 0)
        return True


    def _apply_summary_header(self, summary):
        event = summary["event"]
        self.description.setText(f"{event['name']} · 공급가 기준 단가와 VAT를 합산합니다.")
        self.budget.blockSignals(True); self.tax_mode.blockSignals(True)
        self.budget.setValue(event["budget"] or 0)
        self.tax_mode.setCurrentIndex(max(0, self.tax_mode.findData(event["budget_tax_mode"])))
        self.budget.blockSignals(False); self.tax_mode.blockSignals(False)
        for key in ("budget", "supply", "vat", "total"): self.cards[key].set_value(money(summary[key]))
        difference = summary["difference"]
        if difference is None:
            difference_text = "VAT 기준 선택 필요" if summary["budget"] else "예산 미입력"
        else:
            difference_text = "일치" if difference == 0 else f"{money(abs(difference))} {'남음' if difference > 0 else '부족'}"
        self.cards["difference"].set_value(difference_text)
        messages = []
        if event["budget"] and event["budget_tax_mode"] == "UNSET": messages.append("입력 예산이 VAT 포함인지 별도인지 선택하세요.")
        if summary["warnings"]: messages.append(f"수량 또는 단가가 비어 있는 항목이 {summary['warnings']}개 있습니다.")
        self.warning.setText("  ".join(messages) if messages else "모든 금액 입력이 정상입니다.")

    def _add_item_row(self, item, vendors):
        row = self.table.rowCount()
        self.table.insertRow(row)
        task_id = int(item["id"])
        self._items[task_id] = dict(item); self._task_rows[task_id] = row; self._task_by_row[row] = task_id
        values = [
            item["major"], item["minor"], item["name"], str(int(item["quantity"] or 0)), item["unit"] or "식",
            money(item["unit_price"]), money(item["supply"]), "10%" if item["vat_type"] == "TAXABLE" else "면세",
            money(item["vat"]), money(item["total"]), item["vendor_name"] or "미지정", item["note"] or "",
        ]
        raw_values = {
            3: item["quantity"], 4: item["unit"] or "식", 5: item["unit_price"], 7: item["vat_type"],
            10: item["vendor_id"], 11: item["note"] or "",
        }
        for column, value in enumerate(values):
            # 대분류/중분류(0,1) 이름은 병합 셀 위젯(CategoryCell)이 표시하므로 Item 텍스트는 비운다.
            text = "" if column in {0, 1} else str(value)
            cell = QTableWidgetItem(text)
            cell.setData(Qt.ItemDataRole.UserRole, task_id)
            if column in {0, 1}:
                cell.setData(GROUP_MAJOR_ROLE, item["major"])
                cell.setData(GROUP_MINOR_ROLE, item["minor"])
            if column in raw_values: cell.setData(int(Qt.ItemDataRole.UserRole) + 1, raw_values[column])
            cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if column in {3, 5, 6, 8, 9}: cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(row, column, cell)
        self.table.setRowHeight(row, 48)

    def _add_subtotal_row(self, major, subtotal):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._subtotal_rows[major] = row
        label = QTableWidgetItem(f"{major} 소계")
        self.table.setItem(row, 0, label)
        self.table.setSpan(row, 0, 1, 6)
        for column, value in [(6,subtotal["supply"]),(8,subtotal["vat"]),(9,subtotal["total"])]:
            cell = QTableWidgetItem(money(value))
            self.table.setItem(row, column, cell)
        for column in range(self.table.columnCount()):
            cell = self.table.item(row, column)
            if cell is None:
                cell = QTableWidgetItem(""); self.table.setItem(row, column, cell)
            cell.setBackground(QColor(TOKENS["brand_weak"]))
            cell.setForeground(QColor(TOKENS["brand_pressed"]))
            font = cell.font(); font.setBold(True); font.setPointSize(max(12, font.pointSize() + 2)); cell.setFont(font)
        self.table.setRowHeight(row, 48)

    def _add_total_row(self, summary):
        row = self.table.rowCount(); self.table.insertRow(row)
        self._total_row = row
        label = QTableWidgetItem("전체 합계"); self.table.setItem(row, 0, label); self.table.setSpan(row, 0, 1, 6)
        for column, value in [(6, summary["supply"]), (8, summary["vat"]), (9, summary["total"])]:
            cell = QTableWidgetItem(money(value)); self.table.setItem(row, column, cell)
        for column in range(self.table.columnCount()):
            cell = self.table.item(row, column)
            if cell is None:
                cell = QTableWidgetItem(""); self.table.setItem(row, column, cell)
            cell.setBackground(QColor(TOKENS["brand"]))
            cell.setForeground(QColor("#FFFFFF"))
            font = cell.font(); font.setBold(True); font.setPointSize(max(12, font.pointSize() + 2)); cell.setFont(font)
        self.table.setRowHeight(row, 50)

    def _open_cell_editor(self, row: int, column: int):
        if self.loading or column not in {2, 3, 4, 5, 7, 10, 11}:
            return
        cell = self.table.item(row, column)
        if cell is None:
            return
        task_id = cell.data(Qt.ItemDataRole.UserRole)
        if task_id is None or int(task_id) not in self._items:
            return
        task_id = int(task_id); item = self._items[task_id]
        if column == 2:
            self.table.open_text_editor(
                row, column, item["name"],
                lambda value: self._commit_item_name(task_id, value),
            )
        elif column == 3:
            self.table.open_number_editor(row, column, item["quantity"], lambda value: self._commit_value(task_id, column, "quantity", value))
        elif column == 4:
            choices = [(unit, unit) for unit in load_master_choice_catalog(self.db).units]
            self.table.open_choice_editor(row, column, choices, item["unit"],
                                          lambda value: self._commit_value(task_id, column, "unit", value), editable=True)
        elif column == 5:
            self.table.open_number_editor(row, column, item["unit_price"],
                                          lambda value: self._commit_value(task_id, column, "unit_price", value), money=True)
        elif column == 7:
            choices = [("10%", "TAXABLE"), ("면세", "EXEMPT")]
            self.table.open_choice_editor(row, column, choices, item["vat_type"],
                                          lambda value: self._commit_value(task_id, column, "vat_type", value))
        elif column == 10:
            choices = [("미지정", None)] + [(x["name"], x["id"]) for x in self._vendors]
            self.table.open_choice_editor(row, column, choices, item["vendor_id"],
                                          lambda value: self._commit_value(task_id, column, "vendor_id", value))
        else:
            self.table.open_text_editor(row, column, item["note"] or "",
                                        lambda value: self._commit_value(task_id, column, "note", value))

    def _commit_item_name(self, task_id: int, value: str):
        if not value:
            QMessageBox.warning(self, "입력 확인", "항목명은 비워둘 수 없습니다.")
            return False
        self.service.update_task(task_id, name=value)
        self._items[task_id]["name"] = value
        self.table.item(self._task_rows[task_id], 2).setText(value)
        self.changed.emit(self.event_id or 0)

    def _commit_value(self, task_id: int, column: int, field: str, value):
        self.service.update_task(task_id, **{field: value})
        item = self._items[task_id]; item[field] = value
        cell = self.table.item(self._task_rows[task_id], column)
        labels = {"vat_type": "10%" if value == "TAXABLE" else "면세"}
        if field == "vendor_id":
            text = next((x["name"] for x in self._vendors if x["id"] == value), "미지정")
            item["vendor_name"] = text if value else None
        elif field == "unit_price": text = money(value)
        elif field == "quantity": text = str(int(value or 0))
        else: text = labels.get(field, str(value or ""))
        cell.setText(text); cell.setData(int(Qt.ItemDataRole.UserRole) + 1, value)
        if field in {"quantity", "unit_price", "vat_type"}:
            self._refresh_totals()
        self.changed.emit(self.event_id or 0)

    def _refresh_totals(self):
        summary = self.service.settlement_summary(self.event_id)
        self._apply_summary_header(summary)
        for item in summary["items"]:
            task_id = int(item["id"]); row = self._task_rows.get(task_id)
            if row is None: continue
            self._items[task_id].update(item)
            self.table.item(row, 6).setText(money(item["supply"]))
            self.table.item(row, 8).setText(money(item["vat"]))
            self.table.item(row, 9).setText(money(item["total"]))
        for major, subtotal in summary["categories"].items():
            row = self._subtotal_rows.get(major)
            if row is None: continue
            self.table.item(row, 6).setText(money(subtotal["supply"]))
            self.table.item(row, 8).setText(money(subtotal["vat"]))
            self.table.item(row, 9).setText(money(subtotal["total"]))
        self.table.item(self._total_row, 6).setText(money(summary["supply"]))
        self.table.item(self._total_row, 8).setText(money(summary["vat"]))
        self.table.item(self._total_row, 9).setText(money(summary["total"]))

    def _save_budget(self):
        if self.loading or not self.event_id:
            return
        self.db.execute(
            "UPDATE events SET budget=?,budget_tax_mode=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (self.budget.value() or None, self.tax_mode.currentData(), self.event_id),
        )
        self._refresh_totals()
