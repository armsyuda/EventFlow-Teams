from __future__ import annotations

"""Privacy-conscious diagnostics for brief Windows UI flashes."""

from datetime import datetime
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QWidget


class RuntimeWindowTrace(QObject):
    """Record window lifecycle facts without recording user or company data."""

    _EVENTS = {
        QEvent.Type.Show: "show",
        QEvent.Type.Hide: "hide",
        QEvent.Type.ShowToParent: "show_to_parent",
        QEvent.Type.HideToParent: "hide_to_parent",
        QEvent.Type.ParentChange: "parent_change",
        QEvent.Type.WinIdChange: "native_handle_change",
        QEvent.Type.WindowActivate: "activate",
        QEvent.Type.WindowDeactivate: "deactivate",
    }
    _ALWAYS_TRACK = {
        "QDialog",
        "QMessageBox",
        "QMenu",
        "QFileDialog",
        "QLabel",
        "CategoryCell",
        "TwoLineLabel",
        "StartupSplash",
    }

    def __init__(self, data_root: Path) -> None:
        super().__init__()
        self.path = data_root / "runtime-window-trace.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text("", encoding="utf-8")
        except OSError:
            pass
        self.record("trace_started", process_id=os.getpid())

    def record(self, action: str, **fields: object) -> None:
        """Write only technical metadata; never titles, labels, or user data."""
        timestamp = datetime.now().astimezone().isoformat(timespec="milliseconds")
        detail = " ".join(f"{key}={self._safe(value)}" for key, value in fields.items())
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(f"{timestamp} {action}{(' ' + detail) if detail else ''}\n")
        except OSError:
            # Diagnostics must never prevent the work application from opening.
            return

    @staticmethod
    def _safe(value: object) -> str:
        return str(value).replace("\r", " ").replace("\n", " ").replace(" ", "_")[:96]

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API name
        action = self._EVENTS.get(event.type())
        if action and isinstance(watched, QWidget) and self._should_track(watched, event.type()):
            parent = watched.parentWidget()
            geometry = watched.geometry()
            self.record(
                "widget_event",
                event=action,
                widget=type(watched).__name__,
                object_name=watched.objectName() or "-",
                parent=type(parent).__name__ if parent else "none",
                native_window=watched.isWindow(),
                visible=watched.isVisible(),
                flags=hex(int(watched.windowFlags())),
                geometry=f"{geometry.x()}x{geometry.y()}x{geometry.width()}x{geometry.height()}",
            )
        return super().eventFilter(watched, event)

    def _should_track(self, widget: QWidget, event_type: QEvent.Type) -> bool:
        return (
            widget.isWindow()
            or type(widget).__name__ in self._ALWAYS_TRACK
            or event_type == QEvent.Type.WinIdChange
            or widget.objectName() in {"LoadingOverlay", "LoadingPanel", "InAppInputPanel", "DirectCalendarPopup"}
        )
