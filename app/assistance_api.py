"""Operator-scoped private assistance endpoints; summaries and receipts contain metadata."""

import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from app.agency_http import agency_call, service_actor
from app.assistance_models import (
    CustomerProfile,
    CustomerConsent,
    CustomerLink,
    CommunicationCreate,
    CommunicationPatch,
    CommunicationSent,
    TravellerService,
    RecordEvidence,
    ReminderRule,
    ReminderConfirmation,
)
from app.customer_repository import create_id, get_customer
from app.db import connect
from app.operations_models import Evidence
from app.services import crm, reminders, traveller_services, travel_files
from app.services.case_operations import require

router = APIRouter(prefix="/api")


@router.get("/mom/customers")
def customers(q: str = Query(default="", max_length=160)):
    return {"customers": crm.list_customers(q)}


@router.post("/mom/customers")
def create_customer(data: CustomerProfile, request: Request):
    if data.expected_revision is not None:
        raise HTTPException(422, "新增客戶不需修訂標示")
    return agency_call(lambda: crm.profile(data, service_actor(request)))


@router.get("/mom/customers/{customer_id}")
def customer(customer_id: str):
    def read():
        with connect() as db:
            return crm.customer_meta(get_customer(db, customer_id))

    return agency_call(read)


@router.patch("/mom/customers/{customer_id}")
def patch_customer(customer_id: str, data: CustomerProfile, request: Request):
    if data.expected_revision is None:
        raise HTTPException(422, "修改客戶需核對目前修訂")
    return agency_call(lambda: crm.profile(data, service_actor(request), customer_id))


@router.get("/mom/customers/{customer_id}/reveal")
def reveal_customer(customer_id: str, request: Request):
    return agency_call(lambda: crm.reveal_customer(customer_id, service_actor(request)))


@router.get("/mom/customers/{customer_id}/history")
def customer_history(customer_id: str):
    return agency_call(lambda: crm.customer_history(customer_id))


@router.post("/mom/customers/{customer_id}/consents")
def customer_consent(customer_id: str, data: CustomerConsent, request: Request):
    return agency_call(lambda: crm.consent(customer_id, data, service_actor(request)))


def receipt(scope, request_id, actor, customer_scope=False):
    identifier = str(UUID(request_id))
    with connect() as db:
        if customer_scope:
            scope = create_id(identifier) if scope == "new" else scope
            table, key, prefixes = "customer_commands", "customer_id", ("customer.",)
        else:
            if not db.execute(
                "SELECT 1 FROM trip_cases WHERE id=?", (scope,)
            ).fetchone():
                raise KeyError(scope)
            table, key, prefixes = (
                "agency_commands",
                "case_id",
                ("crm.", "traveller-service.", "reminder."),
            )
        found = db.execute(
            f"SELECT action,actor,response_json FROM {table} WHERE {key}=? AND request_id=?",
            (scope, identifier),
        ).fetchone()
        if not found:
            return {"committed": False}
        require(
            found["actor"] == actor and found["action"].startswith(prefixes),
            "重試紀錄不屬於此帳號或操作",
        )
        result = json.loads(found["response_json"])
        return {"committed": True, "record_id": result["id"], "action": found["action"]}


@router.get("/mom/customer-receipts/{customer_id}/{request_id}")
def customer_receipt(customer_id: str, request_id: str, request: Request):
    return agency_call(
        lambda: receipt(customer_id, request_id, service_actor(request), True)
    )


@router.get("/mom/cases/{case_id}/assistance-receipts/{request_id}")
def assistance_receipt(case_id: str, request_id: str, request: Request):
    return agency_call(lambda: receipt(case_id, request_id, service_actor(request)))


@router.get("/mom/cases/{case_id}/crm")
def case_crm(case_id: str):
    return agency_call(lambda: crm.summary(case_id))


@router.post("/mom/cases/{case_id}/customer-link")
def link_customer(case_id: str, data: CustomerLink, request: Request):
    return agency_call(lambda: crm.link(case_id, data, service_actor(request)))


@router.post("/mom/cases/{case_id}/communications")
def create_message(case_id: str, data: CommunicationCreate, request: Request):
    return agency_call(
        lambda: crm.create_message(case_id, data, service_actor(request))
    )


@router.patch("/mom/cases/{case_id}/communications/{message_id}")
def patch_message(
    case_id: str, message_id: str, data: CommunicationPatch, request: Request
):
    return agency_call(
        lambda: crm.patch_message(case_id, message_id, data, service_actor(request))
    )


@router.get("/mom/cases/{case_id}/communications/{message_id}/reveal")
def reveal_message(case_id: str, message_id: str, request: Request):
    return agency_call(
        lambda: crm.reveal_message(case_id, message_id, service_actor(request))
    )


@router.post("/mom/cases/{case_id}/communications/{message_id}/attest")
def attest_message(
    case_id: str, message_id: str, data: CommunicationSent, request: Request
):
    return agency_call(
        lambda: crm.attest_sent(case_id, message_id, data, service_actor(request))
    )


@router.get("/mom/cases/{case_id}/traveller-services")
def services(case_id: str):
    def read():
        private = travel_files.list_private(case_id)
        return {k: private[k] for k in ("traveller_services", "travellers", "bookings")}

    return agency_call(read)


@router.post("/mom/cases/{case_id}/traveller-services")
def create_service(case_id: str, data: TravellerService, request: Request):
    return agency_call(
        lambda: traveller_services.write(case_id, data, service_actor(request))
    )


@router.patch("/mom/cases/{case_id}/traveller-services/{service_id}")
def patch_service(
    case_id: str, service_id: str, data: TravellerService, request: Request
):
    return agency_call(
        lambda: traveller_services.write(
            case_id, data, service_actor(request), service_id
        )
    )


@router.get("/mom/cases/{case_id}/traveller-services/{service_id}/reveal")
def reveal_service(case_id: str, service_id: str, request: Request):
    return agency_call(
        lambda: traveller_services.reveal(case_id, service_id, service_actor(request))
    )


@router.post("/mom/cases/{case_id}/traveller-services/{service_id}/archive")
def archive_service(
    case_id: str, service_id: str, data: RecordEvidence, request: Request
):
    return agency_call(
        lambda: traveller_services.archive(
            case_id, service_id, data, service_actor(request)
        )
    )


@router.get("/mom/reminder-status")
def reminder_status():
    return reminders.status()


@router.get("/mom/cases/{case_id}/reminders")
def case_reminders(case_id: str):
    return agency_call(lambda: reminders.summary(case_id))


@router.post("/mom/cases/{case_id}/reminders")
def create_reminder(case_id: str, data: ReminderRule, request: Request):
    return agency_call(
        lambda: reminders.write_rule(case_id, data, service_actor(request))
    )


@router.patch("/mom/cases/{case_id}/reminders/{rule_id}")
def patch_reminder(case_id: str, rule_id: str, data: ReminderRule, request: Request):
    return agency_call(
        lambda: reminders.write_rule(case_id, data, service_actor(request), rule_id)
    )


@router.get("/mom/cases/{case_id}/reminders/{rule_id}/reveal")
def reveal_reminder(case_id: str, rule_id: str, request: Request):
    return agency_call(
        lambda: reminders.reveal_rule(case_id, rule_id, service_actor(request))
    )


@router.post("/mom/cases/{case_id}/reminder-jobs/{job_id}/confirm")
def confirm_reminder(
    case_id: str, job_id: str, data: ReminderConfirmation, request: Request
):
    return agency_call(
        lambda: reminders.confirm_job(case_id, job_id, data, service_actor(request))
    )


@router.post("/system/reminders/acknowledge-restore")
def acknowledge_restore(data: Evidence, request: Request):
    return agency_call(
        lambda: reminders.acknowledge_restore(data, service_actor(request))
    )


@router.get("/mom/cases/{case_id}/reminder-jobs/{job_id}/reveal")
def reveal_reminder_job(case_id: str, job_id: str, request: Request):
    return agency_call(
        lambda: reminders.reveal_job(case_id, job_id, service_actor(request))
    )
