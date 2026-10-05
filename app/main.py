from __future__ import annotations

from uuid import UUID
from contextlib import asynccontextmanager
import logging
import re
from pathlib import Path
from urllib.parse import unquote

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from fastapi.responses import Response, FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.airlines import all_airlines
from app.hotels import all_networks
from app.channels.line import handle_line
from app.channels.telegram import handle_telegram
from app.config import settings
from app.db import init_db
from app.models import (
    ActionType,
    AgentAskRequest,
    BookingPreflightRequest,
    BrowserTaskBatchRequest,
    BrowserTaskCreate,
    BrowserTaskIngestRequest,
    CustomerReplyRequest,
    FlightOptionSelectionRequest,
    FlightRevalidationCreateRequest,
    FlightSearchRequest,
    Health,
    HotelBookingPreflightRequest,
    HotelRevalidationCreateRequest,
    HotelSearchRequest,
    HotelSiteGrantCreate,
    TripCaseCreate,
    TripCasePatch,
    UserPreferencesPatch,
    MomIntentRequest,
    SkillFeedbackCreate,
)
from app.providers.mock import demo_provider
from app.repositories import (
    approval_repo,
    browser_attempt_repo,
    browser_task_repo,
    case_repo,
    flight_search_run_repo,
    hotel_search_run_repo,
    hotel_site_grant_repo,
    preferences_repo,
    skill_feedback_repo,
)
from app.services.booking_preflight import build_booking_preflight
from app.services.browser_lab import build_browser_lab_summary
from app.services.browser_tasks import browser_task_service
from app.services.flight_revalidation import summarize_revalidation
from app.services.hotel_booking_preflight import build_hotel_booking_preflight
from app.services.hotel_compare import compare_official_hotel_tasks
from app.services.hotel_revalidation import summarize_hotel_revalidation
from app.services.hotel_trust import approve_independent_hotel_site, builtin_hotel_domains
from app.services.guided import guided_intake
from app.services.official_compare import compare_official_flight_tasks
from app.services.openclaw import openclaw_client
from app.services.policy import policy
from app.services.radar import build_radar
from app.services.mom_ux import build_mom_home, infer_mom_intent, next_best_action, search_run_progress
from app.services.skill_feedback import capture_skill_feedback
from app.services.readiness import build_system_readiness
from app.services.case_workflow import add_manual_option, case_workflow, select_case_option, require_case, validate_search_case
from app.workflow_models import ManualOptionCreate, CaseOptionSelection
from app.workflow_repository import case_workflow_repo
from app.services.replies import draft_customer_reply
from app.services.scoring import rank_flights, rank_hotels
from app.security import operator_authorized, security_headers_for_path, validate_runtime_settings, is_production, access_exempt, access_requires_admin, verify_access_origin
from app.cloudflare_access import AccessVerifier
from app.request_limits import RequestBodyLimitMiddleware


from app.operations_models import QuoteCreate, QuoteDecision, WorkItemCreate, WorkItemPatch, BookingCreate, BookingRebind, VoidRecord, LedgerCreate, DocumentCreate, DocumentPatch, PackCreate, PackDelivery, CaseClose, CaseReopen, SearchAbandon, TravellerData, RosterVerify, AttachmentUpload, AttachmentArchive, WorkAcknowledgement, WorkHandover
from app.service_order_models import (ServiceOrderCreate, ServiceOrderPatch, ServiceAssessment,
    ServiceDecision, ServiceProgress, ServiceSettlement, ServiceResolve, ServiceReopen)
from app.services import service_orders
from app.operations_repository import OperationConflict, OperationBusy
from app.services import case_operations as agency
from app.services.operation_documents import customer_document

logger = logging.getLogger("mom_travel_desk")


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_runtime_settings()
    init_db()
    app.state.access_verifier = AccessVerifier(settings) if settings.auth_mode == "cloudflare" else None
    yield


app = FastAPI(title="Mom Travel Desk POC", version="0.8.1", lifespan=lifespan,
              docs_url=None if is_production() else "/docs",
              redoc_url=None if is_production() else "/redoc",
              openapi_url=None if is_production() else "/openapi.json")


app.add_middleware(RequestBodyLimitMiddleware, limit=lambda: settings.max_request_body_bytes, upload_limit=10 * 1024 * 1024)


@app.middleware("http")
async def protect_operator_api(request: Request, call_next):
    if settings.auth_mode == "cloudflare" and not access_exempt(request):
        try:
            request.state.identity = await app.state.access_verifier.verify(request.headers.get("cf-access-jwt-assertion", ""))
            if access_requires_admin(request) and request.state.identity.role != "admin":
                raise HTTPException(403, "administrator access required")
            verify_access_origin(request)
        except HTTPException as exc:
            response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "auth_mode": "cloudflare"})
        else:
            response = await call_next(request)
    elif settings.auth_mode == "cloudflare" or request.url.path == "/api/auth/session":
        response = await call_next(request)
    elif not operator_authorized(request):
        response = JSONResponse(
            status_code=401,
            content={"detail": "operator authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    else:
        response = await call_next(request)

    for key, value in security_headers_for_path(request.url.path).items():
        response.headers.setdefault(key, value)
    if request.url.path.startswith("/api/") or settings.auth_mode == "cloudflare":
        response.headers.setdefault("Cache-Control", "no-store")
    return response
MOM_STATIC = Path(__file__).parent / "mom_static"
ADMIN_STATIC = Path(__file__).parent / "admin_static"
app.mount("/static", StaticFiles(directory=MOM_STATIC), name="mom-static")
app.mount("/admin-static", StaticFiles(directory=ADMIN_STATIC), name="admin-static")


@app.get("/")
def index():
    return FileResponse(MOM_STATIC / "index.html")


@app.get("/admin")
def admin_index():
    return FileResponse(ADMIN_STATIC / "index.html")


@app.get("/livez")
def liveness():
    return {"ok": True}


@app.get("/api/auth/session")
def auth_session(request: Request):
    if settings.auth_mode == "cloudflare":
        identity = request.state.identity
        return {"mode": "cloudflare", "email": identity.email, "role": identity.role, "logout_url": "/cdn-cgi/access/logout"}
    return {"mode": "token"}


@app.get("/health", response_model=Health)
def health():
    return Health(
        ok=True,
        openclaw_enabled=settings.openclaw_enabled,
        line_enabled=settings.line_enabled,
        telegram_enabled=settings.telegram_enabled,
        db_path=settings.db_path if settings.app_env == "dev" else "configured",
    )


@app.get("/api/cases")
def list_cases():
    return case_repo.list()


@app.post("/api/cases")
def create_case(data: TripCaseCreate):
    return case_repo.create(data)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    obj = case_repo.get(case_id)
    if not obj:
        raise HTTPException(404, "case not found")
    return obj


@app.get("/api/mom/cases/{case_id}")
def get_mom_case(case_id: str):
    obj = case_repo.get(case_id)
    if not obj:
        raise HTTPException(404, "case not found")
    workflow = case_workflow(case_id)
    return {**workflow, "next_action": next_best_action(obj, workflow)}


@app.get("/api/mom/cases/{case_id}/options")
def mom_case_options(case_id: str):
    try:
        return case_workflow(case_id)
    except KeyError:
        raise HTTPException(404, "case not found")


@app.post("/api/mom/cases/{case_id}/options")
def mom_add_manual_option(case_id: str, data: ManualOptionCreate):
    try:
        return add_manual_option(case_id, data)
    except KeyError:
        raise HTTPException(404, "case not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/mom/cases/{case_id}/selection")
def mom_select_option(case_id: str, data: CaseOptionSelection):
    try:
        return select_case_option(case_id, data.option_id)
    except KeyError:
        raise HTTPException(404, "case or option not found")
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.delete("/api/mom/cases/{case_id}/selection/{kind}")
def mom_clear_selection(case_id: str, kind: str):
    if kind not in {"flight", "hotel"}:
        raise HTTPException(422, "kind must be flight or hotel")
    if not case_repo.get(case_id):
        raise HTTPException(404, "case not found")
    try:
        case_workflow_repo.clear_selection(case_id, kind)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    return {"cleared": True}


@app.patch("/api/cases/{case_id}")
def patch_case(case_id: str, patch: TripCasePatch, request: Request):
    try:
        return case_repo.patch(case_id, patch.model_dump(exclude_unset=True), actor=agency_actor(request))
    except KeyError:
        raise HTTPException(404, "case not found")
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_context=False))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.post("/api/guided/{session_id}/start")
def guided_start(session_id: str, reset: bool = False):
    return guided_intake.start(session_id, reset=reset)


@app.get("/api/guided/{session_id}/resume")
def guided_resume(session_id: str):
    return guided_intake.resume(session_id)


@app.post("/api/guided/{session_id}/back")
def guided_back(session_id: str):
    return guided_intake.back(session_id)


@app.post("/api/guided/{session_id}/save")
def guided_save(session_id: str):
    return guided_intake.save(session_id)


@app.post("/api/guided/{session_id}/reset")
def guided_reset(session_id: str):
    return guided_intake.reset(session_id)


@app.post("/api/guided/{session_id}/reply")
def guided_reply(session_id: str, text: str = Body(embed=True)):
    return guided_intake.reply(session_id, text)


@app.get("/api/demo/flights")
def demo_flights(origin: str = "TPE", destination: str = "NRT", adults: int = 1):
    return {
        "customer_safe": False,
        "warning": "DEMO DATA - do not quote to customers",
        "results": rank_flights(demo_provider.flights(origin, destination, adults)),
    }


@app.get("/api/demo/hotels")
def demo_hotels(destination: str = "Tokyo", nights: int = 2):
    return {
        "customer_safe": False,
        "warning": "DEMO DATA - do not quote to customers",
        "results": rank_hotels(demo_provider.hotels(destination, nights)),
    }


@app.post("/api/customer-reply")
async def customer_reply(req: CustomerReplyRequest):
    try:
        return await draft_customer_reply(req)
    except KeyError:
        raise HTTPException(404, "case not found")


@app.post("/api/agent/ask")
async def agent_ask(req: AgentAskRequest):
    trip = case_repo.get(req.case_id) if req.case_id else None
    context = f"TripCase: {trip.model_dump(mode='json') if trip else 'none'}"
    return await openclaw_client.ask(
        req.message,
        req.session_user or f"web:{req.case_id or 'adhoc'}",
        extra_context=context,
    )


@app.get("/api/policy/{action}")
def policy_check(action: ActionType):
    return policy.decide(action).__dict__


@app.post("/api/approvals")
def create_approval(
    case_id: str | None = Body(default=None),
    action_type: ActionType = Body(),
    summary: str = Body(),
    amount_twd: int | None = Body(default=None),
):
    decision = policy.decide(action_type)
    if not decision.allowed:
        raise HTTPException(403, decision.reason)
    return approval_repo.create(case_id, action_type, summary, amount_twd)


@app.get("/api/approvals")
def list_approvals(status: str | None = "pending"):
    return approval_repo.list(status)


@app.post("/api/approvals/{approval_id}/{decision}")
def decide_approval(approval_id: str, decision: str):
    try:
        return approval_repo.decide(approval_id, decision)
    except KeyError:
        raise HTTPException(404, "approval not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/airlines")
def airline_registry():
    return {"airlines": [airline.public_dict() for airline in all_airlines()]}


@app.get("/api/hotels/networks")
def hotel_network_registry():
    return {
        "networks": [network.public_dict() for network in all_networks()],
        "builtin_domains": builtin_hotel_domains(),
        "note": "Independent hotels require a human-approved official-site grant before browser automation.",
    }


@app.get("/api/hotels/site-grants")
def list_hotel_site_grants(status: str | None = None):
    return hotel_site_grant_repo.list(status=status)


@app.post("/api/hotels/site-grants")
def create_hotel_site_grant(data: HotelSiteGrantCreate):
    try:
        return approve_independent_hotel_site(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/hotels/site-grants/{grant_id}/revoke")
def revoke_hotel_site_grant(grant_id: str):
    try:
        return hotel_site_grant_repo.revoke(grant_id)
    except KeyError:
        raise HTTPException(404, "hotel site grant not found")


@app.post("/api/browser/flight-search")
def create_structured_flight_search(data: FlightSearchRequest):
    try:
        if data.case_id:
            validate_search_case(require_case(data.case_id), data, "flight")
        return browser_task_service.create_flight_search(data)
    except KeyError:
        raise HTTPException(404, "case not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@app.get("/api/browser/runs")
def list_flight_search_runs(case_id: str | None = None, limit: int = 100):
    return flight_search_run_repo.list(case_id=case_id, limit=max(1, min(limit, 200)))


@app.get("/api/browser/runs/{run_id}")
def get_flight_search_run(run_id: str):
    run = flight_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "flight search run not found")
    tasks = browser_task_repo.list(limit=100, search_run_id=run.id)
    comparison = compare_official_flight_tasks(run.task_ids) if run.task_ids else None
    return {"run": run, "tasks": tasks, "comparison": comparison}


@app.post("/api/browser/runs/{run_id}/select")
def select_flight_option(run_id: str, data: FlightOptionSelectionRequest):
    try:
        return browser_task_service.select_option(run_id, data.task_id, data.option_id)
    except KeyError:
        raise HTTPException(404, "run or task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/runs/{run_id}/run")
async def run_flight_search_run(run_id: str):
    run = flight_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "flight search run not found")
    if run.case_id and require_case(run.case_id).status.value == "closed":
        raise HTTPException(409, "已結案案件請先重新開案")
    results = []
    # Deliberately sequential while the POC shares one managed browser profile.
    for task_id in run.task_ids:
        try:
            results.append((await browser_task_service.run(task_id)).model_dump(mode="json"))
        except KeyError:
            results.append({"id": task_id, "status": "missing"})
        except ValueError as exc:
            results.append({"id": task_id, "status": "error", "error": str(exc)})
        except Exception:
            logger.exception("flight search task failed", extra={"task_id": task_id, "run_id": run_id})
            results.append({"id": task_id, "status": "error", "error": "browser task failed; operator review required"})
    refreshed = flight_search_run_repo.get(run_id)
    return {
        "run": refreshed,
        "results": results,
        "comparison": compare_official_flight_tasks(run.task_ids),
    }


@app.post("/api/browser/flight-search/run-batch")
async def run_structured_flight_batch(data: BrowserTaskBatchRequest):
    results = []
    for task_id in data.task_ids:
        try:
            results.append((await browser_task_service.run(task_id)).model_dump(mode="json"))
        except KeyError:
            results.append({"id": task_id, "status": "missing"})
        except ValueError as exc:
            results.append({"id": task_id, "status": "error", "error": str(exc)})
        except Exception:
            logger.exception("flight batch task failed", extra={"task_id": task_id})
            results.append({"id": task_id, "status": "error", "error": "browser task failed; operator review required"})
    return {"results": results, "comparison": compare_official_flight_tasks(data.task_ids)}


@app.post("/api/browser/flight-search/compare")
def compare_structured_flight_search(data: BrowserTaskBatchRequest):
    try:
        return compare_official_flight_tasks(data.task_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/revalidate")
def create_flight_revalidation(data: FlightRevalidationCreateRequest):
    try:
        return browser_task_service.create_revalidation(data)
    except KeyError:
        raise HTTPException(404, "search task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/revalidate/{task_id}/summary")
def get_flight_revalidation_summary(task_id: str):
    try:
        return summarize_revalidation(task_id)
    except KeyError:
        raise HTTPException(404, "revalidation task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/booking/preflight")
def booking_preflight(data: BookingPreflightRequest):
    try:
        return build_booking_preflight(data)
    except KeyError:
        raise HTTPException(404, "revalidation task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/hotel-search")
def create_structured_hotel_search(data: HotelSearchRequest):
    if data.case_id:
        try:
            validate_search_case(require_case(data.case_id), data, "hotel")
        except KeyError:
            raise HTTPException(404, "case not found")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
    try:
        return browser_task_service.create_hotel_search(data)
    except KeyError:
        raise HTTPException(404, "case not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/hotel-runs")
def list_hotel_search_runs(case_id: str | None = None, limit: int = 100):
    return hotel_search_run_repo.list(case_id=case_id, limit=max(1, min(limit, 200)))


@app.get("/api/browser/hotel-runs/{run_id}")
def get_hotel_search_run(run_id: str):
    run = hotel_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "hotel search run not found")
    tasks = browser_task_repo.list(limit=100, search_run_id=run.id)
    comparison = compare_official_hotel_tasks(run.task_ids) if run.task_ids else None
    return {"run": run, "tasks": tasks, "comparison": comparison}


@app.post("/api/browser/hotel-runs/{run_id}/select")
def select_hotel_option(run_id: str, data: FlightOptionSelectionRequest):
    try:
        return browser_task_service.select_hotel_option(run_id, data.task_id, data.option_id)
    except KeyError:
        raise HTTPException(404, "run or task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/hotel-runs/{run_id}/run")
async def run_hotel_search_run(run_id: str):
    run = hotel_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "hotel search run not found")
    if run.case_id and require_case(run.case_id).status.value == "closed":
        raise HTTPException(409, "已結案案件請先重新開案")
    results = []
    for task_id in run.task_ids:
        try:
            results.append((await browser_task_service.run(task_id)).model_dump(mode="json"))
        except Exception:
            logger.exception("hotel search task failed", extra={"task_id": task_id, "run_id": run_id})
            results.append({"id": task_id, "status": "error", "error": "browser task failed; operator review required"})
    refreshed = hotel_search_run_repo.get(run_id)
    return {"run": refreshed, "results": results, "comparison": compare_official_hotel_tasks(run.task_ids)}


@app.post("/api/browser/hotel-search/compare")
def compare_structured_hotel_search(data: BrowserTaskBatchRequest):
    try:
        return compare_official_hotel_tasks(data.task_ids)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/browser/hotel-revalidate")
def create_hotel_revalidation(data: HotelRevalidationCreateRequest):
    try:
        return browser_task_service.create_hotel_revalidation(data)
    except KeyError:
        raise HTTPException(404, "hotel search task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/hotel-revalidate/{task_id}/summary")
def get_hotel_revalidation_summary(task_id: str):
    try:
        return summarize_hotel_revalidation(task_id)
    except KeyError:
        raise HTTPException(404, "hotel revalidation task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/hotel-booking/preflight")
def hotel_booking_preflight(data: HotelBookingPreflightRequest):
    try:
        return build_hotel_booking_preflight(data)
    except KeyError:
        raise HTTPException(404, "hotel revalidation task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/tasks")
def list_browser_tasks(limit: int = 100, search_run_id: str | None = None):
    return browser_task_repo.list(limit=max(1, min(limit, 200)), search_run_id=search_run_id)


@app.post("/api/browser/tasks")
def create_browser_task(data: BrowserTaskCreate):
    try:
        return browser_task_service.create(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/tasks/{task_id}/attempts")
def get_browser_task_attempts(task_id: str):
    if not browser_task_repo.get(task_id):
        raise HTTPException(404, "browser task not found")
    return browser_attempt_repo.list_for_task(task_id)


@app.post("/api/browser/tasks/{task_id}/ingest")
def ingest_browser_task_result(task_id: str, data: BrowserTaskIngestRequest):
    try:
        return browser_task_service.ingest(task_id, data)
    except KeyError:
        raise HTTPException(404, "browser task not found")
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/browser/tasks/{task_id}")
def get_browser_task(task_id: str):
    obj = browser_task_repo.get(task_id)
    if not obj:
        raise HTTPException(404, "browser task not found")
    return obj


@app.post("/api/browser/tasks/{task_id}/run")
async def run_browser_task(task_id: str):
    try:
        return await browser_task_service.run(task_id)
    except KeyError:
        raise HTTPException(404, "browser task not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception:
        logger.exception("browser task failed", extra={"task_id": task_id})
        raise HTTPException(502, "browser task failed; operator review required")


@app.get("/api/browser/lab/summary")
def browser_lab_summary(limit: int = 1000):
    return build_browser_lab_summary(limit=max(1, min(limit, 5000)))


async def _execute_flight_run_background(run_id: str) -> None:
    run = flight_search_run_repo.get(run_id)
    if not run:
        return
    try:
        flight_search_run_repo.set_status(run_id, "running")
        for task_id in run.task_ids:
            try:
                await browser_task_service.run(task_id)
            except Exception:
                logger.exception("background flight search task failed", extra={"run_id": run_id, "task_id": task_id})
        # browser_task_service refreshes the run after each task. If nothing could run,
        # retain a visible review state instead of pretending success.
        refreshed = flight_search_run_repo.get(run_id)
        if refreshed and not refreshed.task_ids:
            flight_search_run_repo.set_status(run_id, "needs_review")
    except Exception:
        logger.exception("background flight run failed", extra={"run_id": run_id})
        try:
            flight_search_run_repo.set_status(run_id, "failed")
        except ValueError:
            # Closed cases reject late background business mutations.
            return


async def _execute_hotel_run_background(run_id: str) -> None:
    run = hotel_search_run_repo.get(run_id)
    if not run:
        return
    try:
        hotel_search_run_repo.set_status(run_id, "running")
        for task_id in run.task_ids:
            try:
                await browser_task_service.run(task_id)
            except Exception:
                logger.exception("background hotel search task failed", extra={"run_id": run_id, "task_id": task_id})
        refreshed = hotel_search_run_repo.get(run_id)
        if refreshed and not refreshed.task_ids:
            hotel_search_run_repo.set_status(run_id, "needs_review")
    except Exception:
        logger.exception("background hotel run failed", extra={"run_id": run_id})
        try:
            hotel_search_run_repo.set_status(run_id, "failed")
        except ValueError:
            # Closed cases reject late background business mutations.
            return



def agency_call(fn):
    try:
        return fn()
    except KeyError:
        raise HTTPException(404, "找不到此案件的紀錄") from None
    except OperationBusy as exc:
        raise HTTPException(503, str(exc)) from None
    except OperationConflict as exc:
        raise HTTPException(409, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


def agency_actor(request: Request) -> str:
    identity = getattr(request.state, "identity", None)
    return identity.email if identity else "operator"


def service_actor(request: Request) -> str:
    """Bind a web form to the authenticated actor, without granting permissions."""
    actor = agency_actor(request)
    expected = request.headers.get('x-travel-service-actor')
    if expected is not None:
        try:
            if re.search(r'%(?![0-9a-fA-F]{2})', expected):
                raise ValueError('Malformed actor encoding')
            expected = unquote(expected, errors='strict').strip().casefold()
        except (ValueError, UnicodeError):
            raise HTTPException(400, '操作帳號編碼無效') from None
        if expected != actor:
            raise HTTPException(412, '操作帳號已變更，請返回工作單核對上次結果，再重新填寫。')
    return actor


@app.get("/api/mom/work-items")
def agency_work_items():
    return {"items": agency.list_work_items(), "timezone": "Asia/Taipei"}


@app.get("/api/mom/cases/{case_id}/operations")
def agency_operations(case_id: str):
    return agency_call(lambda: agency.case_operations(case_id))


@app.post("/api/mom/cases/{case_id}/lifecycle/close")
def agency_close_case(case_id: str, data: CaseClose, request: Request):
    return agency_call(lambda: agency.close_case(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/lifecycle/reopen")
def agency_reopen_case(case_id: str, data: CaseReopen, request: Request):
    return agency_call(lambda: agency.reopen_case(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/quotes")
def agency_create_quote(case_id: str, data: QuoteCreate, request: Request):
    return agency_call(lambda: agency.create_quote(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/quotes/{quote_id}/{action}")
def agency_decide_quote(case_id: str, quote_id: str, action: str, data: QuoteDecision, request: Request):
    return agency_call(lambda: agency.decide_quote(case_id, quote_id, action, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/work-items")
def agency_create_work(case_id: str, data: WorkItemCreate, request: Request):
    return agency_call(lambda: agency.create_work_item(case_id, data, agency_actor(request)))


@app.patch("/api/mom/cases/{case_id}/work-items/{item_id}")
def agency_update_work(case_id: str, item_id: str, data: WorkItemPatch, request: Request):
    return agency_call(lambda: agency.patch_work_item(case_id, item_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/bookings")
def agency_create_booking(case_id: str, data: BookingCreate, request: Request):
    return agency_call(lambda: agency.create_booking(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/bookings/{booking_id}/rebind")
def agency_rebind_booking(case_id: str, booking_id: str, data: BookingRebind, request: Request):
    return agency_call(lambda: agency.rebind_booking(case_id, booking_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/bookings/{booking_id}/void")
def agency_void_booking(case_id: str, booking_id: str, data: VoidRecord, request: Request):
    return agency_call(lambda: agency.void_record(case_id, "bookings", booking_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/ledger")
def agency_create_ledger(case_id: str, data: LedgerCreate, request: Request):
    return agency_call(lambda: agency.create_ledger_entry(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/ledger/{entry_id}/void")
def agency_void_ledger(case_id: str, entry_id: str, data: VoidRecord, request: Request):
    return agency_call(lambda: agency.void_record(case_id, "ledger", entry_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/documents")
def agency_create_document(case_id: str, data: DocumentCreate, request: Request):
    return agency_call(lambda: agency.create_document(case_id, data, agency_actor(request)))


@app.patch("/api/mom/cases/{case_id}/documents/{document_id}")
def agency_update_document(case_id: str, document_id: str, data: DocumentPatch, request: Request):
    return agency_call(lambda: agency.patch_document(case_id, document_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/pretrip")
def agency_create_pack(case_id: str, data: PackCreate, request: Request):
    return agency_call(lambda: agency.create_pack(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/pretrip/{pack_id}/deliver")
def agency_deliver_pack(case_id: str, pack_id: str, data: PackDelivery, request: Request):
    return agency_call(lambda: agency.deliver_pack(case_id, pack_id, data, agency_actor(request)))


@app.get("/api/mom/cases/{case_id}/quotes/{quote_id}/document")
def agency_quote_document(case_id: str, quote_id: str):
    return HTMLResponse(agency_call(lambda: customer_document(case_id, quote_id, "quote")))


@app.get("/api/mom/cases/{case_id}/pretrip/{pack_id}/document")
def agency_pack_document(case_id: str, pack_id: str):
    return HTMLResponse(agency_call(lambda: customer_document(case_id, pack_id, "pretrip")))


@app.get("/api/mom/preferences")
def mom_preferences():
    return preferences_repo.get()


@app.patch("/api/mom/preferences")
def patch_mom_preferences(data: UserPreferencesPatch):
    # Keep only airlines the local registry actually understands. Unknown codes are
    # ignored rather than poisoning the next guided search.
    known = {a.code for a in all_airlines()}
    payload = data.model_dump(exclude_none=True, mode="json")
    if "preferred_airlines" in payload:
        payload["preferred_airlines"] = [c for c in payload["preferred_airlines"] if c in known]
        if not payload["preferred_airlines"]:
            payload["preferred_airlines"] = preferences_repo.get().preferred_airlines
    return preferences_repo.patch(UserPreferencesPatch.model_validate(payload))


@app.get("/api/mom/home")
def mom_home():
    return build_mom_home()


@app.post("/api/mom/intent")
def mom_intent(data: MomIntentRequest):
    return infer_mom_intent(data)


@app.get("/api/mom/search-progress/{kind}/{run_id}")
def mom_search_progress(kind: str, run_id: str):
    try:
        return search_run_progress(kind, run_id)
    except KeyError:
        raise HTTPException(404, "search run not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/mom/flight-search/{run_id}/start")
def mom_start_flight_search(run_id: str, background_tasks: BackgroundTasks):
    run = flight_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "flight search run not found")
    if run.case_id and require_case(run.case_id).status.value == "closed":
        raise HTTPException(409, "已結案案件請先重新開案")
    if run.status.value in {"running", "completed"}:
        return {"accepted": False, "reason": f"run already {run.status.value}", "progress": search_run_progress("flight", run_id)}
    if not settings.openclaw_enabled:
        return {"accepted": False, "reason": "openclaw_disabled", "message": "目前尚未連上 OpenClaw。查詢已經存好，可以之後再開始。", "progress": search_run_progress("flight", run_id)}
    try:
        flight_search_run_repo.set_status(run_id, "running")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    background_tasks.add_task(_execute_flight_run_background, run_id)
    return {"accepted": True, "run_id": run_id, "message": "已開始查官方航空網站。您可以先離開，稍後再回來看進度。"}


@app.post("/api/mom/hotel-search/{run_id}/start")
def mom_start_hotel_search(run_id: str, background_tasks: BackgroundTasks):
    run = hotel_search_run_repo.get(run_id)
    if not run:
        raise HTTPException(404, "hotel search run not found")
    if run.case_id and require_case(run.case_id).status.value == "closed":
        raise HTTPException(409, "已結案案件請先重新開案")
    if run.status.value in {"running", "completed"}:
        return {"accepted": False, "reason": f"run already {run.status.value}", "progress": search_run_progress("hotel", run_id)}
    if not settings.openclaw_enabled:
        return {"accepted": False, "reason": "openclaw_disabled", "message": "目前尚未連上 OpenClaw。查詢已經存好，可以之後再開始。", "progress": search_run_progress("hotel", run_id)}
    try:
        hotel_search_run_repo.set_status(run_id, "running")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    background_tasks.add_task(_execute_hotel_run_background, run_id)
    return {"accepted": True, "run_id": run_id, "message": "已開始查飯店官網。您可以先離開，稍後再回來看進度。"}


@app.post("/api/mom/skill-feedback")
def mom_skill_feedback(data: SkillFeedbackCreate):
    # Capture-only in v0.8.1: no production SKILL.md is edited here.
    return capture_skill_feedback(data)


@app.get("/api/mom/skill-feedback")
def list_mom_skill_feedback(skill_key: str | None = None, limit: int = 100):
    return skill_feedback_repo.list(skill_key=skill_key, limit=max(1, min(limit, 500)))


@app.get("/api/mom/skill-feedback/summary")
def mom_skill_feedback_summary(skill_key: str | None = None):
    return skill_feedback_repo.summary(skill_key=skill_key)


@app.get("/api/system/readiness")
def system_readiness():
    return build_system_readiness()


@app.get("/api/radar")
def radar():
    return build_radar()


@app.post("/webhooks/line")
async def line_webhook(request: Request):
    return await handle_line(request)


@app.post("/webhooks/telegram")
async def telegram_webhook(request: Request, payload: dict):
    return await handle_telegram(
        payload,
        request.headers.get("x-telegram-bot-api-secret-token"),
    )


@app.post("/api/browser/runs/{run_id}/abandon")
def abandon_flight_search(run_id: str, data: SearchAbandon, request: Request):
    return agency_call(lambda: agency.abandon_search("flight", run_id, data, agency_actor(request)))


@app.post("/api/browser/hotel-runs/{run_id}/abandon")
def abandon_hotel_search(run_id: str, data: SearchAbandon, request: Request):
    return agency_call(lambda: agency.abandon_search("hotel", run_id, data, agency_actor(request)))


@app.post("/api/browser/tasks/{task_id}/abandon")
def abandon_browser_task(task_id: str, data: SearchAbandon, request: Request):
    return agency_call(lambda: agency.abandon_standalone_task(task_id, data, agency_actor(request)))


from app.services import travel_files


@app.get("/api/mom/cases/{case_id}/travel-files")
def private_records(case_id: str):
    return agency_call(lambda: travel_files.list_private(case_id))


@app.post("/api/mom/cases/{case_id}/travellers")
def add_traveller(case_id: str, data: TravellerData, request: Request):
    return agency_call(lambda: travel_files.traveller_write(case_id, data, agency_actor(request)))


@app.patch("/api/mom/cases/{case_id}/travellers/{traveller_id}")
def update_traveller(case_id: str, traveller_id: str, data: TravellerData, request: Request):
    return agency_call(lambda: travel_files.traveller_write(case_id, data, agency_actor(request), traveller_id))


@app.post("/api/mom/cases/{case_id}/travellers/{traveller_id}/archive")
def archive_traveller(case_id: str, traveller_id: str, data: AttachmentArchive, request: Request):
    return agency_call(lambda: travel_files.archive_traveller(case_id, traveller_id, data, agency_actor(request)))


@app.get("/api/mom/cases/{case_id}/travellers/{traveller_id}/reveal")
def reveal_traveller(case_id: str, traveller_id: str, request: Request):
    return agency_call(lambda: travel_files.reveal_traveller(case_id, traveller_id, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/roster/verify")
def verify_roster(case_id: str, data: RosterVerify, request: Request):
    return agency_call(lambda: travel_files.verify_roster(case_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/documents/{document_id}/attachments")
async def upload_attachment(case_id: str, document_id: str, request: Request, request_id: str, expected_revision: int):
    import base64
    import hashlib
    content = await request.body()
    try:
        filename = base64.b64decode(request.headers.get('x-file-name', ''), validate=True).decode('utf-8')
        data = AttachmentUpload(request_id=request_id, expected_revision=expected_revision, filename=filename,
             media_type=request.headers.get('content-type', ''), size=len(content), sha256=hashlib.sha256(content).hexdigest())
    except (ValueError, UnicodeError):
        raise HTTPException(400, '請選擇有效的 PDF、JPEG 或 PNG，單檔上限 10 MB')
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(agency_call, lambda: travel_files.upload(case_id, document_id, data, content, agency_actor(request)))


@app.get("/api/mom/cases/{case_id}/attachment-receipts/{request_id}")
def upload_receipt(case_id: str, request_id: str, request: Request):
    from uuid import UUID
    try:
        identifier = UUID(request_id)
    except ValueError:
        raise HTTPException(400, '無效查詢編號')
    return agency_call(lambda: travel_files.upload_receipt(case_id, identifier, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/attachments/{attachment_id}/archive")
def archive_attachment(case_id: str, attachment_id: str, data: AttachmentArchive, request: Request):
    return agency_call(lambda: travel_files.archive(case_id, attachment_id, data, agency_actor(request)))


@app.get("/api/mom/cases/{case_id}/attachments/{attachment_id}/download")
def download_attachment(case_id: str, attachment_id: str, request: Request):
    raw, media, name = agency_call(lambda: travel_files.download(case_id, attachment_id, agency_actor(request)))
    return Response(raw, media_type=media, headers={'Content-Disposition': f'attachment; filename="{name}"',
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': 'sandbox'})


@app.post("/api/mom/cases/{case_id}/work-items/{item_id}/acknowledge")
def acknowledge_work(case_id: str, item_id: str, data: WorkAcknowledgement, request: Request):
    return agency_call(lambda: agency.acknowledge_work(case_id, item_id, data, agency_actor(request)))


@app.post("/api/mom/cases/{case_id}/work-handover")
def handover_work(case_id: str, data: WorkHandover, request: Request):
    return agency_call(lambda: agency.handover_work(case_id, data, agency_actor(request)))


@app.get("/api/system/backup-status")
def backup_status():
    from scripts.backup_bundle import status
    return status()


@app.post('/api/mom/cases/{case_id}/service-orders')
def service_order_create(case_id: str, data: ServiceOrderCreate, request: Request):
    return agency_call(lambda: service_orders.create(case_id, data, service_actor(request)))


@app.patch('/api/mom/cases/{case_id}/service-orders/{order_id}')
def service_order_patch(case_id: str, order_id: str, data: ServiceOrderPatch, request: Request):
    return agency_call(lambda: service_orders.patch(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/assessment')
def service_order_assess(case_id: str, order_id: str, data: ServiceAssessment, request: Request):
    return agency_call(lambda: service_orders.assess(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/decision')
def service_order_decide(case_id: str, order_id: str, data: ServiceDecision, request: Request):
    return agency_call(lambda: service_orders.decide(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/progress')
def service_order_progress(case_id: str, order_id: str, data: ServiceProgress, request: Request):
    return agency_call(lambda: service_orders.progress(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/settlement')
def service_order_settle(case_id: str, order_id: str, data: ServiceSettlement, request: Request):
    return agency_call(lambda: service_orders.settle(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/resolve')
def service_order_resolve(case_id: str, order_id: str, data: ServiceResolve, request: Request):
    return agency_call(lambda: service_orders.resolve(case_id, order_id, data, service_actor(request)))


@app.post('/api/mom/cases/{case_id}/service-orders/{order_id}/reopen')
def service_order_reopen(case_id: str, order_id: str, data: ServiceReopen, request: Request):
    return agency_call(lambda: service_orders.reopen(case_id, order_id, data, service_actor(request)))


@app.get('/api/mom/cases/{case_id}/service-order-receipts/{request_id}')
def service_order_receipt(case_id: str, request_id: UUID, request: Request):
    return agency_call(lambda: service_orders.receipt(case_id, request_id, service_actor(request)))
