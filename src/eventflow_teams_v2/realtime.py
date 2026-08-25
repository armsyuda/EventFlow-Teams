"""Realtime wake-up listener for Teams V2.

The subscription contains no work data.  It listens only to a protected
organization pulse and asks the existing ACL-filtered changes RPC for rows.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.parse import quote

import websocket
from PySide6.QtCore import QThread, Signal


class RealtimeSignalClient(QThread):
    changed = Signal()
    state_changed = Signal(str, str)

    def __init__(self, supabase_url: str, publishable_key: str, access_token: str, organization_id: str) -> None:
        super().__init__()
        base = supabase_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1)
        self.url = f"{base}/realtime/v1/websocket?apikey={quote(publishable_key)}&vsn=1.0.0"
        self.access_token = access_token
        self.organization_id = organization_id
        self.topic = f"realtime:teams-v2-{organization_id}"
        self._stopping = threading.Event()
        self._socket: websocket.WebSocket | None = None

    def stop(self) -> None:
        self._stopping.set()
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass

    def run(self) -> None:
        retry_ms = 1000
        while not self._stopping.is_set():
            try:
                self._connect_and_listen()
                retry_ms = 1000
            except Exception as exc:
                if self._stopping.is_set():
                    break
                self.state_changed.emit("WAITING", "실시간 연결 재시도 중")
                self._stopping.wait(retry_ms / 1000)
                retry_ms = min(10_000, retry_ms * 2)
        self.state_changed.emit("STOPPED", "")

    def _connect_and_listen(self) -> None:
        self._socket = websocket.create_connection(self.url, timeout=3)
        self._send("1", self.topic, "phx_join", {
            "config": {
                "broadcast": {"self": False, "ack": False},
                "presence": {"key": ""},
                "postgres_changes": [{
                    # The first change for an organization creates the pulse
                    # row, while later changes update it.  Subscribe to both.
                    "event": "*", "schema": "public", "table": "teams_v2_sync_signals",
                    "filter": f"organization_id=eq.{self.organization_id}",
                }],
            },
            "access_token": self.access_token,
        })
        self.state_changed.emit("SYNCED", "동기화 완료")
        last_heartbeat = time.monotonic()
        while not self._stopping.is_set():
            try:
                raw = self._socket.recv()
            except websocket.WebSocketTimeoutException:
                raw = None
            if raw:
                self._handle_message(raw)
            if time.monotonic() - last_heartbeat >= 20:
                self._send(str(int(time.monotonic() * 1000)), "phoenix", "heartbeat", {})
                last_heartbeat = time.monotonic()
        self._socket.close()

    def _send(self, ref: str | None, topic: str, event: str, payload: dict[str, Any]) -> None:
        if self._socket:
            self._socket.send(json.dumps([ref, ref, topic, event, payload]))

    def _handle_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(message, list) or len(message) < 4:
            return
        event = message[3]
        if event == "postgres_changes":
            self.changed.emit()
        elif event in {"phx_error", "phx_close"}:
            raise ConnectionError("Realtime channel closed")
