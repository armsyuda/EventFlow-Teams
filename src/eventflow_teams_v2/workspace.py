from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from event_checklist.database import Database


def workspace_root(data_root: Path, user_id: str, organization_id: str) -> Path:
    """Return an isolated, plaintext V2 workspace path for one membership."""
    if not user_id or not organization_id:
        raise ValueError("사용자와 회사를 먼저 선택해야 합니다.")
    return data_root / "workspaces" / user_id / organization_id


def workspace_database_path(data_root: Path, user_id: str, organization_id: str) -> Path:
    return workspace_root(data_root, user_id, organization_id) / "data" / "event_checklist.db"


def clear_workspace(data_root: Path, user_id: str, organization_id: str) -> None:
    """Delete one exact V2 workspace, never an arbitrary caller-provided path."""
    root = (data_root / "workspaces").resolve()
    target = workspace_root(data_root, user_id, organization_id).resolve()
    if root not in target.parents:
        raise RuntimeError("유효하지 않은 V2 작업본 경로입니다.")
    if target.exists():
        shutil.rmtree(target)


def clear_user_workspaces(data_root: Path, user_id: str) -> None:
    """Logout cleanup: remove all company workspaces belonging to one user only."""
    root = (data_root / "workspaces").resolve()
    target = (root / user_id).resolve()
    if root not in target.parents:
        raise RuntimeError("유효하지 않은 V2 사용자 작업본 경로입니다.")
    if target.exists():
        shutil.rmtree(target)


class WorkspaceDatabase(Database):
    """Local-compatible database with V2-only synchronization metadata.

    Local domain tables remain untouched.  The later sync worker uses these
    tables to map server UUIDs, persist an outbox, conflicts, and watermarks.
    """

    def __init__(self, path: Path, *, user_id: str, organization_id: str) -> None:
        self.workspace_user_id = user_id
        self.workspace_organization_id = organization_id
        self._existing_cursor = ""
        self._existing_pending = False
        self._outbox_high_water = 0
        self._prepare_existing_workspace_for_baseline_open(Path(path))
        super().__init__(path)
        self._initialize_v2_metadata()
        self._remove_reopened_baseline_seeds()

    def _prepare_existing_workspace_for_baseline_open(self, path: Path) -> None:
        """Stop Local's seed routine from becoming a user edit on reopening.

        ``Database.initialize`` runs before V2 metadata is normally available.
        A previously synchronized empty directory would therefore seed Local
        defaults while its persisted triggers are already active.  Set the
        exact workspace control flag first, then clean only those new seeds
        after the baseline initializer finishes.
        """
        if not path.exists():
            return
        connection = sqlite3.connect(path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"teams_v2_workspace", "teams_v2_sync_control", "teams_v2_outbox"}.issubset(tables):
                return
            workspace = connection.execute("SELECT remote_cursor FROM teams_v2_workspace WHERE singleton=1").fetchone()
            self._existing_cursor = str(workspace[0] or "") if workspace else ""
            self._existing_pending = connection.execute("SELECT EXISTS(SELECT 1 FROM teams_v2_outbox WHERE status='PENDING')").fetchone()[0] == 1
            self._outbox_high_water = int(connection.execute("SELECT COALESCE(MAX(id),0) FROM teams_v2_outbox").fetchone()[0])
            connection.execute("UPDATE teams_v2_sync_control SET suppress_capture=1 WHERE singleton=1")
            connection.commit()
        finally:
            connection.close()

    def _remove_reopened_baseline_seeds(self) -> None:
        if not self._existing_cursor:
            return
        try:
            # Never discard actual unsent Local work.  Only a clean cached
            # workspace can have its baseline-generated, unmapped directory
            # rows removed safely.
            if not self._existing_pending:
                self.conn.execute("DELETE FROM master_items WHERE id NOT IN (SELECT local_id FROM teams_v2_entity_map WHERE entity_type='MASTER_ITEM')")
                self.conn.execute("DELETE FROM contacts WHERE id NOT IN (SELECT local_id FROM teams_v2_entity_map WHERE entity_type IN ('VENDOR','PERSON'))")
            self.conn.execute("DELETE FROM teams_v2_outbox WHERE id>?", (self._outbox_high_water,))
        finally:
            self.conn.execute("UPDATE teams_v2_sync_control SET suppress_capture=0 WHERE singleton=1")
            self.conn.commit()

    def _initialize_v2_metadata(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams_v2_workspace (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                user_id TEXT NOT NULL,
                organization_id TEXT NOT NULL,
                remote_cursor TEXT NOT NULL DEFAULT '',
                last_sync_at TEXT,
                sync_state TEXT NOT NULL DEFAULT 'LOCAL_ONLY'
            );
            CREATE TABLE IF NOT EXISTS teams_v2_entity_map (
                entity_type TEXT NOT NULL,
                local_id INTEGER NOT NULL,
                remote_id TEXT NOT NULL,
                remote_version INTEGER NOT NULL DEFAULT 0,
                remote_updated_at TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (entity_type, local_id),
                UNIQUE (entity_type, remote_id)
            );
            CREATE TABLE IF NOT EXISTS teams_v2_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mutation_id TEXT NOT NULL UNIQUE,
                entity_type TEXT NOT NULL,
                local_id INTEGER,
                operation TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                base_version INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'PENDING',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS teams_v2_sync_control (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                suppress_capture INTEGER NOT NULL DEFAULT 0 CHECK (suppress_capture IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS teams_v2_tombstones (
                entity_type TEXT NOT NULL,
                remote_id TEXT NOT NULL,
                deleted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (entity_type, remote_id)
            );
            CREATE TABLE IF NOT EXISTS teams_v2_conflicts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                local_id INTEGER,
                server_payload_json TEXT NOT NULL,
                local_payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS teams_v2_staff_members (
                user_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'MEMBER',
                job_title TEXT NOT NULL DEFAULT '',
                color_hex TEXT NOT NULL DEFAULT '#A7D4F0',
                status TEXT NOT NULL DEFAULT 'ACTIVE'
            );
            CREATE TABLE IF NOT EXISTS teams_v2_personal_schedules (
                id TEXT PRIMARY KEY,
                member_user_id TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                title TEXT NOT NULL,
                private_content TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                can_edit INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS teams_v2_personal_schedules_dates_idx
                ON teams_v2_personal_schedules(start_date,end_date);
            CREATE TABLE IF NOT EXISTS teams_v2_my_task_priorities (
                event_task_id TEXT PRIMARY KEY, sort_order INTEGER NOT NULL
            );
            """
        )
        task_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(event_tasks)")}
        if "assigned_member_user_id" not in task_columns:
            self.conn.execute("ALTER TABLE event_tasks ADD COLUMN assigned_member_user_id TEXT")
        schedule_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(teams_v2_personal_schedules)")}
        if "sort_order" not in schedule_columns:
            self.conn.execute("ALTER TABLE teams_v2_personal_schedules ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
        self.conn.execute(
            "INSERT OR IGNORE INTO teams_v2_workspace(singleton,user_id,organization_id) VALUES (1,?,?)",
            (self.workspace_user_id, self.workspace_organization_id),
        )
        self.conn.execute("INSERT OR IGNORE INTO teams_v2_sync_control(singleton) VALUES (1)")
        map_columns = {item["name"] for item in self.conn.execute("PRAGMA table_info(teams_v2_entity_map)")}
        if "remote_updated_at" not in map_columns:
            self.conn.execute("ALTER TABLE teams_v2_entity_map ADD COLUMN remote_updated_at TEXT NOT NULL DEFAULT ''")
        row = self.conn.execute("SELECT user_id,organization_id FROM teams_v2_workspace WHERE singleton=1").fetchone()
        if not row or row["user_id"] != self.workspace_user_id or row["organization_id"] != self.workspace_organization_id:
            raise RuntimeError("다른 사용자 또는 회사의 작업본을 열 수 없습니다.")
        self._install_outbox_triggers()
        self.conn.commit()

    def _install_outbox_triggers(self) -> None:
        """Capture Local baseline mutations without changing any Local UI code.

        The payload intentionally identifies the changed Local row only.  The
        V2 encoder reads the complete current row when it sends a mutation,
        so edits made by a dialog, bulk action, or direct SQL share one safe
        capture path.  Remote imports flip ``suppress_capture`` and therefore
        never echo back into the outbox.
        """
        mutation_id = (
            "lower(hex(randomblob(4))) || '-' || lower(hex(randomblob(2))) || '-' || "
            "lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(2))) || '-' || lower(hex(randomblob(6)))"
        )
        def enqueue(entity_type: str, local_id: str, operation: str, payload: str) -> str:
            return f"""
              INSERT INTO teams_v2_outbox(mutation_id,entity_type,local_id,operation,payload_json,base_version)
              SELECT {mutation_id}, '{entity_type}', {local_id}, '{operation}', {payload},
                COALESCE((SELECT remote_version FROM teams_v2_entity_map
                  WHERE entity_type='{entity_type}' AND local_id={local_id}), 0)
              WHERE (SELECT suppress_capture FROM teams_v2_sync_control WHERE singleton=1)=0;
            """
        definitions = {
            "events": ("EVENT", "NEW.id", "OLD.id"),
            "master_items": ("MASTER_ITEM", "NEW.id", "OLD.id"),
        }
        statements: list[str] = []
        for table, (entity, new_id, old_id) in definitions.items():
            statements.extend((
                f"DROP TRIGGER IF EXISTS teams_v2_{table}_insert;",
                f"DROP TRIGGER IF EXISTS teams_v2_{table}_update;",
                f"DROP TRIGGER IF EXISTS teams_v2_{table}_delete;",
                f"CREATE TRIGGER teams_v2_{table}_insert AFTER INSERT ON {table} BEGIN"
                + enqueue(entity, new_id, "LOCAL_UPSERT", f"json_object('local_id',{new_id},'action','INSERT')") + " END;",
                f"CREATE TRIGGER teams_v2_{table}_update AFTER UPDATE ON {table} BEGIN"
                + enqueue(entity, new_id, "LOCAL_UPSERT", f"json_object('local_id',{new_id},'action','UPDATE')") + " END;",
                f"CREATE TRIGGER teams_v2_{table}_delete AFTER DELETE ON {table} BEGIN"
                + enqueue(entity, old_id, "LOCAL_DELETE", f"json_object('local_id',{old_id},'action','DELETE')") + " END;",
            ))
        # A Local task can change checklist, settlement, assignment, and
        # structure fields independently.  Keep those server permission
        # domains as separate queue records instead of widening one RPC.
        statements.extend((
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_insert;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_delete;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_patch;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_cost;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_content;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_assign;",
            "DROP TRIGGER IF EXISTS teams_v2_event_tasks_structure;",
            "CREATE TRIGGER teams_v2_event_tasks_insert AFTER INSERT ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_CREATE", "json_object('local_id',NEW.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_delete AFTER DELETE ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "OLD.id", "LOCAL_DELETE", "json_object('local_id',OLD.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_patch AFTER UPDATE OF status,planned_start,due_date,note,required,is_removed,removed_reason ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_TASK_PATCH", "json_object('local_id',NEW.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_cost AFTER UPDATE OF quantity,unit,unit_price,vat_type ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_TASK_COST", "json_object('local_id',NEW.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_content AFTER UPDATE OF name,detail ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_TASK_CONTENT", "json_object('local_id',NEW.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_assign AFTER UPDATE OF pm_assignee_id,vendor_id,assignee_id ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_TASK_ASSIGN", "json_object('local_id',NEW.id)") + " END;",
            "CREATE TRIGGER teams_v2_event_tasks_structure AFTER UPDATE OF major,minor,sort_order,master_item_id ON event_tasks BEGIN"
            + enqueue("EVENT_TASK", "NEW.id", "LOCAL_TASK_STRUCTURE", "json_object('local_id',NEW.id)") + " END;",
        ))
        # Local keeps vendors and people in one contacts table; preserve the
        # server's separate UUID namespaces in the outbox and entity map.
        statements.extend((
            "DROP TRIGGER IF EXISTS teams_v2_contacts_insert;",
            "DROP TRIGGER IF EXISTS teams_v2_contacts_update;",
            "DROP TRIGGER IF EXISTS teams_v2_contacts_delete;",
            "CREATE TRIGGER teams_v2_contacts_insert AFTER INSERT ON contacts BEGIN"
            + enqueue("VENDOR", "NEW.id", "LOCAL_UPSERT", "json_object('local_id',NEW.id,'action','INSERT')").replace("'VENDOR'", "CASE WHEN NEW.kind='VENDOR' THEN 'VENDOR' ELSE 'PERSON' END") + " END;",
            "CREATE TRIGGER teams_v2_contacts_update AFTER UPDATE ON contacts BEGIN"
            + enqueue("VENDOR", "NEW.id", "LOCAL_UPSERT", "json_object('local_id',NEW.id,'action','UPDATE')").replace("'VENDOR'", "CASE WHEN NEW.kind='VENDOR' THEN 'VENDOR' ELSE 'PERSON' END") + " END;",
            "CREATE TRIGGER teams_v2_contacts_delete AFTER DELETE ON contacts BEGIN"
            + enqueue("VENDOR", "OLD.id", "LOCAL_DELETE", "json_object('local_id',OLD.id,'action','DELETE')").replace("'VENDOR'", "CASE WHEN OLD.kind='VENDOR' THEN 'VENDOR' ELSE 'PERSON' END") + " END;",
        ))
        for table, person_column in (("event_vendors", "vendor_id"), ("event_freelancers", "person_id")):
            statements.extend((
                f"DROP TRIGGER IF EXISTS teams_v2_{table}_insert;",
                f"DROP TRIGGER IF EXISTS teams_v2_{table}_delete;",
                f"CREATE TRIGGER teams_v2_{table}_insert AFTER INSERT ON {table} BEGIN"
                + enqueue("EVENT_PARTICIPANTS", "NEW.event_id", "LOCAL_PARTICIPANTS_SYNC", f"json_object('event_local_id',NEW.event_id,'reference_local_id',NEW.{person_column})") + " END;",
                f"CREATE TRIGGER teams_v2_{table}_delete AFTER DELETE ON {table} BEGIN"
                + enqueue("EVENT_PARTICIPANTS", "OLD.event_id", "LOCAL_PARTICIPANTS_SYNC", f"json_object('event_local_id',OLD.event_id,'reference_local_id',OLD.{person_column})") + " END;",
            ))
        self.conn.executescript("\n".join(statements))

    @contextmanager
    def applying_remote_changes(self) -> Iterator[None]:
        """Temporarily turn off capture while a server snapshot/change is applied."""
        self.conn.execute("UPDATE teams_v2_sync_control SET suppress_capture=1 WHERE singleton=1")
        try:
            yield
        finally:
            self.conn.execute("UPDATE teams_v2_sync_control SET suppress_capture=0 WHERE singleton=1")
            self.conn.commit()

    def pending_outbox(self) -> list[dict[str, object]]:
        rows = self.conn.execute(
            "SELECT * FROM teams_v2_outbox WHERE status='PENDING' ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def set_access_context(self, *, role: str, permissions: set[str]) -> None:
        """Persist only non-secret UI capability metadata for the next local launch."""
        self.conn.execute(
            "ALTER TABLE teams_v2_workspace ADD COLUMN role TEXT NOT NULL DEFAULT ''"
        ) if "role" not in {row["name"] for row in self.conn.execute("PRAGMA table_info(teams_v2_workspace)")} else None
        self.conn.execute(
            "ALTER TABLE teams_v2_workspace ADD COLUMN permissions_json TEXT NOT NULL DEFAULT '[]'"
        ) if "permissions_json" not in {row["name"] for row in self.conn.execute("PRAGMA table_info(teams_v2_workspace)")} else None
        import json
        self.conn.execute(
            "UPDATE teams_v2_workspace SET role=?, permissions_json=? WHERE singleton=1",
            (role, json.dumps(sorted(permissions), ensure_ascii=False)),
        )
        self.conn.commit()
