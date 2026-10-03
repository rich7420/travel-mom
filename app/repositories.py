from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.db import audit, connect
from app.models import (
    ActionType,
    ApprovalRequest,
    BrowserAttempt,
    BrowserTask,
    BrowserTaskCreate,
    CaseStatus,
    FlightSearchRequest,
    FlightSearchRun,
    FlightSearchRunStatus,
    HotelSearchRequest,
    HotelSearchRun,
    HotelSearchRunStatus,
    HotelSiteGrant,
    HotelSiteGrantCreate,
    HotelSiteTrustStatus,
    TripCase,
    TripCaseCreate,
    TripCasePatch,
    UserPreferences,
    UserPreferencesPatch,
    SkillFeedbackRecord,
    SkillFeedbackSummary,
    new_id,
    now_iso,
)

_UNSET = object()


def _case_from_row(r) -> TripCase:
    d = dict(r)
    d["children_ages"] = _loads(d.pop("children_ages_json", None), None)
    d["depart_date"] = date.fromisoformat(d["depart_date"]) if d["depart_date"] else None
    d["return_date"] = date.fromisoformat(d["return_date"]) if d["return_date"] else None
    return TripCase(**d)


def _loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


class CaseRepo:
    def list(self) -> list[TripCase]:
        with connect() as db:
            rows = db.execute("SELECT * FROM trip_cases ORDER BY updated_at DESC").fetchall()
        return [_case_from_row(r) for r in rows]

    def get(self, case_id: str) -> TripCase | None:
        with connect() as db:
            row = db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone()
        return _case_from_row(row) if row else None

    def create(self, data: TripCaseCreate) -> TripCase:
        ts = now_iso()
        case = TripCase(id=new_id("trip"), created_at=ts, updated_at=ts, status=CaseStatus.NEW, **data.model_dump())
        with connect() as db:
            db.execute(
                """INSERT INTO trip_cases
                (id,customer_name,destination,origin,depart_date,return_date,adults,children,budget_twd,notes,status,created_at,updated_at,infants,children_ages_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    case.id, case.customer_name, case.destination, case.origin,
                    case.depart_date.isoformat() if case.depart_date else None,
                    case.return_date.isoformat() if case.return_date else None,
                    case.adults, case.children, case.budget_twd, case.notes,
                    case.status.value, case.created_at, case.updated_at,
                    case.infants, json.dumps(case.children_ages) if case.children_ages is not None else None,
                ),
            )
            db.commit()
        audit(case.id, "system", "case.created", case.model_dump(mode="json"), ts)
        return case

    def patch(self, case_id: str, patch: dict[str, Any]) -> TripCase:
        patch = TripCasePatch.model_validate(patch).model_dump(exclude_unset=True, mode="json")
        with connect() as db:
            # Validate the merged record before any write and serialize competing updates.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM trip_cases WHERE id=?", (case_id,)).fetchone()
            if not row:
                raise KeyError(case_id)
            current = _case_from_row(row)
            if not patch:
                return current
            if patch.get("status") in {"booking", "confirmed"} and patch["status"] != current.status.value:
                raise ValueError("訂購進度由客人採用報價與已核對的訂購確認更新，請使用案件的訂購流程")
            merged = {**current.model_dump(mode="json"), **patch, "updated_at": now_iso()}
            TripCaseCreate.model_validate(merged)
            updated = TripCase.model_validate(merged)
            serialized = updated.model_dump(mode="json")
            assignments, values = [], []
            for key in [*patch, "updated_at"]:
                column = "children_ages_json" if key == "children_ages" else key
                value = serialized[key]
                if key == "children_ages" and value is not None:
                    value = json.dumps(value)
                assignments.append(f"{column}=?")
                values.append(value)
            values.append(case_id)
            db.execute(f"UPDATE trip_cases SET {', '.join(assignments)} WHERE id=?", values)
        audit(case_id, "system", "case.updated", patch, updated.updated_at)
        return updated


class SessionRepo:
    def get(self, session_id: str) -> dict[str, Any] | None:
        with connect() as db:
            row = db.execute("SELECT state_json FROM guided_sessions WHERE session_id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, session_id: str, case_id: str | None, state: dict[str, Any]) -> None:
        ts = now_iso()
        with connect() as db:
            db.execute(
                """INSERT INTO guided_sessions(session_id,case_id,state_json,updated_at)
                VALUES(?,?,?,?) ON CONFLICT(session_id) DO UPDATE SET
                case_id=excluded.case_id,state_json=excluded.state_json,updated_at=excluded.updated_at""",
                (session_id, case_id, json.dumps(state, ensure_ascii=False), ts),
            )
            db.commit()

    def clear(self, session_id: str) -> None:
        with connect() as db:
            db.execute("DELETE FROM guided_sessions WHERE session_id=?", (session_id,))
            db.commit()


class InboundEventRepo:
    """Idempotency store for LINE/Telegram webhook retries.

    The response is persisted before delivery. If a channel retries after a network
    failure, the same response can be re-sent without repeating case creation or
    another agent call.
    """

    def claim(self, channel: str, event_id: str, payload_hash: str) -> tuple[str, dict[str, Any] | None]:
        ts = now_iso()
        with connect() as db:
            cur = db.execute(
                """INSERT OR IGNORE INTO inbound_events
                (channel,event_id,payload_hash,status,response_json,received_at,updated_at)
                VALUES(?,?,?,?,?,?,?)""",
                (channel, event_id, payload_hash, "processing", None, ts, ts),
            )
            inserted = cur.rowcount == 1
            row = db.execute(
                "SELECT status,response_json,payload_hash,updated_at FROM inbound_events WHERE channel=? AND event_id=?",
                (channel, event_id),
            ).fetchone()
            db.commit()
        if inserted:
            return "new", None
        if not row:
            return "busy", None
        if row["payload_hash"] != payload_hash:
            return "collision", None
        response = _loads(row["response_json"], None)
        if response is not None and row["status"] in {"processed", "delivery_failed"}:
            return "replay", response
        if row["status"] == "delivered":
            return "delivered", response

        # A worker can crash after claiming an event but before storing a response.
        # Reclaim only the same payload after a bounded lease so webhook retries do
        # not remain "busy" forever.
        if row["status"] == "processing":
            updated_raw = row["updated_at"]
            try:
                updated = datetime.fromisoformat(str(updated_raw).replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                stale = now - updated > timedelta(seconds=max(1, settings.inbound_event_lease_seconds))
            except (TypeError, ValueError):
                stale = True
            if stale:
                with connect() as db:
                    cur = db.execute(
                        """UPDATE inbound_events SET received_at=?,updated_at=?
                        WHERE channel=? AND event_id=? AND status='processing' AND payload_hash=? AND updated_at=?""",
                        (ts, ts, channel, event_id, payload_hash, updated_raw),
                    )
                    db.commit()
                if cur.rowcount == 1:
                    return "new", None
        return "busy", None

    def store_response(self, channel: str, event_id: str, response: dict[str, Any]) -> None:
        ts = now_iso()
        with connect() as db:
            db.execute(
                "UPDATE inbound_events SET status='processed',response_json=?,updated_at=? WHERE channel=? AND event_id=?",
                (json.dumps(response, ensure_ascii=False), ts, channel, event_id),
            )
            db.commit()

    def mark_delivered(self, channel: str, event_id: str) -> None:
        ts = now_iso()
        with connect() as db:
            db.execute(
                "UPDATE inbound_events SET status='delivered',updated_at=? WHERE channel=? AND event_id=?",
                (ts, channel, event_id),
            )
            db.commit()

    def mark_delivery_failed(self, channel: str, event_id: str) -> None:
        ts = now_iso()
        with connect() as db:
            db.execute(
                "UPDATE inbound_events SET status='delivery_failed',updated_at=? WHERE channel=? AND event_id=?",
                (ts, channel, event_id),
            )
            db.commit()


class ApprovalRepo:
    def create(self, case_id: str | None, action_type: ActionType, summary: str, amount_twd: int | None = None) -> ApprovalRequest:
        ts = now_iso()
        obj = ApprovalRequest(id=new_id("approval"), case_id=case_id, action_type=action_type, summary=summary, amount_twd=amount_twd, created_at=ts)
        with connect() as db:
            db.execute(
                "INSERT INTO approvals(id,case_id,action_type,summary,amount_twd,status,created_at,decided_at) VALUES(?,?,?,?,?,?,?,?)",
                (obj.id, obj.case_id, obj.action_type.value, obj.summary, obj.amount_twd, obj.status, obj.created_at, obj.decided_at),
            )
            db.commit()
        audit(case_id, "system", "approval.created", obj.model_dump(mode="json"), ts)
        return obj

    def list(self, status: str | None = "pending") -> list[ApprovalRequest]:
        with connect() as db:
            if status:
                rows = db.execute("SELECT * FROM approvals WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM approvals ORDER BY created_at DESC").fetchall()
        return [ApprovalRequest(**dict(r)) for r in rows]

    def decide(self, approval_id: str, status: str) -> ApprovalRequest:
        if status not in {"approved", "rejected"}:
            raise ValueError("status must be approved or rejected")
        ts = now_iso()
        with connect() as db:
            db.execute("UPDATE approvals SET status=?,decided_at=? WHERE id=?", (status, ts, approval_id))
            row = db.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
            db.commit()
        if not row:
            raise KeyError(approval_id)
        obj = ApprovalRequest(**dict(row))
        audit(obj.case_id, "human", f"approval.{status}", obj.model_dump(mode="json"), ts)
        return obj


class FlightSearchRunRepo:
    @staticmethod
    def _from_row(row) -> FlightSearchRun:
        data = dict(row)
        return FlightSearchRun(
            id=data["id"],
            case_id=data["case_id"],
            request=FlightSearchRequest.model_validate(_loads(data["request_json"], {})),
            task_ids=_loads(data["task_ids_json"], []),
            manual_handoffs=_loads(data["manual_handoffs_json"], []),
            unsupported_airlines=_loads(data["unsupported_airlines_json"], []),
            status=data["status"],
            selected_task_id=data["selected_task_id"],
            selected_option_id=data["selected_option_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def create(self, request: FlightSearchRequest) -> FlightSearchRun:
        ts = now_iso()
        obj = FlightSearchRun(
            id=new_id("fsearch"),
            case_id=request.case_id,
            request=request,
            status=FlightSearchRunStatus.PLANNED,
            created_at=ts,
            updated_at=ts,
        )
        with connect() as db:
            db.execute(
                """INSERT INTO flight_search_runs
                (id,case_id,request_json,task_ids_json,manual_handoffs_json,unsupported_airlines_json,status,selected_task_id,selected_option_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obj.id, obj.case_id, json.dumps(obj.request.model_dump(mode="json"), ensure_ascii=False),
                    "[]", "[]", "[]", obj.status.value, None, None, ts, ts,
                ),
            )
            db.commit()
        audit(obj.case_id, "system", "flight_search_run.created", obj.model_dump(mode="json"), ts)
        return obj

    def get(self, run_id: str) -> FlightSearchRun | None:
        with connect() as db:
            row = db.execute("SELECT * FROM flight_search_runs WHERE id=?", (run_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, case_id: str | None = None, limit: int = 100) -> list[FlightSearchRun]:
        with connect() as db:
            if case_id:
                rows = db.execute(
                    "SELECT * FROM flight_search_runs WHERE case_id=? ORDER BY created_at DESC LIMIT ?",
                    (case_id, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM flight_search_runs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._from_row(r) for r in rows]

    def finalize_plan(
        self,
        run_id: str,
        task_ids: list[str],
        manual_handoffs: list[dict[str, Any]],
        unsupported_airlines: list[str],
    ) -> FlightSearchRun:
        ts = now_iso()
        status = FlightSearchRunStatus.PLANNED.value if task_ids else FlightSearchRunStatus.NEEDS_REVIEW.value
        with connect() as db:
            db.execute(
                """UPDATE flight_search_runs SET task_ids_json=?,manual_handoffs_json=?,unsupported_airlines_json=?,status=?,updated_at=?
                WHERE id=?""",
                (
                    json.dumps(task_ids, ensure_ascii=False),
                    json.dumps(manual_handoffs, ensure_ascii=False),
                    json.dumps(unsupported_airlines, ensure_ascii=False),
                    status, ts, run_id,
                ),
            )
            db.commit()
        obj = self.get(run_id)
        if not obj:
            raise KeyError(run_id)
        audit(obj.case_id, "system", "flight_search_run.planned", obj.model_dump(mode="json"), ts)
        return obj

    def set_status(self, run_id: str, status: FlightSearchRunStatus | str) -> FlightSearchRun:
        ts = now_iso()
        value = status.value if isinstance(status, FlightSearchRunStatus) else status
        with connect() as db:
            db.execute("UPDATE flight_search_runs SET status=?,updated_at=? WHERE id=?", (value, ts, run_id))
            db.commit()
        obj = self.get(run_id)
        if not obj:
            raise KeyError(run_id)
        return obj

    def select_option(self, run_id: str, task_id: str, option_id: str) -> FlightSearchRun:
        current = self.get(run_id)
        if not current:
            raise KeyError(run_id)
        if task_id not in current.task_ids:
            raise ValueError("task 不屬於此 search run")
        ts = now_iso()
        with connect() as db:
            db.execute(
                "UPDATE flight_search_runs SET selected_task_id=?,selected_option_id=?,updated_at=? WHERE id=?",
                (task_id, option_id, ts, run_id),
            )
            db.commit()
        obj = self.get(run_id)
        if not obj:
            raise KeyError(run_id)
        audit(obj.case_id, "human", "flight_search_run.option_selected", {"run_id": run_id, "task_id": task_id, "option_id": option_id}, ts)
        return obj


class HotelSiteGrantRepo:
    @staticmethod
    def _from_row(row) -> HotelSiteGrant:
        return HotelSiteGrant(**dict(row))

    def create(self, data: HotelSiteGrantCreate, domain: str, approved: bool = True) -> HotelSiteGrant:
        ts = now_iso()
        status = HotelSiteTrustStatus.APPROVED if approved else HotelSiteTrustStatus.PENDING
        obj = HotelSiteGrant(
            id=new_id("hsite"),
            hotel_name=data.hotel_name,
            domain=domain,
            official_url=data.official_url,
            trust_source=data.trust_source,
            evidence_url=data.evidence_url,
            notes=data.notes,
            status=status,
            approved_at=ts if approved else None,
            created_at=ts,
            updated_at=ts,
        )
        with connect() as db:
            existing = db.execute(
                "SELECT id FROM hotel_site_grants WHERE domain=? AND status='approved'",
                (domain,),
            ).fetchone()
            if existing and approved:
                row = db.execute("SELECT * FROM hotel_site_grants WHERE id=?", (existing[0],)).fetchone()
                return self._from_row(row)
            db.execute(
                """INSERT INTO hotel_site_grants
                (id,hotel_name,domain,official_url,trust_source,evidence_url,notes,status,approved_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (obj.id,obj.hotel_name,obj.domain,obj.official_url,obj.trust_source,obj.evidence_url,obj.notes,obj.status.value,obj.approved_at,obj.created_at,obj.updated_at),
            )
            db.commit()
        audit(None, "human" if data.trust_source == "human" else "system", "hotel_site_grant.created", obj.model_dump(mode="json"), ts)
        return obj

    def get_by_domain(self, domain: str, approved_only: bool = True) -> HotelSiteGrant | None:
        with connect() as db:
            if approved_only:
                row = db.execute(
                    "SELECT * FROM hotel_site_grants WHERE domain=? AND status='approved' ORDER BY updated_at DESC LIMIT 1",
                    (domain,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT * FROM hotel_site_grants WHERE domain=? ORDER BY updated_at DESC LIMIT 1",
                    (domain,),
                ).fetchone()
        return self._from_row(row) if row else None

    def list(self, status: str | None = None) -> list[HotelSiteGrant]:
        with connect() as db:
            if status:
                rows = db.execute("SELECT * FROM hotel_site_grants WHERE status=? ORDER BY updated_at DESC", (status,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM hotel_site_grants ORDER BY updated_at DESC").fetchall()
        return [self._from_row(r) for r in rows]

    def revoke(self, grant_id: str) -> HotelSiteGrant:
        ts = now_iso()
        with connect() as db:
            db.execute("UPDATE hotel_site_grants SET status='revoked',updated_at=? WHERE id=?", (ts, grant_id))
            row = db.execute("SELECT * FROM hotel_site_grants WHERE id=?", (grant_id,)).fetchone()
            db.commit()
        if not row:
            raise KeyError(grant_id)
        obj = self._from_row(row)
        audit(None, "human", "hotel_site_grant.revoked", obj.model_dump(mode="json"), ts)
        return obj


class HotelSearchRunRepo:
    @staticmethod
    def _from_row(row) -> HotelSearchRun:
        data = dict(row)
        return HotelSearchRun(
            id=data["id"],
            case_id=data["case_id"],
            request=HotelSearchRequest.model_validate(_loads(data["request_json"], {})),
            task_ids=_loads(data["task_ids_json"], []),
            status=data["status"],
            selected_task_id=data["selected_task_id"],
            selected_option_id=data["selected_option_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )

    def create(self, request: HotelSearchRequest) -> HotelSearchRun:
        ts = now_iso()
        obj = HotelSearchRun(
            id=new_id("hsearch"),
            case_id=request.case_id,
            request=request,
            status=HotelSearchRunStatus.PLANNED,
            created_at=ts,
            updated_at=ts,
        )
        with connect() as db:
            db.execute(
                """INSERT INTO hotel_search_runs
                (id,case_id,request_json,task_ids_json,status,selected_task_id,selected_option_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (obj.id,obj.case_id,json.dumps(obj.request.model_dump(mode="json"),ensure_ascii=False),"[]",obj.status.value,None,None,ts,ts),
            )
            db.commit()
        audit(obj.case_id,"system","hotel_search_run.created",obj.model_dump(mode="json"),ts)
        return obj

    def get(self, run_id: str) -> HotelSearchRun | None:
        with connect() as db:
            row=db.execute("SELECT * FROM hotel_search_runs WHERE id=?",(run_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, case_id: str | None = None, limit: int = 100) -> list[HotelSearchRun]:
        with connect() as db:
            if case_id:
                rows=db.execute("SELECT * FROM hotel_search_runs WHERE case_id=? ORDER BY created_at DESC LIMIT ?",(case_id,limit)).fetchall()
            else:
                rows=db.execute("SELECT * FROM hotel_search_runs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._from_row(r) for r in rows]

    def finalize_plan(self, run_id: str, task_ids: list[str]) -> HotelSearchRun:
        ts=now_iso()
        status=HotelSearchRunStatus.PLANNED.value if task_ids else HotelSearchRunStatus.NEEDS_REVIEW.value
        with connect() as db:
            db.execute("UPDATE hotel_search_runs SET task_ids_json=?,status=?,updated_at=? WHERE id=?",(json.dumps(task_ids),status,ts,run_id))
            db.commit()
        obj=self.get(run_id)
        if not obj: raise KeyError(run_id)
        audit(obj.case_id,"system","hotel_search_run.planned",obj.model_dump(mode="json"),ts)
        return obj

    def set_status(self, run_id: str, status: HotelSearchRunStatus | str) -> HotelSearchRun:
        ts=now_iso(); value=status.value if isinstance(status,HotelSearchRunStatus) else status
        with connect() as db:
            db.execute("UPDATE hotel_search_runs SET status=?,updated_at=? WHERE id=?",(value,ts,run_id)); db.commit()
        obj=self.get(run_id)
        if not obj: raise KeyError(run_id)
        return obj

    def select_option(self, run_id: str, task_id: str, option_id: str) -> HotelSearchRun:
        current=self.get(run_id)
        if not current: raise KeyError(run_id)
        if task_id not in current.task_ids: raise ValueError("task 不屬於此 hotel search run")
        ts=now_iso()
        with connect() as db:
            db.execute("UPDATE hotel_search_runs SET selected_task_id=?,selected_option_id=?,updated_at=? WHERE id=?",(task_id,option_id,ts,run_id)); db.commit()
        obj=self.get(run_id)
        if not obj: raise KeyError(run_id)
        audit(obj.case_id,"human","hotel_search_run.option_selected",{"run_id":run_id,"task_id":task_id,"option_id":option_id},ts)
        return obj


class BrowserTaskRepo:
    @staticmethod
    def _from_row(row) -> BrowserTask:
        data = dict(row)
        data["result_json"] = _loads(data.get("result_json"), None)
        return BrowserTask(**data)

    def create(self, data: BrowserTaskCreate) -> BrowserTask:
        ts = now_iso()
        obj = BrowserTask(
            id=new_id("browser"), status="queued", created_at=ts, updated_at=ts,
            result_text=None, result_json=None, review_state="not_reviewed", **data.model_dump()
        )
        with connect() as db:
            db.execute(
                """INSERT INTO browser_tasks
                (id,case_id,search_run_id,parent_task_id,parent_option_id,kind,source_url,instructions,provider_code,expected_schema,status,result_text,result_json,review_state,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obj.id, obj.case_id, obj.search_run_id, obj.parent_task_id, obj.parent_option_id,
                    obj.kind.value, obj.source_url, obj.instructions, obj.provider_code, obj.expected_schema,
                    obj.status, obj.result_text, None, obj.review_state, obj.created_at, obj.updated_at,
                ),
            )
            db.commit()
        audit(obj.case_id, "system", "browser_task.created", obj.model_dump(mode="json"), ts)
        return obj

    def get(self, task_id: str) -> BrowserTask | None:
        with connect() as db:
            row = db.execute("SELECT * FROM browser_tasks WHERE id=?", (task_id,)).fetchone()
        return self._from_row(row) if row else None

    def list(self, limit: int = 100, search_run_id: str | None = None) -> list[BrowserTask]:
        with connect() as db:
            if search_run_id:
                rows = db.execute(
                    "SELECT * FROM browser_tasks WHERE search_run_id=? ORDER BY created_at ASC LIMIT ?",
                    (search_run_id, limit),
                ).fetchall()
            else:
                rows = db.execute("SELECT * FROM browser_tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._from_row(row) for row in rows]

    def update(
        self, task_id: str, status: str, result_text: str | None = None,
        result_json: dict[str, Any] | None = None, review_state: str | None = None,
        result_attempt_id: str | None | object = _UNSET,
    ) -> BrowserTask:
        ts = now_iso()
        current = self.get(task_id)
        if not current:
            raise KeyError(task_id)
        if review_state is None:
            review_state = current.review_state
        json_blob = json.dumps(result_json, ensure_ascii=False) if result_json is not None else (
            json.dumps(current.result_json, ensure_ascii=False) if current.result_json is not None else None
        )
        if result_text is None:
            result_text = current.result_text
        attempt_id = current.result_attempt_id if result_attempt_id is _UNSET else result_attempt_id
        with connect() as db:
            db.execute(
                "UPDATE browser_tasks SET status=?,result_text=?,result_json=?,review_state=?,result_attempt_id=?,updated_at=? WHERE id=?",
                (status, result_text, json_blob, review_state, attempt_id, ts, task_id),
            )
            row = db.execute("SELECT * FROM browser_tasks WHERE id=?", (task_id,)).fetchone()
            db.commit()
        if not row:
            raise KeyError(task_id)
        obj = self._from_row(row)
        audit(obj.case_id, "system", "browser_task.updated", {"id": task_id, "status": status, "review_state": review_state}, ts)
        return obj


class BrowserAttemptRepo:
    @staticmethod
    def _from_row(row) -> BrowserAttempt:
        data = dict(row)
        data["validation_errors"] = _loads(data.pop("validation_errors_json", "[]"), [])
        return BrowserAttempt(**data)

    def start(self, task_id: str, source: str, browser_profile: str) -> BrowserAttempt:
        ts = now_iso()
        with connect() as db:
            # Serialize MAX+1 and INSERT across processes. Without this immediate
            # transaction, concurrent workers can choose the same attempt number.
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT COALESCE(MAX(attempt_no),0)+1 FROM browser_attempts WHERE task_id=?", (task_id,)).fetchone()
            attempt_no = int(row[0])
            obj = BrowserAttempt(
                id=new_id("attempt"), task_id=task_id, attempt_no=attempt_no,
                source=source, browser_profile=browser_profile, started_at=ts,
                outcome="running", created_at=ts,
            )
            db.execute(
                """INSERT INTO browser_attempts
                (id,task_id,attempt_no,source,browser_profile,started_at,finished_at,duration_ms,outcome,result_status,validation_errors_json,blocker,result_hash,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obj.id, obj.task_id, obj.attempt_no, obj.source, obj.browser_profile,
                    obj.started_at, None, None, obj.outcome, None, "[]", None, None, obj.created_at,
                ),
            )
            db.commit()
        return obj

    def finish(
        self,
        attempt_id: str,
        outcome: str,
        validation_errors: list[str] | None = None,
        blocker: str | None = None,
        result_text: str | None = None,
        result_status: str | None = None,
    ) -> BrowserAttempt:
        finished = now_iso()
        with connect() as db:
            row = db.execute("SELECT * FROM browser_attempts WHERE id=?", (attempt_id,)).fetchone()
            if not row:
                raise KeyError(attempt_id)
            start = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            duration_ms = max(0, int((end - start).total_seconds() * 1000))
            result_hash = hashlib.sha256(result_text.encode("utf-8")).hexdigest() if result_text else None
            db.execute(
                """UPDATE browser_attempts SET finished_at=?,duration_ms=?,outcome=?,result_status=?,validation_errors_json=?,blocker=?,result_hash=?
                WHERE id=?""",
                (
                    finished, duration_ms, outcome, result_status, json.dumps(validation_errors or [], ensure_ascii=False),
                    blocker, result_hash, attempt_id,
                ),
            )
            row = db.execute("SELECT * FROM browser_attempts WHERE id=?", (attempt_id,)).fetchone()
            db.commit()
        return self._from_row(row)

    def list_for_task(self, task_id: str) -> list[BrowserAttempt]:
        with connect() as db:
            rows = db.execute("SELECT * FROM browser_attempts WHERE task_id=? ORDER BY attempt_no", (task_id,)).fetchall()
        return [self._from_row(r) for r in rows]

    def list(self, limit: int = 1000) -> list[BrowserAttempt]:
        with connect() as db:
            rows = db.execute("SELECT * FROM browser_attempts ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._from_row(r) for r in rows]


class UserPreferencesRepo:
    PROFILE_ID = "mom"

    @staticmethod
    def _from_row(row) -> UserPreferences:
        if not row:
            return UserPreferences()
        data = dict(row)
        return UserPreferences(
            profile_id=data["profile_id"], default_origin=data["default_origin"],
            preferred_airlines=_loads(data["preferred_airlines_json"], []),
            font_scale=data["font_scale"], simple_mode=bool(data["simple_mode"]),
            onboarding_complete=bool(data["onboarding_complete"]), updated_at=data["updated_at"],
        )

    def get(self) -> UserPreferences:
        with connect() as db:
            row = db.execute("SELECT * FROM user_preferences WHERE profile_id=?", (self.PROFILE_ID,)).fetchone()
        if row:
            return self._from_row(row)
        obj = UserPreferences(profile_id=self.PROFILE_ID)
        return self._save(obj)

    def _save(self, obj: UserPreferences) -> UserPreferences:
        with connect() as db:
            db.execute(
                """INSERT INTO user_preferences
                (profile_id,default_origin,preferred_airlines_json,font_scale,simple_mode,onboarding_complete,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(profile_id) DO UPDATE SET
                default_origin=excluded.default_origin,preferred_airlines_json=excluded.preferred_airlines_json,
                font_scale=excluded.font_scale,simple_mode=excluded.simple_mode,
                onboarding_complete=excluded.onboarding_complete,updated_at=excluded.updated_at""",
                (obj.profile_id,obj.default_origin,json.dumps(obj.preferred_airlines,ensure_ascii=False),
                 obj.font_scale.value if hasattr(obj.font_scale,"value") else str(obj.font_scale),
                 1 if obj.simple_mode else 0,1 if obj.onboarding_complete else 0,obj.updated_at),
            )
        return obj

    def patch(self, patch: UserPreferencesPatch) -> UserPreferences:
        current = self.get()
        values = current.model_dump(mode="json")
        values.update(patch.model_dump(exclude_none=True, mode="json"))
        values["updated_at"] = now_iso()
        obj = UserPreferences.model_validate(values)
        self._save(obj)
        audit(None,"human","preferences.updated",{k:v for k,v in values.items() if k!="updated_at"},obj.updated_at)
        return obj


class SkillFeedbackRepo:
    @staticmethod
    def _from_row(row) -> SkillFeedbackRecord:
        data=dict(row); data["possible_pii"]=bool(data["possible_pii"]); return SkillFeedbackRecord(**data)

    def create(self, record: SkillFeedbackRecord) -> SkillFeedbackRecord:
        with connect() as db:
            db.execute(
                """INSERT INTO skill_feedback
                (id,skill_key,feedback_type,case_id,source,draft_redacted,final_redacted,note_redacted,skill_hash,edit_ratio,possible_pii,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (record.id,record.skill_key,record.feedback_type.value,record.case_id,record.source,record.draft_redacted,
                 record.final_redacted,record.note_redacted,record.skill_hash,record.edit_ratio,1 if record.possible_pii else 0,record.created_at),
            )
        audit(record.case_id,"human","skill.feedback",{"id":record.id,"skill_key":record.skill_key,"feedback_type":record.feedback_type.value,"skill_hash":record.skill_hash,"edit_ratio":record.edit_ratio,"possible_pii":record.possible_pii},record.created_at)
        return record

    def list(self, skill_key: str | None=None, limit: int=200) -> list[SkillFeedbackRecord]:
        with connect() as db:
            if skill_key:
                rows=db.execute("SELECT * FROM skill_feedback WHERE skill_key=? ORDER BY created_at DESC LIMIT ?",(skill_key,limit)).fetchall()
            else:
                rows=db.execute("SELECT * FROM skill_feedback ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
        return [self._from_row(row) for row in rows]

    def summary(self, skill_key: str | None=None) -> SkillFeedbackSummary:
        params=[]; where=""
        if skill_key: where=" WHERE skill_key=?"; params.append(skill_key)
        with connect() as db:
            rows=db.execute(f"SELECT feedback_type,edit_ratio FROM skill_feedback{where}",params).fetchall()
        counts={"accepted":0,"edited":0,"prefer_future":0,"rejected":0}; ratios=[]
        for row in rows:
            if row["feedback_type"] in counts: counts[row["feedback_type"]]+=1
            if row["edit_ratio"] is not None: ratios.append(float(row["edit_ratio"]))
        total=len(rows); ready=total>=12 and (counts["edited"]+counts["prefer_future"]+counts["rejected"])>=4
        reason=("已有足夠多的媽媽回饋，可以開始建立候選 Skill proposal；仍需離線驗證與人工核准。" if ready else "持續收集實際採用、修改與拒絕紀錄；v0.8.1 不會自動修改正式 Skill。")
        return SkillFeedbackSummary(skill_key=skill_key,total=total,average_edit_ratio=(sum(ratios)/len(ratios) if ratios else None),ready_for_proposal=ready,proposal_reason=reason,**counts)


case_repo = CaseRepo()
session_repo = SessionRepo()
inbound_event_repo = InboundEventRepo()
approval_repo = ApprovalRepo()
flight_search_run_repo = FlightSearchRunRepo()
hotel_site_grant_repo = HotelSiteGrantRepo()
hotel_search_run_repo = HotelSearchRunRepo()
browser_task_repo = BrowserTaskRepo()
browser_attempt_repo = BrowserAttemptRepo()
preferences_repo = UserPreferencesRepo()
skill_feedback_repo = SkillFeedbackRepo()
