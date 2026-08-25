"""Non-modal local outbox coordinator for Teams V2.

This module deliberately has no Local UI dependencies.  It observes only the
V2 outbox in SQLite; an idle timer never contacts the server.  A server request
is made only when a locally captured change is waiting to be sent.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Signal

from .outbox import WorkspaceOutbox
from .workspace import WorkspaceDatabase


class WorkspaceSyncEngine(QObject):
    """Send local changes in the background with bounded retry backoff."""

    state_changed = Signal(str, str)
    mutation_finished = Signal(str, str)

    def __init__(
        self,
        database: WorkspaceDatabase,
        organization_id: str,
        send: Callable[[list[dict[str, Any]]], dict[str, Any]],
        run_network: Callable[[Callable[[], object], Callable[[object], None], Callable[[str], None]], None],
    ) -> None:
        super().__init__()
        self.database = database
        self.organization_id = organization_id
        self.outbox = WorkspaceOutbox(database)
        self.send = send
        self.run_network = run_network
        self.timer = QTimer(self)
        self.timer.setInterval(450)
        self.timer.timeout.connect(self._tick)
        self._in_flight = False
        self._next_allowed_ms = 0
        self._entry: dict[str, object] | None = None

    def start(self) -> None:
        self.timer.start()
        self._tick()

    def stop(self) -> None:
        self.timer.stop()
        self._in_flight = False
        self._entry = None

    def _tick(self) -> None:
        if self._in_flight or self._next_allowed_ms > 0:
            if self._next_allowed_ms > 0:
                self._next_allowed_ms -= self.timer.interval()
            return
        prepared = self.outbox.next_mutation()
        if not prepared:
            if self.database.pending_outbox():
                self.state_changed.emit("WAITING", "동기화 대기 중")
            else:
                self.state_changed.emit("SYNCED", "동기화 완료")
            return
        self._entry, mutation = prepared
        self._in_flight = True
        self.state_changed.emit("SYNCING", "로컬 변경 동기화 중…")
        self.run_network(
            lambda: self.send([mutation]),
            self._sent,
            self._failed,
        )

    def _sent(self, value: object) -> None:
        entry = self._entry
        self._entry = None
        self._in_flight = False
        if not entry or not isinstance(value, dict):
            self._failed("서버 저장 응답이 올바르지 않습니다.")
            return
        result = self.outbox.apply_response(entry, value)
        if result == "APPLIED":
            self.mutation_finished.emit("APPLIED", "")
            self.state_changed.emit("SYNCED", "동기화 완료")
            return
        if result == "CONFLICT":
            self.mutation_finished.emit("CONFLICT", "동시 수정 충돌")
            self.state_changed.emit("ERROR", "동시 수정 확인 필요")
            return
        self.mutation_finished.emit("REJECTED", "서버에서 변경을 거부했습니다.")
        self.state_changed.emit("ERROR", "변경 전송 확인 필요")

    def _failed(self, message: str) -> None:
        entry = self._entry
        self._entry = None
        self._in_flight = False
        if entry:
            self.outbox.record_transport_failure(entry, message or "서버 연결을 확인할 수 없습니다.")
            attempts = int(entry.get("attempts") or 0) + 1
            self._next_allowed_ms = min(30_000, 1_000 * (2 ** min(attempts, 5)))
        self.state_changed.emit("WAITING", "오프라인 변경 보관 중")
        self.mutation_finished.emit("WAITING", message or "서버 연결을 확인할 수 없습니다.")
