from __future__ import annotations

import json
from typing import Callable

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QFrame, QGraphicsDropShadowEffect,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


TASK_MIME = "application/x-eventflow-work-task"


def work_kind_label(task: dict) -> str:
    kind = str(task.get("work_kind") or ("COMPANY_SELF" if task.get("work_scope") == "COMPANY" else "CHECKLIST"))
    return {"CHECKLIST": "체크리스트 업무", "PROJECT_ADDITIONAL": "프로젝트 추가 업무", "COMPANY_SELF": "사내 업무"}.get(kind, "업무")


class WorkDetailDialog(QDialog):
    """Shared read-first detail surface for every Teams work type."""

    def __init__(self, task: dict, *, on_open: Callable[[], None] | None = None, on_edit: Callable[[], None] | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("업무 상세")
        self.setMinimumWidth(520)
        root = QVBoxLayout(self); root.setContentsMargins(24, 22, 24, 20); root.setSpacing(14)
        heading = QLabel(str(task.get("name") or "업무"), objectName="PageTitle"); heading.setWordWrap(True); root.addWidget(heading)
        badge = QLabel(work_kind_label(task)); badge.setStyleSheet("background:#FFF0E8;color:#C9380B;border-radius:8px;padding:5px 9px;font-weight:700;"); badge.setMaximumWidth(badge.sizeHint().width()+18); root.addWidget(badge)
        form = QFormLayout(); form.setHorizontalSpacing(22); form.setVerticalSpacing(11)
        values = [
            ("프로젝트", task.get("event_name") or ("사내 업무" if task.get("work_scope") == "COMPANY" else "프로젝트")),
            ("상태", task.get("status") or "미착수"),
            ("기간", f"{task.get('planned_start') or '시작일 미입력'}  ~  {task.get('due_date') or '마감일 미입력'}"),
            ("담당자", task.get("assignee_name") or "담당자 미지정"),
            ("내용", task.get("detail") or task.get("note") or "내용이 없습니다."),
        ]
        for title, value in values:
            label = QLabel(str(value)); label.setWordWrap(True); label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); form.addRow(title, label)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close); buttons.rejected.connect(self.reject)
        if on_open:
            button = buttons.addButton("체크리스트에서 열기", QDialogButtonBox.ButtonRole.ActionRole); button.clicked.connect(lambda: (self.accept(), on_open()))
        if on_edit:
            button = buttons.addButton("수정하기", QDialogButtonBox.ButtonRole.ActionRole); button.setProperty("primary", True); button.clicked.connect(lambda: (self.accept(), on_edit()))
        root.addWidget(buttons)


class WorkCard(QFrame):
    """One clean card with native drag preview and reliable whole-card input."""

    def __init__(self, task: dict, *, open_detail: Callable[[dict], None], drag_payload: dict | None = None, show_handle: bool = True, parent=None):
        super().__init__(parent)
        self.task = task; self.open_detail = open_detail; self.drag_payload = drag_payload; self._origin: QPoint | None = None; self._dragging = False
        self.setObjectName("UnifiedWorkCard"); self.setCursor(Qt.CursorShape.OpenHandCursor if drag_payload else Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("QFrame#UnifiedWorkCard{background:#FFFFFF;border:none;border-left:4px solid transparent;border-radius:11px;} QFrame#UnifiedWorkCard:hover{background:#FFFDFC;border-left:4px solid #F4511E;}")
        shadow = QGraphicsDropShadowEffect(self); shadow.setBlurRadius(14); shadow.setOffset(0, 3); shadow.setColor(Qt.GlobalColor.lightGray); self.setGraphicsEffect(shadow)
        row = QHBoxLayout(self); row.setContentsMargins(13, 10, 13, 10); row.setSpacing(10)
        if show_handle and drag_payload:
            handle = QLabel("⋮⋮"); handle.setToolTip("끌어서 이동"); handle.setStyleSheet("color:#98A2B3;font-weight:700;border:none;background:transparent;"); row.addWidget(handle)
        text = QVBoxLayout(); text.setSpacing(3)
        top = QHBoxLayout(); top.setSpacing(7)
        kind = QLabel(work_kind_label(task)); kind.setStyleSheet("color:#C9380B;background:#FFF0E8;border:none;border-radius:6px;padding:2px 6px;font-size:11px;font-weight:700;"); top.addWidget(kind)
        project = str(task.get("event_name") or "");
        if project and task.get("work_scope") != "COMPANY": top.addWidget(QLabel(project, objectName="Muted"))
        top.addStretch(); text.addLayout(top)
        name = QLabel(str(task.get("name") or "업무")); name.setWordWrap(True); name.setStyleSheet("border:none;background:transparent;font-weight:700;color:#1D2939;"); text.addWidget(name)
        due = str(task.get("due_date") or "마감일 미입력"); meta = QLabel(f"{task.get('status') or '미착수'}  ·  {due}", objectName="Muted"); meta.setStyleSheet("border:none;background:transparent;color:#667085;"); text.addWidget(meta); row.addLayout(text, 1)
        hint = QLabel("↗"); hint.setToolTip("더블클릭하여 상세 보기"); hint.setStyleSheet("border:none;background:transparent;color:#98A2B3;font-size:15px;"); row.addWidget(hint, 0, Qt.AlignmentFlag.AlignTop)
        self._install_input_filter(self)

    def _install_input_filter(self, widget: QWidget) -> None:
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget): child.installEventFilter(self)

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
            self.open_detail(self.task); event.accept(); return True
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._origin = self.mapFromGlobal(event.globalPosition().toPoint()); self._dragging = False
        elif event.type() == QEvent.Type.MouseMove and self.drag_payload and self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            current = self.mapFromGlobal(event.globalPosition().toPoint())
            if (current-self._origin).manhattanLength() >= 8 and not self._dragging:
                self._start_drag(); return True
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self._origin = None; self._dragging = False
        return super().eventFilter(watched,event)

    def _start_drag(self) -> None:
        self._dragging = True; self.setCursor(Qt.CursorShape.ClosedHandCursor)
        mime = QMimeData(); mime.setData(TASK_MIME,json.dumps(self.drag_payload).encode("utf-8"))
        pixmap = self.grab(); translucent = QPixmap(pixmap.size()); translucent.fill(Qt.GlobalColor.transparent)
        painter = QPainter(translucent); painter.setOpacity(.82); painter.drawPixmap(0,0,pixmap); painter.end()
        drag = QDrag(self); drag.setMimeData(mime); drag.setPixmap(translucent); drag.setHotSpot(self._origin or QPoint(18,18))
        self.hide()
        drag.exec(Qt.DropAction.MoveAction)
        self.show()
        self.setCursor(Qt.CursorShape.OpenHandCursor); self._origin=None; self._dragging=False
