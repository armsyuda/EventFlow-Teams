from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from .database import Database


class EventService:
    def __init__(self, db: Database):
        self.db = db

    def list_events(self):
        return self.db.query("SELECT * FROM events ORDER BY start_date DESC, id DESC")

    def get_event(self, event_id: int):
        return self.db.one("SELECT * FROM events WHERE id=?", (event_id,))

    def create_event(
        self,
        name: str,
        start_date: date,
        end_date: date | None,
        selected_master_ids: Iterable[int] = (),
        location: str = "",
        organizer: str = "",
        budget: float | None = None,
        budget_tax_mode: str = "UNSET",
        pm_vendor_id: int | None = None,
        vendor_ids: Iterable[int] = (),
        freelancer_ids: Iterable[int] = (),
        source_event_id: int | None = None,
        source_task_ids: Iterable[int] = (),
        copy_settlement_prices: bool = False,
    ) -> int:
        name = name.strip()
        if not name:
            raise ValueError("행사명을 입력하세요.")
        if end_date and end_date < start_date:
            raise ValueError("행사 마감일은 행사 시작일보다 빠를 수 없습니다.")
        ids = list(dict.fromkeys(int(value) for value in selected_master_ids))
        imported_ids = list(dict.fromkeys(int(value) for value in source_task_ids))
        if source_event_id is not None:
            if ids:
                raise ValueError("기본 항목과 이전 행사 항목을 동시에 가져올 수 없습니다.")
            if not imported_ids:
                raise ValueError("이전 행사에서 가져올 항목을 선택하세요.")
            placeholders = ",".join("?" for _ in imported_ids)
            imported_tasks = self.db.query(
                f"""SELECT * FROM event_tasks
                    WHERE event_id=? AND is_removed=0 AND id IN ({placeholders})
                    ORDER BY sort_order,id""",
                (int(source_event_id), *imported_ids),
            )
            if len(imported_tasks) != len(imported_ids):
                raise ValueError("이전 행사의 선택 항목 중 가져올 수 없는 항목이 있습니다.")
            masters = []
        else:
            if not ids:
                raise ValueError("하나 이상의 기본 항목을 선택하세요.")
            placeholders = ",".join("?" for _ in ids)
            masters = self.db.query(
                f"SELECT * FROM master_items WHERE id IN ({placeholders}) ORDER BY sort_order", ids
            )
            if len(masters) != len(ids):
                raise ValueError("선택한 기본 항목 중 사용할 수 없는 항목이 있습니다.")
            imported_tasks = []

        selected_vendors = {int(value) for value in vendor_ids}
        if pm_vendor_id:
            selected_vendors.add(int(pm_vendor_id))
        selected_freelancers = {int(value) for value in freelancer_ids}
        selected_vendors.update(int(item["default_vendor_id"]) for item in masters if item["default_vendor_id"])
        for item in masters:
            if not item["default_assignee_id"]:
                continue
            contact = self.db.one("SELECT company_id FROM contacts WHERE id=?", (item["default_assignee_id"],))
            if contact and contact["company_id"]:
                selected_vendors.add(int(contact["company_id"]))
            elif contact:
                selected_freelancers.add(int(item["default_assignee_id"]))

        with self.db.transaction() as conn:
            cursor = conn.execute(
                """INSERT INTO events(name,start_date,end_date,location,organizer,budget,budget_tax_mode,pm_vendor_id)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (name, start_date.isoformat(), end_date.isoformat() if end_date else None,
                 location.strip(), organizer.strip(), budget, budget_tax_mode, pm_vendor_id),
            )
            event_id = int(cursor.lastrowid)
            conn.executemany(
                "INSERT OR IGNORE INTO event_vendors(event_id,vendor_id) VALUES (?,?)",
                [(event_id, value) for value in sorted(selected_vendors)],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO event_freelancers(event_id,person_id) VALUES (?,?)",
                [(event_id, value) for value in sorted(selected_freelancers)],
            )
            for item in masters:
                conn.execute(
                    """
                    INSERT INTO event_tasks(
                        event_id,master_item_id,major,minor,name,detail,status,quantity,unit,assignee_id,vendor_id,
                        planned_start,due_date,sort_order,unit_price,vat_type
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id, item["id"], item["major"], item["minor"], item["name"], item["detail"],
                        "미착수", item["quantity"], item["unit"],
                        item["default_assignee_id"], item["default_vendor_id"],
                        None, None, item["sort_order"],
                        item["base_unit_price"], item["default_vat_type"],
                    ),
                )
            for item in imported_tasks:
                conn.execute(
                    """
                    INSERT INTO event_tasks(
                        event_id,master_item_id,major,minor,name,detail,required,status,priority,
                        quantity,unit,planned_start,due_date,sort_order,unit_price,vat_type
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        event_id, item["master_item_id"], item["major"], item["minor"], item["name"],
                        item["detail"], item["required"], "미착수", item["priority"], 1, item["unit"],
                        None, None, item["sort_order"],
                        item["unit_price"] if copy_settlement_prices else 0, item["vat_type"],
                    ),
                )
        return event_id

    def update_event(
        self,
        event_id: int,
        name: str,
        start_date: date,
        end_date: date | None,
        location: str = "",
        organizer: str = "",
        budget: float | None = None,
        budget_tax_mode: str = "UNSET",
        pm_vendor_id: int | None = None,
        rebase_auto: bool = True,
    ) -> None:
        if not name.strip():
            raise ValueError("행사명을 입력하세요.")
        if end_date and end_date < start_date:
            raise ValueError("행사 마감일은 행사 시작일보다 빠를 수 없습니다.")
        with self.db.transaction() as conn:
            conn.execute(
                """UPDATE events SET name=?,start_date=?,end_date=?,location=?,organizer=?,budget=?,budget_tax_mode=?,pm_vendor_id=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (name.strip(), start_date.isoformat(), end_date.isoformat() if end_date else None,
                 location.strip(), organizer.strip(), budget, budget_tax_mode, pm_vendor_id, event_id),
            )
            conn.execute(
                """UPDATE event_tasks SET pm_assignee_id=NULL
                   WHERE event_id=? AND pm_assignee_id IS NOT NULL
                     AND pm_assignee_id NOT IN (
                       SELECT id FROM contacts WHERE kind='PERSON' AND company_id=?
                     )""",
                (event_id, pm_vendor_id),
            )

    def delete_event(self, event_id: int) -> None:
        self.db.execute("DELETE FROM events WHERE id=?", (event_id,))

    def list_tasks(self, event_id: int, search: str = "", status: str = "", major: str = "",
                   include_removed: bool = False, vendor_id: int | None = None,
                   pm_assignee_id: int | None = None):
        sql = """
            SELECT t.*, p.name AS assignee_name, p.phone AS assignee_phone,
                   pm.name AS pm_assignee_name, v.name AS vendor_name
            FROM event_tasks t
            LEFT JOIN contacts p ON p.id=t.assignee_id
            LEFT JOIN contacts pm ON pm.id=t.pm_assignee_id
            LEFT JOIN contacts v ON v.id=t.vendor_id
            WHERE t.event_id=?
        """
        params: list[object] = [event_id]
        if not include_removed:
            sql += " AND t.is_removed=0"
        if search:
            sql += " AND (t.name LIKE ? OR t.detail LIKE ? OR t.note LIKE ?)"
            value = f"%{search}%"
            params.extend([value, value, value])
        if status:
            sql += " AND t.status=?"
            params.append(status)
        if major:
            sql += " AND t.major=?"
            params.append(major)
        if vendor_id is not None:
            sql += " AND t.vendor_id=?"
            params.append(int(vendor_id))
        if pm_assignee_id is not None:
            sql += " AND t.pm_assignee_id=?"
            params.append(int(pm_assignee_id))
        # 분류 셀을 한 덩어리로 병합할 수 있도록 같은 대분류와 중분류를
        # 반드시 인접하게 둔다. 각 분류의 최초 sort_order로 기존 분류 순서를
        # 보존하고, 나중에 추가한 항목도 선택한 분류 안쪽에 배치한다.
        sql += """ ORDER BY
            (SELECT MIN(g.sort_order) FROM event_tasks g
             WHERE g.event_id=t.event_id AND g.major=t.major AND g.is_removed=0),
            (SELECT MIN(g.sort_order) FROM event_tasks g
             WHERE g.event_id=t.event_id AND g.major=t.major AND g.minor=t.minor AND g.is_removed=0),
            t.sort_order, t.id"""
        return self.db.query(sql, params)

    def update_task(self, task_id: int, **fields) -> None:
        allowed = {
            "name", "status", "quantity", "unit", "assignee_id", "pm_assignee_id", "vendor_id",
            "planned_start", "due_date", "cost", "note", "detail", "required",
            "unit_price", "vat_type", "is_removed", "removed_reason",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"수정할 수 없는 필드: {', '.join(sorted(unknown))}")
        if not fields:
            return
        row = self.db.one("SELECT planned_start,due_date,status FROM event_tasks WHERE id=?", (task_id,))
        if row is None:
            raise ValueError("업무를 찾을 수 없습니다.")
        for key in ("planned_start", "due_date"):
            if key in fields and not fields[key]:
                fields[key] = None
        planned = fields.get("planned_start", row["planned_start"])
        due = fields.get("due_date", row["due_date"])
        if planned and due and planned > due:
            raise ValueError("작업 시작일은 마감일보다 늦을 수 없습니다.")
        if "status" in fields:
            fields["completed_at"] = datetime.now().isoformat(timespec="seconds") if fields["status"] == "완료" else None
            allowed.add("completed_at")
        assignments = ",".join(f"{key}=?" for key in fields)
        values = list(fields.values()) + [task_id]
        self.db.execute(
            f"UPDATE event_tasks SET {assignments},updated_at=CURRENT_TIMESTAMP WHERE id=?", values
        )

    def bulk_assign_tasks(self, event_id: int, task_ids: Iterable[int], **assignments) -> int:
        """Assign PM, vendor, and vendor contact to several active tasks atomically."""
        allowed = {"pm_assignee_id", "vendor_id", "assignee_id"}
        unknown = set(assignments) - allowed
        if unknown:
            raise ValueError(f"일괄 지정할 수 없는 필드: {', '.join(sorted(unknown))}")
        ids = list(dict.fromkeys(int(value) for value in task_ids))
        if not ids or not assignments:
            return 0
        placeholders = ",".join("?" for _ in ids)
        tasks = self.db.query(
            f"SELECT id,vendor_id FROM event_tasks WHERE event_id=? AND is_removed=0 AND id IN ({placeholders})",
            (event_id, *ids),
        )
        if len(tasks) != len(ids):
            raise ValueError("선택한 항목 중 현재 행사에서 변경할 수 없는 항목이 있습니다.")

        if "pm_assignee_id" in assignments and assignments["pm_assignee_id"] is not None:
            event = self.get_event(event_id)
            person = self.db.one(
                "SELECT kind,company_id FROM contacts WHERE id=?", (assignments["pm_assignee_id"],)
            )
            if not person or person["kind"] != "PERSON" or person["company_id"] != event["pm_vendor_id"]:
                raise ValueError("담당자(PM)는 이 행사의 PM 업체 소속 담당자만 지정할 수 있습니다.")

        if "vendor_id" in assignments and assignments["vendor_id"] is not None:
            vendor = self.db.one("SELECT kind FROM contacts WHERE id=?", (assignments["vendor_id"],))
            if not vendor or vendor["kind"] != "VENDOR":
                raise ValueError("선택한 업체를 찾을 수 없습니다.")
        if "vendor_id" in assignments:
            # 업체가 바뀌면 기존 업체담당자를 그대로 둘 수 없다. 지정값이 없으면
            # 미지정으로 정리해 업체와 담당자의 소속이 어긋나지 않게 한다.
            assignments.setdefault("assignee_id", None)

        if "assignee_id" in assignments and assignments["assignee_id"] is not None:
            person = self.db.one(
                "SELECT kind,company_id FROM contacts WHERE id=?", (assignments["assignee_id"],)
            )
            expected_vendor = assignments.get("vendor_id")
            if not person or person["kind"] != "PERSON" or person["company_id"] != expected_vendor:
                raise ValueError("업체담당자는 선택한 업체 소속 담당자만 지정할 수 있습니다.")

        columns = ",".join(f"{field}=?" for field in assignments)
        values = list(assignments.values())
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE event_tasks SET {columns},updated_at=CURRENT_TIMESTAMP "
                f"WHERE event_id=? AND is_removed=0 AND id IN ({placeholders})",
                (*values, event_id, *ids),
            )
        return len(ids)

    def reorder_tasks(self, event_id: int, task_id: int, target_task_id: int,
                      *, new_major: str | None = None, new_minor: str | None = None,
                      before: bool = True) -> None:
        """드래그 드롭으로 task 를 target_task 앞(before) 또는 뒤(after)로 이동한다.

        list_tasks 의 표시 순서 = (대분류 최소 sort_order, 중분류 최소 sort_order,
        개별 sort_order, id) 이므로, 분류 그룹핑을 유지한 채 task 를 원하는 위치에
        끼워 넣고 전체 sort_order 를 10 단위로 재할당해 재조회 순서를 그대로
        재현한다.

        - new_major / new_minor 를 주면 task 의 분류를 변경한다(분류 변경 승인 후).
        - task_id 와 target_task_id 가 같은 분류 내라면 그 안에서만 순서가 바뀐다.
        """
        if target_task_id == task_id:
            return
        # 분류를 바꾸려면 먼저 갱신한다(기존 소속에서 분리되어 목표 위치에 끼워진다).
        fields: dict[str, object] = {}
        if new_major is not None:
            fields["major"] = new_major
        if new_minor is not None:
            fields["minor"] = new_minor
        if fields:
            fields["id"] = task_id
            self.db.execute(
                "UPDATE event_tasks SET major=:major, minor=:minor, updated_at=CURRENT_TIMESTAMP WHERE id=:id",
                {"major": fields.get("major"), "minor": fields.get("minor"), "id": task_id},
            )

        # 현재 표시 순서(분류 그룹핑 포함)를 가져온다.
        tasks = self.list_tasks(event_id)
        order = [int(t["id"]) for t in tasks]
        if task_id not in order:
            return
        if target_task_id not in order:
            return

        # task_id 를 목표 위치에서 제거한 뒤, target_task_id 앞/뒤에 다시 삽입한다.
        order.remove(task_id)
        target_index = order.index(target_task_id)
        insert_at = target_index if before else target_index + 1
        order.insert(insert_at, task_id)

        with self.db.transaction() as conn:
            for index, tid in enumerate(order):
                conn.execute(
                    "UPDATE event_tasks SET sort_order=? WHERE id=?", ((index + 1) * 10, tid)
                )

    def set_completed(self, task_id: int, completed: bool) -> None:
        self.update_task(task_id, status="완료" if completed else "미착수")

    def rename_category(self, event_id: int, *, old_major: str, old_minor: str | None = None,
                        new_major: str | None = None, new_minor: str | None = None) -> None:
        """분류 이름을 일괄 변경한다.

        - new_major 를 주면 해당 major 를 쓰는 모든 task 의 major 를 새 값으로 바꾼다.
          (그 아래 중분류들은 major 만 바뀌고 minor 는 그대로 따라온다)
        - new_minor 를 주면 old_major 안에서 old_minor 를 쓰는 task 의 minor 를 갱신한다.
        - 편집 후 같은 분류의 MIN(sort_order) 가 유지되므로 그룹 순서는 그대로 유지된다.
        """
        assignments: list[str] = []
        set_params: list[object] = []
        if new_major is not None:
            assignments.append("major=?")
            set_params.append(str(new_major))
        if new_minor is not None:
            assignments.append("minor=?")
            set_params.append(str(new_minor))
        if not assignments:
            return
        # SET 파라미터가 먼저, THEN WHERE 파라미터 순서(SQL 자리 순서와 일치).
        where = ["event_id=?", "major=?"]
        where_params: list[object] = [event_id, str(old_major)]
        if old_minor is not None:
            if new_minor is None:
                return  # 중분류 이름을 바꾸려면 new_minor 가 필요하다
            where.append("minor=?")
            where_params.append(str(old_minor))
        elif new_minor is not None:
            # 대분류만 지정했는데 new_minor 가 오는 경우는 허용하지 않는다.
            return
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE event_tasks SET {', '.join(assignments)},updated_at=CURRENT_TIMESTAMP "
                f"WHERE {' AND '.join(where)}",
                tuple(set_params + where_params),
            )

    def move_category(self, event_id: int, *, major: str, minor: str | None = None,
                      target_major: str, target_minor: str | None = None,
                      before: bool = True) -> None:
        """분류 그룹을 통째로 목표 분류 앞(before) 또는 뒤(after)로 이동한다.

        major 만 주면 해당 대분류 그룹 전체를, major+minor 를 주면 그 중분류 그룹만
        list_tasks 순서에서 목표 분류 앞/뒤로 옮긴 뒤 sort_order 를 재할당한다.
        """
        tasks = self.list_tasks(event_id)

        def group_span(tasks, major, minor):
            indexes = [i for i, t in enumerate(tasks)
                       if t["major"] == major and (minor is None or t["minor"] == minor)]
            if not indexes:
                return None, None
            return indexes[0], indexes[-1]

        src_start, src_end = group_span(tasks, major, minor)
        if src_start is None:
            return
        src_ids = [int(tasks[i]["id"]) for i in range(src_start, src_end + 1)]

        # 나머지 task id 리스트에서 목표 분류의 id 를 찾아 그 앞/뒤에 source 그룹을 삽입한다.
        remaining = [int(t["id"]) for t in tasks if int(t["id"]) not in set(src_ids)]
        target_id_ref = None
        for i, t in enumerate(tasks):
            if t["major"] == target_major and (target_minor is None or t["minor"] == target_minor):
                if i not in range(src_start, src_end + 1):
                    target_id_ref = int(t["id"])
                    break
        if target_id_ref is None:
            return
        insert_at = remaining.index(target_id_ref) if before else remaining.index(target_id_ref) + 1
        order = remaining[:insert_at] + src_ids + remaining[insert_at:]

        with self.db.transaction() as conn:
            for index, tid in enumerate(order):
                conn.execute(
                    "UPDATE event_tasks SET sort_order=? WHERE id=?", ((index + 1) * 10, tid)
                )

    def dashboard(self, event_id: int) -> dict:
        row = self.db.one(
            """
            SELECT
                COUNT(*) total,
                SUM(CASE WHEN required=1 AND status<>'해당없음' THEN 1 ELSE 0 END) managed,
                SUM(CASE WHEN status='완료' THEN 1 ELSE 0 END) completed,
                SUM(CASE WHEN status='진행중' THEN 1 ELSE 0 END) in_progress,
                SUM(CASE WHEN status='미착수' THEN 1 ELSE 0 END) not_started,
                SUM(CASE WHEN required=1 AND status NOT IN ('완료','해당없음') AND due_date < date('now','localtime') THEN 1 ELSE 0 END) overdue
            FROM event_tasks WHERE event_id=? AND is_removed=0
            """,
            (event_id,),
        )
        data = dict(row) if row else {}
        managed = data.get("managed") or 0
        completed = data.get("completed") or 0
        data["progress"] = completed / managed if managed else 0.0
        data["urgent"] = self.db.query(
            """
            SELECT id,name,status,due_date,
                   CAST(julianday(due_date)-julianday(date('now','localtime')) AS INTEGER) remaining_days
            FROM event_tasks
            WHERE event_id=? AND is_removed=0 AND required=1 AND status NOT IN ('완료','해당없음')
              AND due_date IS NOT NULL AND due_date <= date('now','localtime','+7 day')
            ORDER BY due_date, sort_order LIMIT 12
            """,
            (event_id,),
        )
        return data

    def calendar_tasks(self, selected_date: date, event_id: int | None = None):
        sql = """
            SELECT t.*, e.name AS event_name
            FROM event_tasks t JOIN events e ON e.id=t.event_id
            WHERE t.is_removed=0 AND t.planned_start IS NOT NULL AND t.due_date IS NOT NULL
              AND ? BETWEEN t.planned_start AND t.due_date
        """
        params: list[object] = [selected_date.isoformat()]
        if event_id:
            sql += " AND t.event_id=?"
            params.append(event_id)
        sql += """ ORDER BY
            CASE WHEN t.status='완료' THEN 1 ELSE 0 END,
            CASE WHEN t.status<>'완료' AND t.due_date < date('now','localtime') THEN 0 ELSE 1 END,
            t.due_date, t.sort_order"""
        return self.db.query(sql, params)

    def calendar_range(self, first: date, last: date, event_id: int | None = None,
                       major: str = "", minor: str = "", vendor_id: int | None = None,
                       pm_assignee_id: int | None = None):
        sql = """
            SELECT id,event_id,name,major,minor,sort_order,planned_start,due_date,status
            FROM event_tasks WHERE is_removed=0 AND status NOT IN ('완료','해당없음')
              AND planned_start IS NOT NULL AND due_date IS NOT NULL
              AND due_date>=? AND planned_start<=?
        """
        params: list[object] = [first.isoformat(), last.isoformat()]
        if event_id:
            sql += " AND event_id=?"
            params.append(event_id)
        if major:
            sql += " AND major=?"
            params.append(major)
        if minor:
            sql += " AND minor=?"
            params.append(minor)
        if vendor_id is not None:
            sql += " AND vendor_id=?"
            params.append(int(vendor_id))
        if pm_assignee_id is not None:
            sql += " AND pm_assignee_id=?"
            params.append(int(pm_assignee_id))
        sql += " ORDER BY due_date, sort_order"
        return self.db.query(sql, params)

    def set_event_participants(self, event_id: int, vendor_ids=(), freelancer_ids=()) -> None:
        vendor_set = {int(value) for value in vendor_ids}
        freelancer_set = {int(value) for value in freelancer_ids}
        assigned = self.db.query(
            """SELECT DISTINCT t.vendor_id,t.assignee_id,c.company_id FROM event_tasks t
               LEFT JOIN contacts c ON c.id=t.assignee_id WHERE t.event_id=?""", (event_id,))
        for row in assigned:
            if row["vendor_id"]: vendor_set.add(int(row["vendor_id"]))
            if row["company_id"]: vendor_set.add(int(row["company_id"]))
            elif row["assignee_id"]: freelancer_set.add(int(row["assignee_id"]))
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM event_vendors WHERE event_id=?", (event_id,))
            conn.execute("DELETE FROM event_freelancers WHERE event_id=?", (event_id,))
            conn.executemany(
                "INSERT INTO event_vendors(event_id,vendor_id) VALUES (?,?)",
                [(event_id, value) for value in sorted(vendor_set)],
            )
            conn.executemany(
                "INSERT INTO event_freelancers(event_id,person_id) VALUES (?,?)",
                [(event_id, value) for value in sorted(freelancer_set)],
            )

    def event_participants(self, event_id: int) -> dict:
        return {
            "vendors": self.db.query(
                "SELECT c.* FROM contacts c JOIN event_vendors x ON x.vendor_id=c.id WHERE x.event_id=? ORDER BY c.name",
                (event_id,),
            ),
            "freelancers": self.db.query(
                "SELECT c.* FROM contacts c JOIN event_freelancers x ON x.person_id=c.id WHERE x.event_id=? ORDER BY c.name",
                (event_id,),
            ),
        }

    def available_assignees(self, event_id: int, vendor_id: int | None = None):
        params: list[object] = [event_id]
        sql = """
            SELECT DISTINCT c.* FROM contacts c
            WHERE c.kind='PERSON' AND (
                c.id IN (SELECT person_id FROM event_freelancers WHERE event_id=?)
        """
        if vendor_id:
            sql += " OR c.company_id=?"
            params.append(vendor_id)
        else:
            sql += " OR c.company_id IN (SELECT vendor_id FROM event_vendors WHERE event_id=?)"
            params.append(event_id)
        sql += ") ORDER BY c.name"
        return self.db.query(sql, params)

    def add_master_tasks(self, event_id: int, master_ids: Iterable[int]) -> tuple[int, int]:
        event = self.get_event(event_id)
        if not event:
            raise ValueError("행사를 찾을 수 없습니다.")
        restored = 0
        added = 0
        with self.db.transaction() as conn:
            for master_id in dict.fromkeys(int(value) for value in master_ids):
                existing = conn.execute(
                    "SELECT id,is_removed FROM event_tasks WHERE event_id=? AND master_item_id=?",
                    (event_id, master_id),
                ).fetchone()
                if existing:
                    if existing["is_removed"]:
                        conn.execute("UPDATE event_tasks SET is_removed=0,removed_reason='' WHERE id=?", (existing["id"],))
                        restored += 1
                    continue
                item = conn.execute("SELECT * FROM master_items WHERE id=?", (master_id,)).fetchone()
                if not item:
                    continue
                conn.execute(
                    """INSERT INTO event_tasks(
                       event_id,master_item_id,major,minor,name,detail,status,quantity,unit,
                       assignee_id,vendor_id,planned_start,due_date,
                       sort_order,unit_price,vat_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id,item["id"],item["major"],item["minor"],item["name"],item["detail"],"미착수",
                     item["quantity"],item["unit"],item["default_assignee_id"],item["default_vendor_id"],
                     None,None,item["sort_order"],item["base_unit_price"],item["default_vat_type"]),
                )
                added += 1
        return added, restored

    def add_custom_task(self, event_id: int, *, major: str, minor: str, name: str, planned_start: date | None = None,
                        due_date: date | None = None, quantity: float = 1, unit: str = "", unit_price: int | None = None,
                        vat_type: str = "TAXABLE", detail: str = "") -> int:
        if not major.strip() or not minor.strip() or not name.strip():
            raise ValueError("대분류, 중분류와 항목명을 모두 입력하세요.")
        if planned_start and due_date and planned_start > due_date:
            raise ValueError("작업 시작일은 마감일보다 늦을 수 없습니다.")
        next_order = self.db.one("SELECT COALESCE(MAX(sort_order),0)+1 n FROM event_tasks WHERE event_id=?", (event_id,))["n"]
        cursor = self.db.execute(
            """INSERT INTO event_tasks(event_id,major,minor,name,detail,status,quantity,unit,
               planned_start,due_date,sort_order,unit_price,vat_type)
               VALUES (?,?,?,?,?,'미착수',?,?,?,?,?,?,?)""",
            (event_id,major.strip(),minor.strip(),name.strip(),detail.strip(),quantity,unit.strip(),
             planned_start.isoformat() if planned_start else None,
             due_date.isoformat() if due_date else None,next_order,unit_price,vat_type),
        )
        return int(cursor.lastrowid)

    def set_task_removed(self, task_ids: Iterable[int], removed: bool, reason: str = "") -> None:
        ids = list(dict.fromkeys(int(value) for value in task_ids))
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        if not removed:
            # 복원(removed=False): 항목을 현재 화면 위치에 맞게 재배치해, 과거의 낮은
            # sort_order 가 분류를 앞으로 고정시키는 것을 방지한다.
            # - 해당 major+minor 의 활성 항목이 있으면 그 minor 의 맨 끝(MAX+10)
            # - minor 가 비어 있으면 같은 major 의 활성 항목 끝(MAX+10) → major 내 맨 뒤에 배치
            #   (전부 비어 있으면 10)
            rows = self.db.query(
                f"SELECT id,event_id,major,minor FROM event_tasks WHERE id IN ({placeholders})", ids
            )
            with self.db.transaction() as conn:
                for row in rows:
                    event_id = row["event_id"]; major = row["major"]; minor = row["minor"]
                    minor_max = conn.execute(
                        "SELECT COALESCE(MAX(sort_order),0) FROM event_tasks "
                        "WHERE event_id=? AND major=? AND minor=? AND is_removed=0 AND id<>?",
                        (event_id, major, minor, row["id"]),
                    ).fetchone()[0]
                    base = minor_max
                    if base == 0:
                        # minor 가 비어 있으면 같은 major 의 끝에 배치
                        major_max = conn.execute(
                            "SELECT COALESCE(MAX(sort_order),0) FROM event_tasks "
                            "WHERE event_id=? AND major=? AND is_removed=0 AND id<>?",
                            (event_id, major, row["id"]),
                        ).fetchone()[0]
                        base = major_max
                    conn.execute(
                        "UPDATE event_tasks SET is_removed=0,removed_reason='',sort_order=? WHERE id=?",
                        (base + 10, row["id"]),
                    )
        else:
            self.db.execute(
                f"UPDATE event_tasks SET is_removed=1,removed_reason=? WHERE id IN ({placeholders})",
                (reason.strip(), *ids),
            )

    @staticmethod
    def line_amounts(quantity, unit_price, vat_type: str) -> tuple[int, int, int]:
        if quantity is None or unit_price is None:
            return 0, 0, 0
        supply = int((Decimal(str(quantity)) * Decimal(int(unit_price))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        vat = int((Decimal(supply) * Decimal("0.10")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)) if vat_type == "TAXABLE" else 0
        return supply, vat, supply + vat

    def settlement_summary(self, event_id: int) -> dict:
        event = self.get_event(event_id)
        rows = self.db.query(
            """SELECT t.*,v.name vendor_name FROM event_tasks t
               LEFT JOIN contacts v ON v.id=t.vendor_id
               WHERE t.event_id=? AND t.is_removed=0 AND t.status<>'해당없음'
               ORDER BY
                 (SELECT MIN(g.sort_order) FROM event_tasks g
                  WHERE g.event_id=t.event_id AND g.major=t.major AND g.is_removed=0),
                 CASE WHEN TRIM(t.minor)='기타' THEN 1 ELSE 0 END,
                 (SELECT MIN(g.sort_order) FROM event_tasks g
                  WHERE g.event_id=t.event_id AND g.major=t.major AND g.minor=t.minor AND g.is_removed=0),
                 t.sort_order,t.id""",
            (event_id,),
        )
        items = []
        categories: dict[str, dict[str, int]] = {}
        warnings = 0
        for row in rows:
            item = dict(row)
            supply, vat, total = self.line_amounts(row["quantity"], row["unit_price"], row["vat_type"])
            item.update(supply=supply, vat=vat, total=total)
            item["warning"] = "수량 미입력" if row["quantity"] is None else ("단가 미입력" if row["unit_price"] is None else "")
            warnings += bool(item["warning"])
            subtotal = categories.setdefault(row["major"], {"supply": 0, "vat": 0, "total": 0})
            for key, value in (("supply", supply), ("vat", vat), ("total", total)):
                subtotal[key] += value
            items.append(item)
        supply = sum(value["supply"] for value in categories.values())
        vat = sum(value["vat"] for value in categories.values())
        total = supply + vat
        budget = int(event["budget"] or 0) if event else 0
        mode = event["budget_tax_mode"] if event else "UNSET"
        comparison = total if mode == "INCLUDED" else (supply if mode == "EXCLUDED" else None)
        return {"event": event, "items": items, "categories": categories, "supply": supply, "vat": vat,
                "total": total, "budget": budget, "budget_tax_mode": mode,
                "difference": budget - comparison if budget and comparison is not None else None,
                "comparison": comparison, "warnings": warnings}
