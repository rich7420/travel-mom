from __future__ import annotations

import json

from app.db import audit, connect
from app.models import new_id, now_iso


class CaseWorkflowRepo:
    def add_option(self, case_id: str, payload: dict) -> dict:
        option = {**payload, "id": new_id("option"), "case_id": case_id, "created_at": now_iso()}
        with connect() as db:
            db.execute(
                "INSERT INTO case_options(id,case_id,kind,payload_json,created_at) VALUES(?,?,?,?,?)",
                (option["id"], case_id, option["kind"], json.dumps(option, ensure_ascii=False), option["created_at"]),
            )
        return option

    def list_options(self, case_id: str) -> list[dict]:
        with connect() as db:
            rows = db.execute("SELECT payload_json FROM case_options WHERE case_id=? ORDER BY created_at DESC", (case_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def select(self, case_id: str, option: dict) -> dict:
        snapshot = {**option, "selected_at": now_iso()}
        with connect() as db:
            db.execute(
                """INSERT INTO case_option_selections(case_id,kind,option_id,snapshot_json,selected_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(case_id,kind) DO UPDATE SET
                   option_id=excluded.option_id,snapshot_json=excluded.snapshot_json,selected_at=excluded.selected_at""",
                (case_id, option["kind"], option["id"], json.dumps(snapshot, ensure_ascii=False), snapshot["selected_at"]),
            )
        return snapshot

    def selections(self, case_id: str) -> list[dict]:
        with connect() as db:
            rows = db.execute("SELECT snapshot_json FROM case_option_selections WHERE case_id=? ORDER BY kind", (case_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def clear_selection(self, case_id: str, kind: str) -> None:
        with connect() as db:
            db.execute("DELETE FROM case_option_selections WHERE case_id=? AND kind=?", (case_id, kind))
        audit(case_id, "operator", "case.option_selection_cleared", {"kind": kind}, now_iso())


case_workflow_repo = CaseWorkflowRepo()
