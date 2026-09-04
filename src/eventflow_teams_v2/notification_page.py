from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout, QWidget


def _time_label(value: object) -> str:
    text = str(value or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value or "")[:16]


class NotificationPage(QWidget):
    """Durable server notification list; toast delivery is only a preview."""

    def __init__(self, load: Callable[[bool], list[dict]], mark_read: Callable[[str | None], bool], delete: Callable[[str | None], bool], open_notice: Callable[[dict], None], parent=None):
        super().__init__(parent); self._load=load; self._mark_read=mark_read; self._delete=delete; self._open_notice=open_notice; self.notices: list[dict]=[]
        root=QVBoxLayout(self); root.setContentsMargins(32,28,32,32); root.setSpacing(12)
        top=QHBoxLayout(); top.addWidget(QLabel("알림",objectName="PageTitle")); top.addWidget(QLabel("업무 배정과 변경 내역을 다시 확인할 수 있습니다.",objectName="PageDescription")); top.addStretch()
        self.unread=QCheckBox("미확인만 보기"); self.unread.toggled.connect(self.refresh); top.addWidget(self.unread)
        read_all=QPushButton("모두 확인"); read_all.clicked.connect(self._read_all); top.addWidget(read_all)
        delete_all=QPushButton("전체 삭제"); delete_all.setProperty("danger",True); delete_all.clicked.connect(self._delete_all); top.addWidget(delete_all); root.addLayout(top)
        self.message=QLabel(""); self.message.setObjectName("Muted"); root.addWidget(self.message)
        self.list=QListWidget(); self.list.setObjectName("NotificationList"); self.list.setSpacing(8); self.list.itemDoubleClicked.connect(self._open_item); root.addWidget(self.list,1)

    def refresh(self) -> None:
        try: self.set_notices(self._load(self.unread.isChecked()))
        except Exception as exc: self.message.setText(f"알림을 불러오지 못했습니다: {exc}")

    def set_notices(self, notices: list[dict]) -> None:
        self.notices=list(notices); self.list.clear(); self.message.setText(f"{len(self.notices)}개의 알림")
        if not self.notices:
            item=QListWidgetItem("표시할 알림이 없습니다."); item.setFlags(Qt.ItemFlag.NoItemFlags); self.list.addItem(item); return
        for notice in self.notices:
            item=QListWidgetItem(); item.setData(Qt.ItemDataRole.UserRole,notice); item.setSizeHint(item.sizeHint().__class__(0,86)); self.list.addItem(item)
            card=QFrame(); card.setObjectName("NotificationCard"); card.setStyleSheet("QFrame#NotificationCard{background:#FFF;border:1px solid #E2E8F0;border-radius:10px;}" if notice.get("read_at") else "QFrame#NotificationCard{background:#FFF7F2;border:1px solid #F15A24;border-radius:10px;}")
            box=QVBoxLayout(card); box.setContentsMargins(12,8,12,8); box.setSpacing(3); row=QHBoxLayout(); row.addWidget(QLabel(str(notice.get("title") or "업무 알림"),objectName="SectionTitle"),1); row.addWidget(QLabel(_time_label(notice.get("created_at")),objectName="Muted")); box.addLayout(row)
            project=str(notice.get("project_name") or "사내 업무"); box.addWidget(QLabel(f"{project} · {notice.get('message') or ''}"))
            actions=QHBoxLayout(); actions.addStretch(); open_button=QPushButton("업무 보기"); open_button.setProperty("quiet",True); open_button.clicked.connect(lambda _=False,n=notice:self._open(n)); actions.addWidget(open_button); delete_button=QPushButton("삭제"); delete_button.setProperty("quiet",True); delete_button.clicked.connect(lambda _=False,n=notice:self._delete_one(n)); actions.addWidget(delete_button); box.addLayout(actions); self.list.setItemWidget(item,card)

    def _open_item(self,item:QListWidgetItem)->None:
        notice=item.data(Qt.ItemDataRole.UserRole)
        if isinstance(notice,dict): self._open(notice)

    def _open(self,notice:dict)->None:
        self._mark_read(str(notice.get("id") or "")); self._open_notice(notice)

    def _read_all(self)->None:
        if self._mark_read(None): self.refresh()

    def _delete_one(self,notice:dict)->None:
        if self._delete(str(notice.get("id") or "")): self.refresh()

    def _delete_all(self)->None:
        if QMessageBox.question(self,"알림 전체 삭제","지금까지 받은 알림을 모두 삭제할까요?") == QMessageBox.StandardButton.Yes and self._delete(None): self.refresh()
