from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterator, Sequence


SCHEMA_VERSION = 10


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection: sqlite3.Connection | None = None
        self._history_directory: Path | None = None
        self._history_limit = 50
        self._undo_stack: list[Path] = []
        self._redo_stack: list[Path] = []
        self._history_depth = 0
        self._history_counter = 0
        self._history_listeners: list[Any] = []
        self._dirty = False
        self.open()

    def open(self) -> None:
        if self.connection is not None:
            return
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.initialize()

    def close(self) -> None:
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self.connection is None:
            raise RuntimeError("데이터베이스가 닫혀 있습니다.")
        return self.connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.history_action():
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def initialize(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                version INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT,
                location TEXT NOT NULL DEFAULT '',
                organizer TEXT NOT NULL DEFAULT '',
                budget REAL,
                budget_tax_mode TEXT NOT NULL DEFAULT 'UNSET'
                    CHECK(budget_tax_mode IN ('INCLUDED','EXCLUDED','UNSET')),
                pm_vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(end_date IS NULL OR end_date >= start_date)
            );

            CREATE TABLE IF NOT EXISTS master_items (
                id INTEGER PRIMARY KEY,
                major TEXT NOT NULL,
                minor TEXT NOT NULL,
                name TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT '중' CHECK(priority IN ('상', '중', '하')),
                quantity REAL,
                unit TEXT NOT NULL DEFAULT '',
                base_unit_price INTEGER,
                default_vat_type TEXT NOT NULL DEFAULT 'TAXABLE'
                    CHECK(default_vat_type IN ('TAXABLE','EXEMPT')),
                default_vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                default_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                sort_order INTEGER NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('PERSON', 'VENDOR')),
                name TEXT NOT NULL,
                phone TEXT NOT NULL DEFAULT '',
                job_title TEXT NOT NULL DEFAULT '',
                role_note TEXT NOT NULL DEFAULT '',
                company_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS event_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                master_item_id INTEGER REFERENCES master_items(id) ON DELETE SET NULL,
                major TEXT NOT NULL,
                minor TEXT NOT NULL,
                name TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                required INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT '미착수'
                    CHECK(status IN ('미착수','진행중','확인요청','완료','보류','해당없음')),
                priority TEXT NOT NULL DEFAULT '중' CHECK(priority IN ('상','중','하')),
                quantity REAL,
                unit TEXT NOT NULL DEFAULT '',
                assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                pm_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                planned_start TEXT,
                due_date TEXT,
                cost REAL,
                unit_price INTEGER,
                vat_type TEXT NOT NULL DEFAULT 'TAXABLE'
                    CHECK(vat_type IN ('TAXABLE','EXEMPT')),
                is_removed INTEGER NOT NULL DEFAULT 0,
                removed_reason TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                completed_at TEXT,
                sort_order INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK(planned_start IS NULL OR due_date IS NULL OR planned_start <= due_date)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS event_vendors (
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                vendor_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                PRIMARY KEY(event_id, vendor_id)
            );

            CREATE TABLE IF NOT EXISTS event_freelancers (
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                person_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
                PRIMARY KEY(event_id, person_id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_event ON event_tasks(event_id);
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON event_tasks(due_date);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON event_tasks(status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_event_master_unique
                ON event_tasks(event_id, master_item_id) WHERE master_item_id IS NOT NULL;
            """
        )
        row = self.conn.execute("SELECT version FROM schema_info LIMIT 1").fetchone()
        if row is None:
            self.conn.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
        elif row["version"] < SCHEMA_VERSION:
            self._migrate(row["version"])
        elif row["version"] > SCHEMA_VERSION:
            raise RuntimeError(f"지원하지 않는 DB 버전: {row['version']}")
        self.conn.execute("DROP INDEX IF EXISTS idx_contacts_kind_name")
        self.conn.execute("DROP INDEX IF EXISTS idx_contacts_company_name")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_contacts_kind_name_lookup "
            "ON contacts(kind,name)"
        )
        task_columns = {column["name"] for column in self.conn.execute("PRAGMA table_info(event_tasks)")}
        if "removed_reason" not in task_columns:
            self.conn.execute("ALTER TABLE event_tasks ADD COLUMN removed_reason TEXT NOT NULL DEFAULT ''")
        self._seed_master_items()
        self._seed_contacts()
        self.conn.commit()

    def _migrate(self, from_version: int) -> None:
        safety_path = self.path.with_name(f"{self.path.stem}.pre-v{from_version}.db")
        if not safety_path.exists():
            safety = sqlite3.connect(safety_path)
            try:
                self.conn.backup(safety)
            finally:
                safety.close()
        version = from_version
        if version == 1:
            self.conn.execute(
                "ALTER TABLE master_items ADD COLUMN default_vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL"
            )
            self.conn.execute(
                "ALTER TABLE master_items ADD COLUMN default_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL"
            )
            version = 2
        if version == 2:
            # 과거 자동 일정도 이전 과정에서 다시 계산하지 않는다.
            # 저장되어 있던 날짜는 그대로 보존하고 v7에서 자동 일정 열만 제거한다.
            version = 3
        if version == 3:
            def add_column(table: str, column: str, declaration: str) -> None:
                existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

            add_column("master_items", "base_unit_price", "INTEGER")
            add_column("master_items", "default_vat_type", "TEXT NOT NULL DEFAULT 'TAXABLE'")
            add_column("events", "budget_tax_mode", "TEXT NOT NULL DEFAULT 'UNSET'")
            add_column("contacts", "company_id", "INTEGER REFERENCES contacts(id) ON DELETE SET NULL")
            add_column("event_tasks", "unit_price", "INTEGER")
            add_column("event_tasks", "vat_type", "TEXT NOT NULL DEFAULT 'TAXABLE'")
            add_column("event_tasks", "is_removed", "INTEGER NOT NULL DEFAULT 0")
            self.conn.execute(
                """UPDATE event_tasks SET unit_price = CASE
                   WHEN cost IS NULL THEN NULL
                   WHEN quantity IS NOT NULL AND quantity > 0 THEN CAST(ROUND(cost / quantity) AS INTEGER)
                   ELSE CAST(ROUND(cost) AS INTEGER) END"""
            )
            self.conn.execute(
                """INSERT OR IGNORE INTO event_vendors(event_id,vendor_id)
                   SELECT DISTINCT event_id,vendor_id FROM event_tasks WHERE vendor_id IS NOT NULL"""
            )
            self.conn.execute(
                """INSERT OR IGNORE INTO event_freelancers(event_id,person_id)
                   SELECT DISTINCT t.event_id,t.assignee_id FROM event_tasks t
                   JOIN contacts c ON c.id=t.assignee_id
                   WHERE t.assignee_id IS NOT NULL AND c.kind='PERSON' AND c.company_id IS NULL"""
            )
            version = 4
        if version == 4:
            from .units import infer_default_unit

            rows = self.conn.execute("SELECT id,major,minor,name,unit FROM master_items").fetchall()
            for item in rows:
                if not (item["unit"] or "").strip():
                    self.conn.execute(
                        "UPDATE master_items SET unit=? WHERE id=?",
                        (infer_default_unit(item["major"], item["minor"], item["name"]), item["id"]),
                    )
            self.conn.execute(
                """UPDATE event_tasks
                   SET unit=(SELECT m.unit FROM master_items m WHERE m.id=event_tasks.master_item_id)
                   WHERE TRIM(COALESCE(unit,''))='' AND master_item_id IS NOT NULL"""
            )
            version = 5
        if version == 5:
            event_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(events)")}
            if "pm_vendor_id" not in event_columns:
                self.conn.execute(
                    "ALTER TABLE events ADD COLUMN pm_vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL"
                )
            task_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(event_tasks)")}
            if "pm_assignee_id" not in task_columns:
                self.conn.execute(
                    "ALTER TABLE event_tasks ADD COLUMN pm_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL"
                )
            version = 6
        if version == 6:
            # 기존 자동 일정 열을 제거하고 업무 날짜를 선택 입력값으로 바꾼다.
            # 기존 행사에 이미 저장된 날짜는 그대로 옮겨 사용자 데이터를 보존한다.
            self.conn.executescript(
                """
                PRAGMA foreign_keys=OFF;
                PRAGMA legacy_alter_table=ON;
                ALTER TABLE event_tasks RENAME TO event_tasks_pre_v7;
                CREATE TABLE event_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    master_item_id INTEGER REFERENCES master_items(id) ON DELETE SET NULL,
                    major TEXT NOT NULL, minor TEXT NOT NULL, name TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '', required INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL DEFAULT '미착수'
                        CHECK(status IN ('미착수','진행중','확인요청','완료','보류','해당없음')),
                    priority TEXT NOT NULL DEFAULT '중' CHECK(priority IN ('상','중','하')),
                    quantity REAL, unit TEXT NOT NULL DEFAULT '',
                    assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                    pm_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                    vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                    planned_start TEXT, due_date TEXT, cost REAL, unit_price INTEGER,
                    vat_type TEXT NOT NULL DEFAULT 'TAXABLE' CHECK(vat_type IN ('TAXABLE','EXEMPT')),
                    is_removed INTEGER NOT NULL DEFAULT 0, removed_reason TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '', completed_at TEXT, sort_order INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK(planned_start IS NULL OR due_date IS NULL OR planned_start <= due_date)
                );
                INSERT INTO event_tasks(
                    id,event_id,master_item_id,major,minor,name,detail,required,status,priority,
                    quantity,unit,assignee_id,pm_assignee_id,vendor_id,planned_start,due_date,cost,
                    unit_price,vat_type,is_removed,removed_reason,note,completed_at,sort_order,created_at,updated_at
                ) SELECT
                    id,event_id,master_item_id,major,minor,name,detail,required,status,priority,
                    quantity,unit,assignee_id,pm_assignee_id,vendor_id,planned_start,due_date,cost,
                    unit_price,vat_type,is_removed,removed_reason,note,completed_at,sort_order,created_at,updated_at
                  FROM event_tasks_pre_v7;
                DROP TABLE event_tasks_pre_v7;

                ALTER TABLE master_items RENAME TO master_items_pre_v7;
                CREATE TABLE master_items (
                    id INTEGER PRIMARY KEY, major TEXT NOT NULL, minor TEXT NOT NULL, name TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    priority TEXT NOT NULL DEFAULT '중' CHECK(priority IN ('상','중','하')),
                    quantity REAL, unit TEXT NOT NULL DEFAULT '', base_unit_price INTEGER,
                    default_vat_type TEXT NOT NULL DEFAULT 'TAXABLE' CHECK(default_vat_type IN ('TAXABLE','EXEMPT')),
                    default_vendor_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                    default_assignee_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
                    sort_order INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 1
                );
                INSERT INTO master_items(
                    id,major,minor,name,detail,priority,quantity,unit,base_unit_price,default_vat_type,
                    default_vendor_id,default_assignee_id,sort_order,active
                ) SELECT
                    id,major,minor,name,detail,priority,quantity,unit,base_unit_price,default_vat_type,
                    default_vendor_id,default_assignee_id,sort_order,active
                  FROM master_items_pre_v7;
                DROP TABLE master_items_pre_v7;
                CREATE INDEX idx_tasks_event ON event_tasks(event_id);
                CREATE INDEX idx_tasks_due ON event_tasks(due_date);
                CREATE INDEX idx_tasks_status ON event_tasks(status);
                CREATE UNIQUE INDEX idx_event_master_unique
                    ON event_tasks(event_id, master_item_id) WHERE master_item_id IS NOT NULL;
                PRAGMA legacy_alter_table=OFF;
                PRAGMA foreign_keys=ON;
                """
            )
            version = 7
        if version == 7:
            contact_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(contacts)")}
            if "job_title" not in contact_columns:
                self.conn.execute("ALTER TABLE contacts ADD COLUMN job_title TEXT NOT NULL DEFAULT ''")
            version = 8
        if version == 8:
            event_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(events)")}
            if "event_start_date" not in event_columns:
                self.conn.execute("ALTER TABLE events ADD COLUMN event_start_date TEXT")
            if "event_end_date" not in event_columns:
                self.conn.execute("ALTER TABLE events ADD COLUMN event_end_date TEXT")
            # 이전 버전에는 행사 마지막 날만 기록했다. 기존 데이터는 하루 행사로
            # 보존하고, 여러 날 행사는 수정 화면에서 정확한 시작·마감일을 입력한다.
            self.conn.execute(
                "UPDATE events SET event_start_date=end_date, event_end_date=end_date "
                "WHERE end_date IS NOT NULL AND event_start_date IS NULL"
            )
            version = 9
        if version == 9:
            # v9의 별도 행사 기간을 표준 시작일·마감일로 승격한다.
            # 준비기간/최종 행사일 개념은 더 이상 유지하지 않는다.
            self.conn.execute(
                "UPDATE events SET start_date=COALESCE(event_start_date,start_date), "
                "end_date=COALESCE(event_end_date,event_start_date,end_date)"
            )
            self.conn.execute("ALTER TABLE events DROP COLUMN event_start_date")
            self.conn.execute("ALTER TABLE events DROP COLUMN event_end_date")
            version = 10
        if version != SCHEMA_VERSION:
            raise RuntimeError(f"DB 마이그레이션 경로가 없습니다: {from_version} → {SCHEMA_VERSION}")
        self.conn.execute("UPDATE schema_info SET version=?", (SCHEMA_VERSION,))

    def _seed_master_items(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM master_items").fetchone()[0]
        if count:
            return
        resource = files("event_checklist").joinpath("resources/master_items.json")
        items = json.loads(resource.read_text(encoding="utf-8"))
        from .units import infer_default_unit
        for item in items:
            if not (item.get("unit") or "").strip():
                item["unit"] = infer_default_unit(item["major"], item["minor"], item["name"])
        self.conn.executemany(
            """
            INSERT INTO master_items(
                id, major, minor, name, detail, quantity, unit, sort_order, active
            ) VALUES (
                :id, :major, :minor, :name, :detail, :quantity, :unit, :sort_order, :active
            )
            """,
            items,
        )

    def _seed_contacts(self) -> None:
        count = self.conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        if count:
            return
        people = ["총괄", "기획", "무대/시스템", "시설", "홍보", "운영", "행정", "안전", "기록"]
        self.conn.executemany(
            "INSERT INTO contacts(kind, name) VALUES ('PERSON', ?)", [(name,) for name in people]
        )
        self.conn.execute("INSERT INTO contacts(kind, name) VALUES ('VENDOR', '(업체 미정)')")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        if self._is_domain_mutation(sql):
            with self.history_action():
                cursor = self.conn.execute(sql, params)
                self.conn.commit()
                return cursor
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def checkpoint(self) -> None:
        self.conn.commit()
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @staticmethod
    def _is_domain_mutation(sql: str) -> bool:
        normalized = " ".join(sql.strip().lower().split())
        if not normalized.startswith(("insert ", "update ", "delete ", "replace ")):
            return False
        return not any(token in normalized for token in (
            " into settings", " update settings", " from settings",
            " into schema_info", " update schema_info", " from schema_info",
        ))

    def enable_history(self, directory: Path, limit: int = 50) -> None:
        """Enable lightweight, session-scoped full database undo snapshots."""
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        session = root / f"session_{datetime.now():%Y%m%d_%H%M%S}_{os.getpid()}"
        session.mkdir(parents=True, exist_ok=True)
        self._history_directory = session
        self._history_limit = max(1, int(limit))
        self._dirty = False
        self._notify_history_changed()

    def add_history_listener(self, callback) -> None:
        if callback not in self._history_listeners:
            self._history_listeners.append(callback)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    def mark_backed_up(self) -> None:
        self._dirty = False

    def _notify_history_changed(self) -> None:
        for callback in tuple(self._history_listeners):
            try:
                callback(self.can_undo, self.can_redo)
            except RuntimeError:
                self._history_listeners.remove(callback)

    def _snapshot(self, kind: str) -> Path:
        if self._history_directory is None:
            raise RuntimeError("변경 이력이 활성화되지 않았습니다.")
        self._history_counter += 1
        target = self._history_directory / f"{kind}_{self._history_counter:06d}.db"
        self.conn.commit()
        target_conn = sqlite3.connect(target)
        try:
            self.conn.backup(target_conn)
        finally:
            target_conn.close()
        return target

    @staticmethod
    def _discard(paths: list[Path]) -> None:
        for path in paths:
            path.unlink(missing_ok=True)
        paths.clear()

    def _trim(self, stack: list[Path]) -> None:
        while len(stack) > self._history_limit:
            stack.pop(0).unlink(missing_ok=True)

    @contextmanager
    def history_action(self):
        outermost = self._history_directory is not None and self._history_depth == 0
        snapshot = self._snapshot("undo") if outermost else None
        self._history_depth += 1
        try:
            yield
        except Exception:
            if snapshot is not None:
                # A grouped action may contain more than one committed service call.
                # Restore the starting point so a partially completed edit is never left behind.
                self._restore_history_snapshot(snapshot)
                snapshot.unlink(missing_ok=True)
            raise
        else:
            if snapshot is not None:
                self._undo_stack.append(snapshot)
                self._trim(self._undo_stack)
                self._discard(self._redo_stack)
                self._dirty = True
                self._notify_history_changed()
        finally:
            self._history_depth -= 1

    def _restore_history_snapshot(self, source: Path) -> None:
        temporary = self.path.with_suffix(".history-restore.tmp")
        self.close()
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
            self.open()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        current = self._snapshot("redo")
        target = self._undo_stack.pop()
        self._redo_stack.append(current)
        self._trim(self._redo_stack)
        self._restore_history_snapshot(target)
        target.unlink(missing_ok=True)
        self._dirty = True
        self._notify_history_changed()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        current = self._snapshot("undo")
        target = self._redo_stack.pop()
        self._undo_stack.append(current)
        self._trim(self._undo_stack)
        self._restore_history_snapshot(target)
        target.unlink(missing_ok=True)
        self._dirty = True
        self._notify_history_changed()
        return True

    def clear_history(self) -> None:
        self._discard(self._undo_stack)
        self._discard(self._redo_stack)
        self._notify_history_changed()

    def cleanup_history(self) -> None:
        directory = self._history_directory
        self.clear_history()
        self._history_directory = None
        if directory is not None:
            try:
                directory.rmdir()
            except OSError:
                pass
