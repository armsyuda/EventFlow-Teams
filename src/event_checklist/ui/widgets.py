from __future__ import annotations

from collections import defaultdict
from datetime import date

from PySide6.QtCore import QDate, QEasingCurve, QEvent, QLocale, QObject, QPoint, QPointF, QPropertyAnimation, QRect, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPalette, QPen, QRegion, QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QAbstractSpinBox, QApplication, QCalendarWidget, QComboBox, QDateEdit,
    QDialog, QDoubleSpinBox, QFrame, QGraphicsOpacityEffect, QHeaderView, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStyledItemDelegate, QStyle, QStyleOptionViewItem, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from ..theme import TOKENS
from ..units import COMMON_UNITS


GROUP_MAJOR_ROLE = int(Qt.ItemDataRole.UserRole) + 101
GROUP_MINOR_ROLE = int(Qt.ItemDataRole.UserRole) + 102


class AppComboBox(QComboBox):
    """Shared combo box with a clipped, consistently styled popup."""

    popup_closed = Signal()
    popup_open = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_open = False
        self._swallow_release = False  # popup을 연 직후 ghost release 1회를 무시

    def showPopup(self) -> None:
        self._popup_open = True
        # 더블클릭 잔여 마우스 릴리스가 방금 연 popup을 닫지 못하도록,
        # 다음 번째 마우스 릴리스까지 가드를 켠다.
        self._swallow_release = True
        self.popup_open.emit()
        self._polish_popup()
        try:
            super().showPopup()
        except Exception:
            self._popup_open = False
            raise
        QTimer.singleShot(0, self._polish_popup)

    def event(self, event) -> bool:
        t = event.type()
        if t == QEvent.Type.MouseButtonRelease and self._swallow_release:
            self._swallow_release = False
            return True
        return super().event(event)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._popup_open = False
        self.popup_closed.emit()

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)

    def popup_is_open(self) -> bool:
        return self._popup_open

    def _polish_popup(self) -> None:
        view = self.view()
        container = self.view().window()
        longest_label = max(
            (view.fontMetrics().horizontalAdvance(self.itemText(index)) for index in range(self.count())),
            default=0,
        )
        # Narrow spreadsheet columns must not force two-character units such
        # as "세트" into an ellipsis.  Keep enough room for text, padding and
        # the slim vertical scrollbar while avoiding an excessively wide menu.
        popup_width = min(360, max(112, self.width(), longest_label + 48))
        view.setMinimumWidth(popup_width)
        view.setTextElideMode(Qt.TextElideMode.ElideNone)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        container.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        container.setAutoFillBackground(False)
        # A bare ``background: transparent`` on the popup container cascades
        # into its list view on Windows and turns the whole menu black.  Scope
        # transparency to the outer native container and give the actual list
        # its own opaque SEED surface.
        container.setStyleSheet(
            "QComboBoxPrivateContainer { background: transparent; border: none; padding: 0; }"
        )
        view.setAutoFillBackground(True)
        view.viewport().setAutoFillBackground(True)
        view.setStyleSheet(f"""
            QAbstractItemView {{
                background-color: {TOKENS['bg_layer']};
                color: {TOKENS['fg_neutral']};
                border: 1px solid {TOKENS['stroke']};
                border-radius: 9px;
                padding: 5px;
                outline: none;
                selection-background-color: {TOKENS['brand_weak']};
                selection-color: {TOKENS['brand_pressed']};
            }}
            QAbstractItemView::item {{
                min-height: 34px;
                padding: 0 9px;
                border-radius: 6px;
                background-color: {TOKENS['bg_layer']};
                color: {TOKENS['fg_neutral']};
            }}
            QAbstractItemView::item:selected {{
                background-color: {TOKENS['brand_weak']};
                color: {TOKENS['brand_pressed']};
            }}
            QScrollBar:vertical {{
                width: 5px;
                margin: 3px 0;
                border: none;
                background: transparent;
            }}
            QScrollBar::handle:vertical {{
                min-height: 24px;
                border: none;
                border-radius: 2px;
                background: #C9CDD3;
            }}
            QScrollBar::handle:vertical:hover {{ background: #AEB3BA; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                width: 0;
                height: 0;
                border: none;
                background: transparent;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)
        if container.width() > 0 and container.height() > 0:
            path = QPainterPath()
            path.addRoundedRect(container.rect(), 9, 9)
            container.setMask(QRegion(path.toFillPolygon().toPolygon()))


class AddableChoiceField(QWidget):
    """Shared existing-choice picker with an explicit add-new action."""

    value_added = Signal(str)

    def __init__(self, choices=(), value: str = "", *, add_label: str = "+ 새로 추가",
                 dialog_title: str = "새 값 추가", prompt: str = "새 이름", parent=None):
        super().__init__(parent)
        self.dialog_title = dialog_title
        self.prompt = prompt
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.combo = AppComboBox()
        # New values are entered through the explicit add button.  Keeping the
        # picker non-editable makes a click anywhere on the field open the
        # existing-value popup instead of merely placing a text cursor.
        self.combo.setEditable(False)
        self.combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems(choices)
        if value:
            self.setCurrentText(value)
        self.open_button = QPushButton("▾")
        self.open_button.setObjectName("ChoiceOpenButton")
        self.open_button.setFixedWidth(42)
        self.open_button.setToolTip("기존 목록 보기")
        self.open_button.clicked.connect(self.combo.showPopup)
        self.add_button = QPushButton(add_label)
        self.add_button.setProperty("secondary", True)
        self.add_button.setMinimumWidth(112)
        self.add_button.clicked.connect(self._request_value)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.open_button)
        layout.addWidget(self.add_button)

    def _request_value(self):
        value, accepted = QInputDialog.getText(self, self.dialog_title, self.prompt)
        if accepted:
            self.add_value(value)

    def add_value(self, value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        index = self.findText(text)
        if index < 0:
            self.combo.addItem(text)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(index)
        self.value_added.emit(text)
        return True

    def addItems(self, choices) -> None:
        for value in choices:
            text = str(value or "").strip()
            if text and self.findText(text) < 0:
                self.combo.addItem(text)

    def clear(self) -> None:
        self.combo.clear()

    def currentText(self) -> str:
        return self.combo.currentText()

    def setCurrentText(self, value: str) -> None:
        text = str(value or "").strip()
        if text and self.findText(text) < 0:
            self.combo.addItem(text)
        self.combo.setCurrentText(text)

    def setCurrentIndex(self, index: int) -> None:
        self.combo.setCurrentIndex(index)

    def findText(self, value: str) -> int:
        return self.combo.findText(value)

    def setToolTip(self, text: str) -> None:
        super().setToolTip(text)
        self.combo.setToolTip(text)
        self.add_button.setToolTip(text)


class _PopupReleaseGuard(QObject):
    """콤보 팝업을 연 직후, 더블클릭 잔여 마우스 릴리스가 팝업을 닫지 않도록 차단.

    로그 분석 결과, editable 콤보에서 popup을 열면 더블클릭의 두 번째 마우스
    릴리스가 '팝업 외부 클릭'으로 인식돼 QComboBox가 hidePopup을 호출한다.
    이 릴리스는 콤보의 event()로 오지 않아 기존 가드(_swallow_release)로는
    못 막는다. 애플리케이션 전역 이벤트 필터로 팝업 열림 직후 짧은 시간 동안
    마우스 릴리스를 소비해 팝업을 지킨다.
    """

    ACTIVE_WINDOW_MS = 250

    def __init__(self):
        super().__init__()
        self._active_until = 0.0
        self._swallow_release = False  # 활성 창 동안 첫 release 1회를 소비
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.installEventFilter(self)

    def arm(self) -> None:
        import time
        self._active_until = time.monotonic() + self.ACTIVE_WINDOW_MS
        self._swallow_release = True

    def eventFilter(self, watched, event) -> bool:
        import time
        if not self._swallow_release:
            return False
        if time.monotonic() > self._active_until:
            self._swallow_release = False
            return False
        # 활성 창 동안 도착하는 마우스 릴리스(팝업 밖 잔여 클릭)를 소비한다.
        if event.type() == QEvent.Type.MouseButtonRelease:
            self._swallow_release = False
            return True
        return False


_popup_guard: _PopupReleaseGuard | None = None


def _get_popup_guard() -> _PopupReleaseGuard:
    global _popup_guard
    if _popup_guard is None:
        _popup_guard = _PopupReleaseGuard()
    return _popup_guard


def arm_popup_release_guard() -> None:
    """단위 콤보 등 popup을 열기 직전에 호출해 잔여 릴리스를 걸러낸다."""
    _get_popup_guard().arm()


class FastEditableTable(QTableWidget):
    """Spreadsheet table that creates only the editor for the active cell."""

    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self._active_editor = None
        self._active_cell = None
        self._date_popup: QFrame | None = None
        self._group_spans: list[tuple[int, int]] = []
        self._money_columns: set[int] = set()
        self._left_columns: set[int] = set()
        self._fixed_column_widths: dict[int, int] = {}
        self._drag_source_row: int | None = None
        self._on_row_drag_reorder = None
        self.currentCellChanged.connect(self._close_editor_after_cell_change)

    def _close_editor_after_cell_change(self, row: int, column: int, *_previous) -> None:
        if self._active_cell is not None and self._active_cell != (row, column):
            editor = self._active_editor
            if isinstance(editor, QComboBox):
                self.close_cell_editor()
            elif editor is not None:
                # Text and number edits commit through editingFinished.  Give
                # that signal a chance to save before the fallback removal.
                editor.clearFocus()
                QTimer.singleShot(
                    0,
                    lambda: self.close_cell_editor() if self._active_editor is editor else None,
                )
        elif self._date_popup is not None:
            self.close_cell_editor()

    def set_fixed_columns(self, columns: dict[int, int]) -> None:
        self._fixed_column_widths = {int(column): int(width) for column, width in columns.items()}
        header = self.horizontalHeader()
        for column, width in self._fixed_column_widths.items():
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, width)

    def fixed_column_widths(self) -> dict[int, int]:
        return dict(self._fixed_column_widths)

    def set_money_columns(self, columns) -> None:
        self._money_columns = {int(column) for column in columns}
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is not None:
                    self._apply_item_alignment(item, column)

    def set_left_columns(self, columns) -> None:
        """지정 열(세부내용·메모 등)의 셀 텍스트를 좌측 정렬로 고정한다."""
        self._left_columns = {int(column) for column in columns}
        for row in range(self.rowCount()):
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is not None and column in self._left_columns:
                    self._apply_item_alignment(item, column)

    def _apply_item_alignment(self, item, column: int) -> None:
        horizontal = Qt.AlignmentFlag.AlignHCenter
        if column in self._money_columns:
            horizontal = Qt.AlignmentFlag.AlignRight
        elif column in self._left_columns:
            horizontal = Qt.AlignmentFlag.AlignLeft
        item.setTextAlignment(horizontal | Qt.AlignmentFlag.AlignVCenter)

    def setItem(self, row: int, column: int, item) -> None:
        if item is not None:
            self._apply_item_alignment(item, column)
        super().setItem(row, column, item)

    def reset_spans(self) -> None:
        """Remove category and summary spans before rebuilding table rows."""
        self.clearSpans()
        self._group_spans.clear()

    def apply_category_spans(self, major_column: int, minor_column: int | None = None) -> None:
        """Merge adjacent equal category cells with one shared hierarchy rule."""
        for row, column in self._group_spans:
            if row < self.rowCount() and column < self.columnCount():
                self.setSpan(row, column, 1, 1)
        self._group_spans.clear()

        def category(row: int) -> tuple[str, str] | None:
            major_item = self.item(row, major_column)
            if major_item is None:
                return None
            major = major_item.data(GROUP_MAJOR_ROLE)
            minor = major_item.data(GROUP_MINOR_ROLE)
            if major is None:
                return None
            return str(major), str(minor or "")

        def merge_runs(column: int, key_for_row) -> None:
            start = 0
            while start < self.rowCount():
                key = key_for_row(start)
                if key is None:
                    start += 1
                    continue
                end = start + 1
                while end < self.rowCount() and key_for_row(end) == key:
                    end += 1
                count = end - start
                if count > 1:
                    self.setSpan(start, column, count, 1)
                    item = self.item(start, column)
                    if item is not None:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._group_spans.append((start, column))
                start = end

        merge_runs(major_column, lambda row: (category(row) or (None, None))[0])
        if minor_column is not None:
            merge_runs(minor_column, category)

    def play_reorder_animation(self) -> None:
        """드롭 후 재배치가 끝났음을 보여주는 짧은 페이드 효과.

        행이 재정렬된 직후 opacity 를 살짝 낮췄다 되돌려 '자리가 바뀌었다'는 느낌을
        준다. A 방식(간단한 페이드)이며 성능에 거의 영향을 주지 않는다.
        """
        effect = QGraphicsOpacityEffect(self.viewport())
        self.viewport().setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(0.45)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: self.viewport().setGraphicsEffect(None))
        self._reorder_anim = anim  # 참조 유지(GUI 수명 동안, 프로퍼티로 보존)
        anim.start()

    def open_cell_editor(self, row: int, column: int, editor) -> None:
        self.close_cell_editor()
        self._active_editor = editor
        self._active_cell = (row, column)
        self.setCellWidget(row, column, editor)
        editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def close_cell_editor(self) -> None:
        if self._date_popup is not None:
            popup = self._date_popup
            self._date_popup = None
            popup.close()
            popup.deleteLater()
        if self._active_editor is None or self._active_cell is None:
            return
        editor = self._active_editor
        row, column = self._active_cell
        self._active_editor = None
        self._active_cell = None
        if isinstance(editor, QComboBox):
            editor.hidePopup()
        for calendar in editor.findChildren(QCalendarWidget):
            calendar.hide()
        editor.blockSignals(True)
        self.removeCellWidget(row, column)
        self.viewport().update()

    def open_choice_editor(self, row: int, column: int, choices, current, commit, *, editable=False) -> None:
        editor = AppComboBox()
        editor.setEditable(editable)
        for label, value in choices:
            editor.addItem(str(label), value)
            editor.setItemData(editor.count() - 1, Qt.AlignmentFlag.AlignCenter, Qt.ItemDataRole.TextAlignmentRole)
        if editor.isEditable():
            editor.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        index = editor.findData(current)
        if index >= 0:
            editor.setCurrentIndex(index)
        elif editable:
            editor.setCurrentText(str(current or ""))

        finished = False
        active = False  # 드롭다운이 실제로 열려 사용자 선택이 진행 중인 상태

        def mark_active():
            nonlocal active
            active = True

        def apply_choice(*_args):
            nonlocal finished
            if finished:
                return
            value = editor.currentText().strip() if editable else editor.currentData()
            if commit(value) is False:
                return
            finished = True
            # Do not destroy the editor from inside the native popup's
            # activated event.  Let Qt finish closing the popup first.
            QTimer.singleShot(0, self.close_cell_editor)

        def close_cancelled_popup():
            # A popup dismissed by clicking another cell must not leave its
            # editor embedded in the old cell.  If activated() follows
            # hidePopup(), the zero-delay check sees finished=True and leaves
            # the normal commit path in control.
            QTimer.singleShot(
                0,
                lambda: None
                if finished or self._active_editor is not editor
                else self.close_cell_editor(),
            )

        editor.activated.connect(apply_choice)
        editor.popup_closed.connect(close_cancelled_popup)
        if editable:
            # Windows에서 editable 콤보의 팝업을 열면 focus가 잠시 lineEdit을
            # 벗어나 editingFinished가 조기에 발생한다. this-open_editor 시점에
            # 아직 팝업이 안 열렸으면(showPopup 예약 전) 이를 초기화 노이즈로
            # 무시한다. popup_open 플래그가 참이 된 뒤에만 실제 선택으로 처리.
            editor.popup_open.connect(mark_active)

            def on_editing_finished():
                if not active or editor.popup_is_open():
                    return
                apply_choice()

            editor.lineEdit().editingFinished.connect(on_editing_finished)
        self.open_cell_editor(row, column, editor)
        # Offscreen test platforms cannot safely own native popup windows after
        # the transient cell editor is removed.  The real Windows application
        # still opens the choices immediately with the first cell click.
        if QApplication.platformName() != "offscreen":
            # 더블클릭 잔여 마우스 릴리스가 '팝업 외부 클릭'으로 감지돼 popup이
            # 닫히는 것을 막기 위해, 팝업을 여는 직전에 전역 릴리스 가드에 arm.
            arm_popup_release_guard()
            QTimer.singleShot(0, editor.showPopup)

    def open_number_editor(self, row: int, column: int, value, commit, *, money=False) -> None:
        editor = QDoubleSpinBox()
        editor.setRange(0, 999_999_999_999)
        configure_money_spin(editor) if money else configure_quantity_spin(editor)
        editor.setValue(float(value or 0))

        def apply_value():
            result = int(editor.value()) or None
            if commit(result) is False:
                return
            self.close_cell_editor()

        editor.editingFinished.connect(apply_value)
        self.open_cell_editor(row, column, editor)
        editor.selectAll()

    def open_date_editor(self, row: int, column: int, value: str | None, commit) -> None:
        self.close_cell_editor()
        popup = _DirectCalendarPopup(self)
        popup.set_selected_date(QDate.fromString(value, "yyyy-MM-dd") if value else QDate.currentDate())
        popup.set_clear_action("날짜 비우기")
        self._date_popup = popup

        def finish_popup():
            if self._date_popup is popup:
                self._date_popup = None
            popup.close()

        def apply_date(selected: QDate):
            text = selected.toString("yyyy-MM-dd")
            if commit(text) is False:
                return
            finish_popup()

        def clear_date():
            if commit(None) is False:
                return
            finish_popup()

        popup.calendar.clicked.connect(apply_date)
        popup.clear_button.clicked.connect(clear_date)
        popup.destroyed.connect(lambda *_args: setattr(self, "_date_popup", None) if self._date_popup is popup else None)
        rect = self.visualRect(self.model().index(row, column))
        position = self.viewport().mapToGlobal(QPoint(rect.left(), rect.bottom()))
        screen = QApplication.screenAt(position)
        if screen is not None:
            available = screen.availableGeometry()
            if position.x() + popup.width() > available.right():
                position.setX(max(available.left(), available.right() - popup.width()))
            if position.y() + popup.height() > available.bottom():
                position.setY(max(available.top(), self.viewport().mapToGlobal(rect.topLeft()).y() - popup.height()))
        popup.move(position)
        popup.show(); popup.raise_(); popup.activateWindow()

    def open_text_editor(self, row: int, column: int, value: str, commit) -> None:
        editor = QLineEdit(value or "")
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)

        def apply_text():
            if commit(editor.text().strip()) is False:
                return
            self.close_cell_editor()

        editor.editingFinished.connect(apply_text)
        self.open_cell_editor(row, column, editor)
        editor.selectAll()

    def enable_major_float(self, major_column: int) -> None:
        """대분류가 화면(뷰포트) 위쪽으로 벗어나 보이지 않게 될 때,
        이름이 항상 보이도록 뷰포트 상단에 대분류를 고정 표시한다."""
        self._major_column = major_column
        if getattr(self, "_major_float", None) is None:
            self._major_float = QLabel(self.viewport())
            self._major_float.setObjectName("MajorFloatLabel")
            self._major_float.setStyleSheet(
                "QLabel#MajorFloatLabel{background:#6B7280; color:#FFFFFF; padding:4px 12px; "
                "border-radius:6px; font-weight:600; font-size:13px;}"
            )
            self._major_float.hide()
        self.verticalScrollBar().valueChanged.connect(lambda _: self._update_major_float())
        # 스크롤·뷰포트 크기 변화와 함께 즉시 갱신
        self._update_major_float()

    def _update_major_float(self) -> None:
        label = getattr(self, "_major_float", None)
        if label is None:
            return
        major_col = getattr(self, "_major_column", None)
        if major_col is None or self.rowCount() == 0:
            label.hide()
            return
        vp = self.viewport()
        top = vp.rect().top()
        # 뷰포트 상단에 걸치는 행
        index = self.indexAt(QPoint(vp.rect().left() + 2, top + 1))
        if not index.isValid():
            label.hide()
            return
        row = index.row()
        item = self.item(row, major_col)
        if item is None:
            label.hide()
            return
        major = item.data(GROUP_MAJOR_ROLE)
        if major is None:
            label.hide()
            return
        group_major = str(major)
        # 대분류 그룹의 시작 행 rect
        group_row = row
        while group_row > 0:
            above = self.item(group_row - 1, major_col)
            if above is None or above.data(GROUP_MAJOR_ROLE) != major:
                break
            group_row -= 1
        start_rect = self.visualRect(self.model().index(group_row, major_col))
        # 대분류 시작 지점이 뷰포트 상단보다 위로 벗어나면 고정 표시
        if start_rect.top() < vp.rect().top():
            label.setText(group_major)
            label.adjustSize()
            # 대분류 열의 가로 중앙에 배치한다.
            col_rect = self.visualRect(self.model().index(row, major_col))
            label_x = col_rect.center().x() - label.width() // 2
            label.move(max(vp.rect().left() + 2, label_x), vp.rect().top() + 6)
            label.raise_()
            label.show()
        else:
            label.hide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_major_float()

    def enable_row_drag(self, on_reorder) -> None:
        """행 드래그 드롭으로 순서를 바꿀 수 있게 한다.

        on_reorder(source_row, target_row, before) -> bool 를 받는다. 사용자가
        source_row 행을 target_row 위치로 옮길 때 호출되며, before=True 면 target 행
        위쪽에, False 면 아래쪽에 놓는 것이다. True 를 반환하면 순서 변경을 실제
        적용한다(호출부가 DB/화면을 갱신). 기본 QTableWidget 의 셀 이동은 사용하지
        않아 병합 셀이나 편집기가 흐트러지지 않는다.
        """
        self._on_row_drag_reorder = on_reorder
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDropIndicatorShown(True)
        self.viewport().setAcceptDrops(True)

    def startDrag(self, supported_actions):
        indexes = self.selectedIndexes()
        if indexes:
            self._drag_source_row = indexes[0].row()
        super().startDrag(supported_actions)
        self._drag_source_row = None

    def dropEvent(self, event) -> None:
        callback = self._on_row_drag_reorder
        if callback is None or self._drag_source_row is None:
            event.ignore()
            return
        source = self._drag_source_row
        target = self._drop_target_row(event)
        before = self.dropIndicatorPosition() != QAbstractItemView.DropIndicatorPosition.BelowItem
        if source == target or target < 0:
            event.ignore()
            return
        # 행 이동을 실제로 적용할지 페이지가 결정한다. 셀 위젯/병합 셀을 보존하기
        # 위해 QTableWidget 의 기본 행 이동은 막고, 페이지가 재조회로 화면을 다시
        # 그리는 방식으로 반영한다.
        if callback(source, target, before):
            event.accept()
        else:
            event.ignore()

    def _drop_target_row(self, event) -> int:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(self.viewport().mapFromGlobal(self.viewport().mapToGlobal(pos)))
        if not index.isValid():
            row = self.rowCount() - 1
        else:
            row = index.row()
        position = self.dropIndicatorPosition()
        if position == QAbstractItemView.DropIndicatorPosition.BelowItem:
            row += 1
        return max(0, min(row, self.rowCount()))


class SpreadsheetItemDelegate(QStyledItemDelegate):
    """Shared spreadsheet painter with truly centered item checkboxes."""

    @staticmethod
    def check_indicator_rect(option: QStyleOptionViewItem, style) -> QRect:
        probe = QStyleOptionViewItem(option)
        indicator = style.subElementRect(QStyle.SubElement.SE_ItemViewItemCheckIndicator, probe, option.widget)
        indicator.moveCenter(option.rect.center())
        return indicator

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        check_state = index.data(Qt.ItemDataRole.CheckStateRole)
        if check_state is None:
            super().paint(painter, option, index)
            return

        style = option.widget.style() if option.widget is not None else QApplication.style()
        body = QStyleOptionViewItem(option)
        self.initStyleOption(body, index)
        body.features &= ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, body, painter, option.widget)

        indicator = QStyleOptionViewItem(option)
        indicator.rect = self.check_indicator_rect(option, style)
        indicator.state &= ~(
            QStyle.StateFlag.State_On | QStyle.StateFlag.State_Off | QStyle.StateFlag.State_NoChange
        )
        if check_state == Qt.CheckState.Checked:
            indicator.state |= QStyle.StateFlag.State_On
        elif check_state == Qt.CheckState.PartiallyChecked:
            indicator.state |= QStyle.StateFlag.State_NoChange
        else:
            indicator.state |= QStyle.StateFlag.State_Off
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_IndicatorItemViewItemCheck,
            indicator,
            painter,
            option.widget,
        )


class GroupSeparatorDelegate(SpreadsheetItemDelegate):
    """대분류·중분류가 바뀌는 행의 위쪽 경계를 단계별로 강조한다."""

    def __init__(self, anchor_column: int = 1, parent=None, wrap_columns=()):
        super().__init__(parent)
        self.anchor_column = anchor_column
        self.wrap_columns = {int(column) for column in wrap_columns}

    def separator_level(self, model, row: int) -> int:
        if row <= 0:
            return 0
        current = model.index(row, self.anchor_column)
        previous = model.index(row - 1, self.anchor_column)
        major = current.data(GROUP_MAJOR_ROLE)
        previous_major = previous.data(GROUP_MAJOR_ROLE)
        minor = current.data(GROUP_MINOR_ROLE)
        previous_minor = previous.data(GROUP_MINOR_ROLE)
        if major != previous_major:
            return 2
        if minor != previous_minor:
            return 1
        return 0

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.column() in self.wrap_columns:
            wrapped = QStyleOptionViewItem(option)
            self.initStyleOption(wrapped, index)
            # Qt 기본 delegate는 행 높이가 늘어나면 세 줄 이상도 그린다. 이 열은
            # 항상 두 줄만 쓰도록 배경과 텍스트를 분리해 직접 그린다.
            text = wrapped.text
            wrapped.text = ""
            style = wrapped.widget.style() if wrapped.widget is not None else QApplication.style()
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, wrapped, painter, wrapped.widget)
            self._draw_two_line_text(painter, option, text, wrapped)
        else:
            super().paint(painter, option, index)
        level = self.separator_level(index.model(), index.row())
        if not level:
            return
        painter.save()
        color = QColor(TOKENS["brand"] if level == 2 else "#C9CDD3")
        painter.setPen(QPen(color, 3 if level == 2 else 2))
        y = option.rect.top() + 1
        painter.drawLine(option.rect.left(), y, option.rect.right(), y)
        painter.restore()

    @staticmethod
    def _draw_two_line_text(painter: QPainter, option: QStyleOptionViewItem, text: str, styled: QStyleOptionViewItem) -> None:
        if not text:
            return
        rect = option.rect.adjusted(6, 3, -6, -3)
        layout = QTextLayout(text, styled.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        text_option.setAlignment(styled.displayAlignment)
        layout.setTextOption(text_option)
        color = styled.palette.color(
            QPalette.ColorRole.HighlightedText if styled.state & QStyle.StateFlag.State_Selected else QPalette.ColorRole.Text
        )
        painter.save()
        painter.setPen(color)
        layout.beginLayout()
        y = 0.0
        for _ in range(2):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(rect.width())
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()
        layout.draw(painter, QPointF(rect.left(), rect.top() + max(0, (rect.height() - y) / 2)))
        painter.restore()


def configure_grouped_editor_table(table: QTableWidget, anchor_column: int = 1) -> None:
    """표 안 입력칸을 행 안에 맞추고 분류 변경 경계를 표시한다."""
    table.setProperty("embeddedEditors", True)
    table.setItemDelegate(GroupSeparatorDelegate(anchor_column, table))
    table.verticalHeader().setDefaultSectionSize(48)
    table.verticalHeader().setMinimumSectionSize(48)


class _DirectDateCalendar(QCalendarWidget):
    """Shared date-input calendar with intentionally quiet adjacent months."""

    adjacent_month_color = QColor("#BAC1CC")

    def __init__(self, parent=None):
        super().__init__(parent)

    def paintCell(self, painter: QPainter, rect: QRect, value: QDate) -> None:  # noqa: N802
        """Draw spillover days ourselves because the native grid ignores formats.

        Some Windows Qt styles repaint the date number after `dateTextFormat`
        has been applied.  Painting this simple white cell and its number last
        makes the lower-contrast outside-month dates deterministic everywhere.
        """
        super().paintCell(painter, rect, value)
        if value.month() == self.monthShown():
            return
        painter.save()
        painter.fillRect(rect.adjusted(1, 1, -1, -1), QColor("#FFFFFF"))
        painter.setPen(self.adjacent_month_color)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(value.day()))
        painter.restore()


class _DirectCalendarPopup(QFrame):
    """월 이동과 연도 선택을 명확히 분리한 날짜 선택 팝업."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setObjectName("DirectCalendarPopup")
        self.setStyleSheet(
            "QFrame#DirectCalendarPopup{background:#FFFFFF;border:1px solid #CBD5E1;border-radius:10px;}"
            "QPushButton#DirectCalendarMonthButton{background:#FFFFFF;color:#172B4D;border:1px solid #CBD5E1;"
            "border-radius:6px;font-size:20px;font-weight:700;min-width:30px;max-width:30px;"
            "min-height:30px;max-height:30px;padding:0;}"
            "QPushButton#DirectCalendarMonthButton:hover{background:#EFF6FF;border-color:#60A5FA;}"
            "QLabel#DirectCalendarMonthLabel{color:#172B4D;font-weight:700;font-size:15px;}"
            "QComboBox#DirectCalendarYear{background:#FFFFFF;color:#172B4D;border:1px solid #CBD5E1;"
            "border-radius:6px;padding:3px 20px;font-weight:700;min-width:76px;text-align:center;}"
        )
        self.root = QVBoxLayout(self); self.root.setContentsMargins(6, 6, 6, 6); self.root.setSpacing(4)
        header = QHBoxLayout(); header.setContentsMargins(4, 0, 4, 0); header.setSpacing(6)
        self.previous_button = QPushButton("‹", self); self.previous_button.setObjectName("DirectCalendarMonthButton")
        self.previous_button.setToolTip("이전 달")
        self.month_label = QLabel(self); self.month_label.setObjectName("DirectCalendarMonthLabel")
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.year_combo = QComboBox(self); self.year_combo.setObjectName("DirectCalendarYear")
        # The previous read-only line editor consumed clicks over most of the
        # field, so only the tiny arrow opened the year menu.
        self.year_combo.setEditable(False)
        self.year_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.year_combo.setToolTip("연도 선택")
        self.next_button = QPushButton("›", self); self.next_button.setObjectName("DirectCalendarMonthButton")
        self.next_button.setToolTip("다음 달")
        header.addWidget(self.previous_button)
        header.addStretch(1)
        header.addWidget(self.month_label)
        header.addWidget(self.year_combo)
        header.addStretch(1)
        header.addWidget(self.next_button)
        self.root.addLayout(header)
        self.calendar = _DirectDateCalendar(self)
        self.calendar.setNavigationBarVisible(False)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.calendar.setGridVisible(True)
        # Six full date rows plus the weekday header need more than the old
        # 254px height on Windows high-DPI displays.  Keep the grid entirely
        # inside its popup instead of letting the final row be clipped.
        self.calendar.setFixedSize(326, 280)
        self.root.addWidget(self.calendar, 0, Qt.AlignmentFlag.AlignCenter)
        self.previous_button.clicked.connect(self.calendar.showPreviousMonth)
        self.next_button.clicked.connect(self.calendar.showNextMonth)
        self.year_combo.currentIndexChanged.connect(self._select_year)
        self.calendar.currentPageChanged.connect(self._sync_header)
        self._sync_header(self.calendar.yearShown(), self.calendar.monthShown())
        self._fit_to_contents()

    def _fit_to_contents(self) -> None:
        """Size the shared popup from its real layout, including app styling.

        A fixed height worked only until a checklist popup added its two action
        buttons.  The app stylesheet makes those buttons taller than the
        native defaults, so hard-coded heights let them overlap the final
        calendar week.  The layout's own size hint is DPI/style aware.
        """
        self.root.activate()
        content_height = max(self.root.sizeHint().height(), self.root.minimumSize().height())
        self.setFixedWidth(340)
        self.setFixedHeight(content_height + self.frameWidth() * 2 + 2)

    def set_clear_action(self, label: str) -> None:
        if hasattr(self, "clear_button"):
            return
        actions = QHBoxLayout(); actions.setContentsMargins(2, 0, 2, 0)
        self.clear_button = QPushButton(label, self); self.clear_button.setToolTip("입력한 날짜를 지우고 미입력 상태로 되돌립니다.")
        self.close_button = QPushButton("닫기", self); self.close_button.clicked.connect(self.hide)
        actions.addWidget(self.clear_button); actions.addStretch(); actions.addWidget(self.close_button)
        self.root.addLayout(actions); self._fit_to_contents()

    def set_selected_date(self, value: QDate) -> None:
        self.calendar.setSelectedDate(value)
        self.calendar.setCurrentPage(value.year(), value.month())

    def _sync_header(self, year: int, month: int) -> None:
        self.month_label.setText(f"{month}월")
        self.year_combo.blockSignals(True)
        # 일정은 앞으로의 계획이 주 대상이지만, 과거 기록도 선택할 수 있도록
        # 화면의 기준 연도만 중앙에 두고 앞뒤 2년씩 정확히 다섯 개만 보여 준다.
        self.year_combo.clear()
        for candidate in range(year - 2, year + 3):
            self.year_combo.addItem(str(candidate), candidate)
        self.year_combo.setCurrentIndex(2)
        self.year_combo.blockSignals(False)

    def _select_year(self, index: int) -> None:
        if index >= 0:
            self.calendar.setCurrentPage(int(self.year_combo.itemData(index)), self.calendar.monthShown())


class DirectDateEdit(QDateEdit):
    """직접 입력 없이 공용 달력을 여는 날짜 입력창."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("directCalendar", True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setCursor(Qt.CursorShape.PointingHandCursor)
        self.lineEdit().installEventFilter(self)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # 표에는 날짜 입력칸이 수백 개 생길 수 있다. 달력은 실제 클릭할 때만
        # 하나씩 만들어 초기 체크리스트 표시 비용을 줄인다.
        self._direct_calendar: _DirectCalendarPopup | None = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._open_calendar()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self._open_calendar()
            event.accept()
            return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.lineEdit() and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
                self._open_calendar()
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.isEnabled():
            self._open_calendar()
            event.accept()
            return
        super().keyPressEvent(event)

    def _open_calendar(self):
        popup = self._ensure_calendar()
        popup.set_selected_date(self.date())
        # Prefer opening below the field, but keep every date row inside the
        # usable screen when a form sits near the bottom or right edge.
        anchor = self.mapToGlobal(self.rect().bottomLeft())
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            x = max(available.left(), min(anchor.x(), available.right() - popup.width() + 1))
            y = anchor.y()
            if y + popup.height() > available.bottom() + 1:
                y = max(available.top(), self.mapToGlobal(self.rect().topLeft()).y() - popup.height())
            anchor = QPoint(x, y)
        popup.move(anchor)
        popup.show(); popup.raise_(); popup.activateWindow()

    def _choose_date(self, value: QDate):
        self.setDate(value)
        if self._direct_calendar:
            self._direct_calendar.hide()

    def calendarWidget(self):
        return self._ensure_calendar().calendar

    def _ensure_calendar(self) -> _DirectCalendarPopup:
        if self._direct_calendar is None:
            popup = _DirectCalendarPopup(self)
            popup.calendar.clicked.connect(self._choose_date)
            self._direct_calendar = popup
        return self._direct_calendar


def configure_money_spin(widget: QDoubleSpinBox, suffix: str = " 원") -> QDoubleSpinBox:
    """금액 입력을 쉼표 단위로 표시하고 불필요한 증감 화살표를 없앤다."""
    widget.setDecimals(0)
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    widget.setGroupSeparatorShown(True)
    widget.setLocale(QLocale(QLocale.Language.Korean, QLocale.Country.SouthKorea))
    widget.setSuffix(suffix)
    widget.setAlignment(Qt.AlignmentFlag.AlignRight)
    return widget


def configure_quantity_spin(widget: QDoubleSpinBox) -> QDoubleSpinBox:
    """수량을 자연수 중심으로 표시하고 증감 화살표를 숨긴다."""
    widget.setDecimals(0)
    widget.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    widget.setGroupSeparatorShown(True)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setProperty("quantityInput", True)
    return widget


class UnitComboBox(AppComboBox):
    value_committed = Signal(str)

    def __init__(self, value: str = "", parent=None, choices=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        values = []
        for unit in choices or COMMON_UNITS:
            text = str(unit or "").strip()
            if text and text not in values:
                values.append(text)
        self.addItems(values)
        self.setCurrentText(value or "식")
        self._last_value = self.currentText().strip()
        self.activated.connect(self._commit)
        self.lineEdit().editingFinished.connect(self._commit)
        self.setToolTip("목록에서 선택하거나 필요한 단위를 직접 입력할 수 있습니다.")

    def _commit(self, *_args):
        value = self.currentText().strip() or "식"
        if value == self._last_value:
            return
        self._last_value = value
        self.setCurrentText(value)
        self.value_committed.emit(value)


class KpiCard(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("Muted")
        self.value_label = QLabel("0")
        self.value_label.setObjectName("KpiValue")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str | int) -> None:
        self.value_label.setText(str(value))


class PeriodCalendar(QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dates: dict[date, list[dict]] = defaultdict(list)
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        self.setMinimumWidth(620)
        self.setMinimumHeight(520)

    def set_periods(self, rows) -> None:
        self._dates.clear()
        for row in rows:
            current = date.fromisoformat(row["planned_start"])
            end = date.fromisoformat(row["due_date"])
            period = dict(row)
            while current <= end:
                self._dates[current].append(period)
                current = current.fromordinal(current.toordinal() + 1)
        self.updateCells()

    def periods_for_day(self, day: date) -> list[dict]:
        """완료되지 않았고 마감이 가까운 업무부터 달력 라벨 순서를 정한다."""
        unique = {int(period["id"]): period for period in self._dates.get(day, [])}
        return sorted(
            unique.values(),
            key=lambda period: (
                period["status"] == "완료",
                period["due_date"],
                int(period.get("sort_order") or 0),
                int(period["id"]),
            ),
        )

    def visible_periods(self, day: date, max_slots: int) -> tuple[list[dict], int]:
        ordered = self.periods_for_day(day)
        if len(ordered) <= max_slots:
            return ordered, 0
        visible_count = max(1, max_slots - 1)
        return ordered[:visible_count], len(ordered) - visible_count

    def paintCell(self, painter: QPainter, rect, qdate: QDate) -> None:
        super().paintCell(painter, rect, qdate)
        day = date(qdate.year(), qdate.month(), qdate.day())
        periods = self._dates.get(day)
        if not periods:
            return
        painter.save()
        # 기본 달력은 날짜 숫자를 셀 중앙에 그린다. 일정 라벨이 많은 날에는
        # 겹치므로 해당 셀을 다시 칠하고 날짜를 위쪽에 고정한다.
        selected = qdate == self.selectedDate()
        cell_bg = QColor(TOKENS["brand_weak"] if selected else TOKENS["bg_layer"])
        painter.fillRect(rect.adjusted(1, 1, -1, -1), cell_bg)
        if qdate.month() != self.monthShown():
            day_color = QColor(TOKENS["fg_subtle"])
        elif qdate.dayOfWeek() in (6, 7):
            day_color = QColor(TOKENS["critical"])
        else:
            day_color = QColor(TOKENS["fg_neutral"])
        day_font = painter.font()
        day_font.setPointSizeF(9)
        painter.setFont(day_font)
        painter.setPen(day_color)
        painter.drawText(
            QRect(rect.left() + 2, rect.top() + 4, rect.width() - 4, 20),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
            str(qdate.day()),
        )
        palette = {
            "시스템": "#F25B24", "시설": "#8B5CF6", "행사": "#1769AA",
            "홍보": "#D97706", "운영": "#18864B",
        }
        label_height = 14
        label_gap = 1
        max_slots = min(4, max(2, (rect.height() - 34) // (label_height + label_gap)))
        visible, hidden_count = self.visible_periods(day, max_slots)
        lane_count = len(visible) + (1 if hidden_count else 0)
        start_y = rect.bottom() - 3 - lane_count * label_height - max(0, lane_count - 1) * label_gap

        font = painter.font()
        font.setPointSizeF(7.5)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        for lane, period in enumerate(visible):
            color = QColor(TOKENS["positive"] if period["status"] == "완료" else palette.get(period["major"], TOKENS["brand"]))
            fill = QColor(color)
            fill.setAlpha(38)
            painter.setPen(QPen(color, 1))
            painter.setBrush(fill)
            y = start_y + lane * (label_height + label_gap)
            label_rect = QRect(rect.left() + 4, y, rect.width() - 8, label_height)
            painter.drawRoundedRect(label_rect, 2, 2)
            painter.setPen(color.darker(125))
            text = metrics.elidedText(str(period["name"]), Qt.TextElideMode.ElideRight, label_rect.width() - 7)
            painter.drawText(label_rect.adjusted(4, 0, -3, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)

        if hidden_count:
            lane = len(visible)
            y = start_y + lane * (label_height + label_gap)
            more_rect = QRect(rect.left() + 4, y, rect.width() - 8, label_height)
            more_bg = QColor(TOKENS["bg_weak"])
            painter.setPen(QPen(QColor(TOKENS["fg_subtle"]), 1))
            painter.setBrush(more_bg)
            painter.drawRoundedRect(more_rect, 2, 2)
            painter.setPen(QColor(TOKENS["fg_muted"]))
            painter.drawText(
                more_rect.adjusted(4, 0, -3, 0),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                f"+{hidden_count}개 더보기",
            )
        painter.restore()


def configure_data_table(table: QTableWidget, widths: list[int], *, alternating: bool = True) -> None:
    """모든 열을 직접 늘이거나 이동할 수 있게 하고 초기 너비만 지정한다."""
    header = table.horizontalHeader()
    header.setProperty("columnResizeGuides", True)
    header.setToolTip("열 사이의 세로선을 좌우로 드래그하면 열 너비를 조절할 수 있습니다.")
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setSectionsMovable(True)
    header.setMinimumSectionSize(44)
    header.setStretchLastSection(False)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    table.setAlternatingRowColors(alternating)
    table.setItemDelegate(SpreadsheetItemDelegate(table))
    table.verticalHeader().setDefaultSectionSize(48)
    table.verticalHeader().setMinimumSectionSize(48)
    for column, width in enumerate(widths):
        table.setColumnWidth(column, width)


def configure_resizable_table(table: QTableWidget, widths: list[int]) -> None:
    """Backward-compatible alias for the shared table configuration."""
    configure_data_table(table, widths)


class TwoLineLabel(QLabel):
    """A category label that uses at most two wrapped lines, regardless of cell height."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._full_text = text
        self.setText(text)
        self.setToolTip(text)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        layout = QTextLayout(self._full_text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        option.setAlignment(self.alignment())
        layout.setTextOption(option)
        layout.beginLayout()
        y = 0.0
        for _ in range(2):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            line.setPosition(QPointF(0, y))
            y += line.height()
        layout.endLayout()
        layout.draw(painter, QPointF(0, max(0, (self.height() - y) / 2)))


class CategoryCell(QWidget):
    """병합된 대분류/중분류 셀에 얹는 위젯. 이름 라벨 + 작은 드래그 핸들로 구성.

    - 이름 라벨 더블클릭 → on_edit(major, minor)
    - 하단 핸들을 누르고 끌면 드래그로 분류 이동 → on_move(source_major, source_minor,
      target_major, target_minor)

    `minor is None` 이면 대분류 그룹(전체 major)을 나타낸다.
    """

    def __init__(self, major: str, minor: str | None, table, major_column: int, minor_column: int,
                 major_only: bool, on_edit, on_move, parent=None):
        super().__init__(parent)
        self.major = major
        self.minor = minor
        self._table = table  # 드롭 목표 계산용 테이블 참조 (setCellWidget parent 와 무관하게 안정적)
        self._major_column = major_column
        self._minor_column = minor_column
        self._major_only = major_only  # True 면 대분류 그룹, False 면 중분류 그룹
        self._on_edit = on_edit
        self._on_move = on_move
        self._dragging = False
        self._last_global = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 3)
        layout.setSpacing(0)
        # 중분류(minor) 셀에는 중분류 이름만, 대분류(minor None) 셀에는 대분류 이름만 표시한다.
        # Create child labels with their final parent immediately.  On Windows,
        # creating them parentless can briefly expose them as native windows
        # before the table takes ownership of this category cell.
        self.label = TwoLineLabel(str(minor if minor is not None else major), self)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        # 열 폭이 매우 좁아도 중분류는 두 줄까지만 사용한다. 드래그 핸들 공간은
        # 항상 남겨 텍스트와 핸들이 서로 겹치지 않는다.
        self.label.setMaximumHeight(40)
        self.label.setStyleSheet("background:transparent; font-weight:500;")
        # 대분류는 병합 영역이 세로로 길어 화면 밖으로 벗어나 이름이 가려지지 않도록
        # 이름 라벨을 병합 열의 세로 중앙에 배치한다. 중분류는 위쪽에 배치.
        if self._major_only:
            # [위쪽 스트레치][라벨][아래쪽 스트레치(핸들 위)] — 라벨이 세로 중앙.
            layout.addStretch(1)
            layout.addWidget(self.label, 0)
            layout.addStretch(1)  # 라벨과 핸들 사이 여유
        else:
            layout.addWidget(self.label, 1)
        # 드래그 핸들: 크고 눈에 띄게, 드래그 가능 표시(⋮⋮ / 좌우 여백 버튼).
        self.handle = QLabel("\u2630", self)  # ☰ 아이콘 — 드래그 가능을 명확히 표현
        self.handle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.handle.setFixedHeight(22)
        self.handle.setToolTip("끌어서 분류 순서 변경 (더블클릭: 이름 변경)")
        self.handle.setCursor(Qt.CursorShape.SizeAllCursor)
        # 배경색 없이 아이콘(☰) 3줄만, 색상은 연하게.
        self.handle.setStyleSheet(
            "color:#C9CFD6; background:transparent; border:none; font-size:14px; font-weight:600;"
        )
        layout.addWidget(self.handle, 0)
        self.setCursor(Qt.CursorShape.ArrowCursor)

    # 이름 라벨 더블클릭 → 분류 이름 편집
    def mouseDoubleClickEvent(self, event) -> None:
        if self._on_edit:
            self._on_edit(self.major, self.minor)
        event.accept()

    # 핸들 드래그 → 분류 이동 (전역 이벤트 필터로 grabMouse 없이 안정적으로 동작)
    def mousePressEvent(self, event) -> None:
        if (event.button() == Qt.MouseButton.LeftButton
                and self.handle.geometry().contains(event.position().toPoint())):
            self._dragging = True
            self._drag_source = (self.major, self.minor)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            app = QApplication.instance()
            if app is not None:
                app.installEventFilter(self)
            event.accept()
        else:
            # 분류 셀의 라벨/여백 영역을 눌러도 테이블의 개별 항목 드래그가 시작되지
            # 않도록 삼킨다 (이름 편집은 mouseDoubleClickEvent 로만, 이동은 핸들로만).
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        # 개별 항목 드래그가 분류 셀에서 시작되지 않도록 차단한다.
        event.accept()

    def eventFilter(self, watched, event) -> bool:
        if self._dragging and event.type() == QEvent.Type.MouseMove:
            self._last_global = event.globalPosition().toPoint()
            return False
        if self._dragging and event.type() == QEvent.Type.MouseButtonRelease:
            global_pos = getattr(self, "_last_global", event.globalPosition().toPoint())
            self._end_drag(global_pos)
            return True
        return False

    def _end_drag(self, global_pos) -> None:
        self._dragging = False
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._on_move and self._table is not None:
            target = _category_at_global(self._table, self._major_column, self._minor_column, global_pos)
            if target is None:
                return
            # 드롭 지점이 타겟 행의 중심보다 아래면 타겟 뒤(after=before False)로 이동하게 한다.
            below = self._drop_below_center(global_pos)
            if self._major_only:
                target = (target[0], None)  # 대분류 이동은 minor 를 버린다
            else:
                # 중분류 이동은 같은 대분류 안에서만 가능하다. 다른 대분류로는 옮기지 않는다
                # (중분류는 그 소속 항목들을 따라가되, 대분류를 벗어나면 항목이 뒤섞이므로 금지).
                if target[0] != self.major:
                    return
            if target != (self.major, self.minor):
                self._on_move(self.major, self.minor, target[0], target[1], not below)

    def _drop_below_center(self, global_pos) -> bool:
        viewport_pos = self._table.viewport().mapFromGlobal(global_pos)
        index = self._table.indexAt(viewport_pos)
        if not index.isValid():
            return False
        return viewport_pos.y() > self._table.visualRect(index).center().y()


def _category_at_global(table, major_column: int, minor_column: int, global_pos):
    """전역 좌표 기준 테이블 행의 (major, minor) 분류를 반환한다. 소계/합계 행은 None."""
    table_pos = table.viewport().mapFromGlobal(global_pos)
    index = table.indexAt(table_pos)
    if not index.isValid():
        return None
    row = index.row()
    major_item = table.item(row, major_column)
    if major_item is None:
        return None
    major = major_item.data(GROUP_MAJOR_ROLE)
    if major is None:
        return None
    minor = major_item.data(GROUP_MINOR_ROLE)
    return str(major), str(minor or "")


def install_category_cell_widgets(table: FastEditableTable, major_column: int, minor_column: int,
                                  on_edit, on_move) -> None:
    """병합된 분류 그룹 첫 행에 CategoryCell 위젯을 배치한다.

    on_edit(major, minor): 분류 이름 편집 요청
    on_move(source_major, source_minor, target_major, target_minor): 분류 이동 요청
    (source_minor 가 None 이면 대분류 그룹 이동)
    병합이 적용된 뒤에 호출한다.
    """
    # (major_column 또는 minor_column) 그룹 시작 행 목록: (row, column, major, minor)
    def group_starts_for(column: int):
        starts = []
        last = None
        for row in range(table.rowCount()):
            item = table.item(row, column)
            if item is None:
                continue
            major = item.data(GROUP_MAJOR_ROLE)
            minor = item.data(GROUP_MINOR_ROLE)
            # 소계·합계처럼 분류 role 이 없는 행은 건너뛴다(정산 테이블 대비).
            if major is None:
                continue
            key = (major, minor)
            if column == major_column:
                key = (major, None)  # 대분류 그룹은 major 단위로만 묶는다
            if key != last:
                starts.append((row, column, str(major), str(minor or "") if column == minor_column else None))
                last = key
        return starts

    for row, column, major, minor in group_starts_for(major_column):
        table.setCellWidget(row, column, CategoryCell(
            major, minor, table, major_column, minor_column, True,
            lambda m, n: on_edit(m, n), on_move, table.viewport(),
        ))
    for row, column, major, minor in group_starts_for(minor_column):
        table.setCellWidget(row, column, CategoryCell(
            major, minor, table, major_column, minor_column, False,
            lambda m, n: on_edit(m, n), on_move, table.viewport(),
        ))


def configure_editable_table(
    table: QTableWidget,
    widths: list[int],
    *,
    grouped: bool = False,
    anchor_column: int = 1,
    wrap_columns=(),
) -> None:
    """Shared presentation contract for spreadsheet-like editable tables."""
    configure_data_table(table, widths)
    table.setProperty("embeddedEditors", True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setWordWrap(True)
    table.setTextElideMode(Qt.TextElideMode.ElideNone)
    if grouped:
        table.setItemDelegate(GroupSeparatorDelegate(anchor_column, table, wrap_columns))


def fit_table_to_view(table: QTableWidget, minimum: int = 58) -> None:
    """현재 창 너비에 맞춰 표시 중인 모든 열을 비례 조정한다.

    각 열의 현재 너비 비율을 유지한 채 viewport 폭에 맞춰 전체를 균등히
    늘린다. 세부내용/메모 열을 상대적으로 넓게 유지하려면 초기 너비를
    기준 열(항목) 대비 약 3배로 지정해 두면 된다.
    """
    visible = [column for column in range(table.columnCount()) if not table.isColumnHidden(column)]
    if not visible:
        return
    fixed = table.fixed_column_widths() if isinstance(table, FastEditableTable) else {}
    flexible = [column for column in visible if column not in fixed]
    if not flexible:
        return
    fixed_width = sum(table.columnWidth(column) for column in visible if column in fixed)
    available = max(1, table.viewport().width() - fixed_width - 4)
    current = [max(minimum, table.columnWidth(column)) for column in flexible]
    total = sum(current)
    if total <= 0:
        return
    widths = [max(minimum, int(width * available / total)) for width in current]
    # 반올림 오차는 마지막 열에 반영하되 최소 너비를 지킨다.
    if sum(widths) < available:
        widths[-1] += available - sum(widths)
    for column, width in zip(flexible, widths):
        table.setColumnWidth(column, width)
    _resize_wrapped_rows_after_fit(table)


def _resize_wrapped_rows_after_fit(table: QTableWidget) -> None:
    """Keep category and task names readable when fit-to-view narrows their columns."""
    columns = table.property("fitWrapColumns") or []
    if not columns:
        return
    table.setWordWrap(True)
    for row in range(table.rowCount()):
        required_height = 48
        for column in columns:
            item = table.item(row, int(column))
            if item is None:
                continue
            category_name = item.data(GROUP_MINOR_ROLE) if not item.text() else None
            text = item.text() or category_name or ""
            if not text:
                continue
            available = max(24, table.columnWidth(int(column)) - 12)
            lines = min(2, max(1, (QFontMetrics(item.font()).horizontalAdvance(str(text)) + available - 1) // available))
            # 중분류 셀은 라벨 2줄과 22px 드래그 핸들을 함께 담아야 한다.
            height = 34 + lines * 20 if category_name else 16 + lines * 20
            required_height = max(required_height, min(96, height))
        table.setRowHeight(row, required_height)
    # 병합 셀 위젯의 레이아웃도 새 행 높이를 즉시 다시 계산해야 실제 줄바꿈이 반영된다.
    table.doItemsLayout()
    table.viewport().update()
