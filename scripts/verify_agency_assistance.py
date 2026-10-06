"""Real browser journeys for customer history, traveller fulfilment and reminder policies.

Runs entirely on disposable synthetic data. Outbound channels are disabled.
Supports installed Brave via --executable-path and --headed.
"""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sqlite3
import sys
import tempfile
from uuid import uuid4

from cryptography.fernet import Fernet
import httpx
from playwright.sync_api import sync_playwright, expect
from browser_test_support import free_port, wait_live, stop_server, source_manifest


def proof(**fields):
    return {
        "request_id": str(uuid4()),
        "reference": "合成通知編號",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "checked": True,
        **fields,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", choices=["chromium", "firefox", "webkit"], default="chromium"
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--executable-path")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    sources = source_manifest()

    def check(name, ok=True):
        assert ok, name
        checks.append(name)
        print("PASS", name, flush=True)

    with tempfile.TemporaryDirectory(prefix="agency-assistance-browser-") as temp:
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        env = {
            **os.environ,
            "TRAVEL_DESK_DB": str(Path(temp) / "desk.db"),
            "APP_ENV": "dev",
            "AUTH_MODE": "token",
            "TRAVEL_DESK_ADMIN_TOKEN": "",
            "OPENCLAW_ENABLED": "false",
            "LINE_ENABLED": "false",
            "TELEGRAM_ENABLED": "false",
            "REMINDERS_ENABLED": "false",
            "REMINDER_LINE_ENABLED": "false",
            "REMINDER_SMTP_ENABLED": "false",
            "PII_FERNET_KEY": Fernet.generate_key().decode(),
            "ATTACHMENTS_DIR": str(Path(temp) / "files"),
            "BACKUP_DIR": str(Path(temp) / "backups"),
        }
        with (out / "server.log").open("w") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                wait_live(base)
                with httpx.Client(base_url=base, trust_env=False) as api:
                    api.patch(
                        "/api/mom/preferences", json={"onboarding_complete": True}
                    )

                    def request(method, path, data=None):
                        r = api.request(method, path, json=data)
                        assert r.status_code == 200, r.text
                        return r.json()

                    case = request(
                        "POST",
                        "/api/cases",
                        {
                            "customer_name": "合成客戶工作台",
                            "destination": "東京",
                            "adults": 1,
                            "depart_date": (
                                datetime.now(timezone.utc).date() + timedelta(days=14)
                            ).isoformat(),
                            "return_date": (
                                datetime.now(timezone.utc).date() + timedelta(days=18)
                            ).isoformat(),
                        },
                    )
                    c = case["id"]
                    path = "/api/mom/cases/" + c
                    option = request(
                        "POST",
                        path + "/options",
                        {
                            "kind": "flight",
                            "supplier_name": "合成供應商",
                            "source_reference": "通知",
                            "title": "合成機票",
                            "details": "一位往返",
                            "conditions": "依通知核對",
                            "total_amount": "10000",
                            "currency": "TWD",
                            "observed_at": datetime.now(timezone.utc).isoformat(),
                            "confirmed_for_case": True,
                        },
                    )
                    request("POST", path + "/selection", {"option_id": option["id"]})
                    q = request(
                        "POST",
                        path + "/quotes",
                        {
                            "request_id": str(uuid4()),
                            "title": "合成報價",
                            "valid_until": (
                                datetime.now(timezone.utc) + timedelta(hours=1)
                            ).isoformat(),
                            "includes": "機票",
                            "excludes": "未列費用",
                        },
                    )
                    request("POST", path + "/quotes/" + q["id"] + "/sent", proof())
                    request("POST", path + "/quotes/" + q["id"] + "/accept", proof())
                    request(
                        "POST",
                        path + "/bookings",
                        proof(
                            kind="flight",
                            title="合成正式機票",
                            supplier="合成供應商",
                            confirmation_number="E2E-" + uuid4().hex[:8],
                            customer_details="人工確認",
                        ),
                    )
                    request(
                        "POST",
                        path + "/travellers",
                        {
                            "request_id": str(uuid4()),
                            "name": "合成旅客",
                            "category": "adult",
                            "date_of_birth": "1990-01-01",
                            "passport_number": "PRIVATE-PASSPORT",
                            "passport_expiry": "2030-01-01",
                            "nationality": "TW",
                        },
                    )
                    request(
                        "POST",
                        path + "/work-items",
                        {
                            "request_id": str(uuid4()),
                            "title": "合成補件期限",
                            "kind": "document",
                            "owner": "媽媽",
                            "due_at": (
                                datetime.now(timezone.utc) + timedelta(hours=1)
                            ).isoformat(),
                            "source": "供應商通知",
                        },
                    )
                    with sync_playwright() as pw:
                        launch = {"headless": not args.headed}
                        if args.executable_path:
                            launch["executable_path"] = args.executable_path
                        browser = getattr(pw, args.browser).launch(**launch)
                        context = browser.new_context(
                            viewport={"width": 1360, "height": 900},
                            locale="zh-TW",
                            permissions=["clipboard-read", "clipboard-write"]
                            if args.browser == "chromium"
                            else [],
                        )
                        page = context.new_page()
                        page.on("pageerror", lambda e: errors.append(str(e)))
                        page.on("dialog", lambda d: d.accept())
                        page.goto(base)
                        page.wait_for_function(
                            "()=>state.preferences!==null&&state.cases.length>0"
                        )

                        def case_open(which=c):
                            page.evaluate("(c)=>MomApp.openCase(c)", which)
                            expect(
                                page.locator("[data-action=crm-open]")
                            ).to_be_visible()

                        def fill_proof(form):
                            form.locator("[name=reference]").fill("合成UI核對")
                            form.locator("[name=checked]").check()

                        def save(form):
                            fill_proof(form)
                            form.locator("button[type=submit]").click()
                            expect(form).to_have_count(0)

                        case_open()
                        page.locator("[data-action=crm-open]").click()
                        expect(page.locator("#sheetBody")).to_contain_text(
                            "尚未關聯客戶"
                        )
                        check("case exposes focused CRM with explicit empty state")
                        page.locator("[data-action=crm-customer-form]").click()
                        form = page.locator("#customerProfileForm")
                        form.locator("[name=display_name]").fill("合成王女士")
                        form.locator("[name=phone]").fill("PRIVATE-PHONE")
                        form.locator("[name=email]").fill("synthetic@example.test")
                        save(form)
                        expect(page.locator("#customerLinkForm")).to_be_visible()
                        check("customer creation returns explicit case linking form")
                        form = page.locator("#customerLinkForm")
                        form.locator("[name=reason]").fill("核對本人")
                        save(form)
                        expect(page.locator("#sheetBody")).to_contain_text("合成王女士")
                        check("explicit customer link enables communications")
                        check(
                            "CRM summary masks contacts",
                            "PRIVATE-PHONE"
                            not in page.locator("#sheetBody").inner_text(),
                        )
                        customer = api.get(path + "/crm").json()["customer"]
                        page.locator("[data-action=crm-consent-form]").click()
                        form = page.locator("#customerConsentForm")
                        form.locator("[name=granted]").select_option("true")
                        save(form)
                        check(
                            "email consent recorded independently",
                            api.get("/api/mom/customers/" + customer["id"]).json()[
                                "consents"
                            ]["email"]["granted"],
                        )
                        page.locator("[data-action=crm-message-form]").first.click()
                        form = page.locator("#communicationForm")
                        form.locator("[name=kind]").select_option("draft")
                        form.locator("[name=body]").fill("PRIVATE-目前草稿修改")
                        save(form)
                        check(
                            "draft persistence never marks message sent",
                            api.get(path + "/crm").json()["communications"][0]["status"]
                            == "draft",
                        )
                        page.locator("[data-action=crm-reveal]").click()
                        expect(page.locator("#crmMessageBody")).to_have_value(
                            "PRIVATE-目前草稿修改"
                        )
                        check("audited message reveal restores persisted draft")
                        page.locator("#crmMessageBody").fill("PRIVATE-再次修改")
                        page.locator("[data-action=crm-message-form]").first.click()
                        expect(
                            page.locator("#communicationForm [name=body]")
                        ).to_have_value("PRIVATE-再次修改")
                        save(page.locator("#communicationForm"))
                        check("draft edit uses current editor text")
                        page.reload()
                        page.wait_for_function("()=>state.preferences!==null")
                        case_open()
                        page.locator("[data-action=crm-open]").click()
                        page.locator("[data-action=crm-reveal]").click()
                        expect(page.locator("#crmMessageBody")).to_have_value(
                            "PRIVATE-再次修改"
                        )
                        check("draft survives real browser reload")
                        page.locator("[data-action=crm-message-attest]").click()
                        form = page.locator("#communicationAttestForm")
                        form.locator("[name=actually_sent]").check()
                        save(form)
                        check(
                            "only explicit manual send attestation marks sent",
                            api.get(path + "/crm").json()["communications"][0]["status"]
                            == "sent",
                        )
                        case_open()
                        page.locator("details.sales-actions").evaluate(
                            "(e)=>e.open=true"
                        )
                        page.locator(
                            "details.sales-actions [data-action=customer-reply]"
                        ).click()
                        form = page.locator("#replyForm")
                        form.locator("[name=incoming_text]").fill("請確認旅行安排")
                        form.locator("button[type=submit]").click()
                        expect(page.locator("#replyDraft")).to_be_visible()
                        page.locator("#replyDraft").fill(
                            "  PRIVATE-生成後的目前修改\n\n"
                        )
                        dialogs = []
                        page.on("dialog", lambda d: dialogs.append(d.message))
                        page.locator("[data-action=crm-save-reply]").click()
                        expect(page.locator("#replySaveForm")).to_be_visible()
                        check(
                            "save draft handoff does not request abandon confirmation",
                            not dialogs,
                        )
                        page.locator("#sheetBack").click()
                        expect(page.locator("#replyDraft")).to_have_value(
                            "  PRIVATE-生成後的目前修改\n\n"
                        )
                        expect(page.locator(".feedback-row")).to_be_visible()
                        check(
                            "cancel save restores current edited draft and feedback chrome"
                        )
                        page.locator("[data-action=crm-save-reply]").click()
                        save(page.locator("#replySaveForm"))
                        draft = api.get(path + "/crm").json()["communications"][0]
                        check(
                            "generated draft saves exact current text without marking sent",
                            draft["status"] == "draft"
                            and api.get(
                                path + "/communications/" + draft["id"] + "/reveal"
                            ).json()["body"]
                            == "  PRIVATE-生成後的目前修改\n\n",
                        )
                        case_open()
                        page.locator("[data-action=crm-open]").click()
                        page.locator("[data-action=crm-message-form]").first.click()
                        form = page.locator("#communicationForm")
                        form.locator("[name=kind]").select_option("complaint")
                        form.locator("[name=body]").fill("PRIVATE-客訴原文")
                        form.locator("[name=followup_at]").fill("2026-10-20T10:00")
                        save(form)
                        page.locator("[data-action=crm-reveal]").first.click()
                        expect(page.locator("#crmMessageBody")).to_have_value(
                            "PRIVATE-客訴原文"
                        )
                        page.locator("[data-action=crm-message-form]").first.click()
                        form = page.locator("#communicationForm")
                        form.locator("[name=owner]").fill("小李")
                        form.locator("[name=status]").select_option("resolved")
                        save(form)
                        check(
                            "complaint resolution retains original body",
                            api.get(path + "/crm").json()["communications"][0]["status"]
                            == "resolved",
                        )
                        # Commit succeeds but browser loses response. Frozen body reconciles owned UUID.
                        page.locator("[data-action=crm-message-form]").first.click()
                        form = page.locator("#communicationForm")
                        form.locator("[name=body]").fill("PRIVATE-遺失回應")
                        fill_proof(form)
                        page.evaluate(
                            """()=>{window.savedFetch=fetch;window.communicationPosts=0;window.fetch=async(url,opts)=>{const result=await savedFetch(url,opts);if(String(url).endsWith('/communications')&&opts?.method==='POST'){communicationPosts++;if(communicationPosts===1)throw new TypeError('synthetic response lost');}return result;};}"""
                        )
                        form.locator("button[type=submit]").click()
                        expect(form.locator(".form-error")).to_be_visible()
                        check(
                            "lost response retains metadata-only pending intent",
                            page.evaluate(
                                '(c)=>{const raw=sessionStorage.getItem("travel-assistance-intents:"+c);return raw&&!raw.includes("PRIVATE-")&&JSON.parse(raw).length===1;}',
                                c,
                            ),
                        )
                        # Change verified identity after the receipt returns from the real server,
                        # before the browser caller resumes. Old plaintext must not be restored.
                        page.evaluate(
                            """()=>{window.receiptFetch=fetch;window.fetch=async(url,opts)=>{const result=await receiptFetch(url,opts);if(String(url).includes('/assistance-receipts/')){state.auth={mode:'token',email:'other@example.test'};dispatchEvent(new Event('travel-actor-changed'));}return result;};}"""
                        )
                        form.locator("[data-action=assistance-reconcile]").click()
                        expect(page.locator("#toast")).to_contain_text("帳號已變更")
                        check(
                            "actor switch during awaited receipt keeps UUID and prevents duplicate write",
                            page.evaluate(
                                '(c)=>communicationPosts===1&&sessionStorage.getItem("travel-assistance-intents:"+c)!==null',
                                c,
                            ),
                        )
                        check(
                            "actor switch replaces private fields with metadata-only reconciliation chrome",
                            form.locator("[name=body]").count() == 0
                            and form.locator(
                                "[data-action=assistance-reconcile]"
                            ).count()
                            == 1,
                        )
                        page.evaluate(
                            "()=>{window.fetch=window.receiptFetch;state.auth={mode:'token'};dispatchEvent(new Event('travel-actor-changed'));}"
                        )
                        form.locator("[data-action=assistance-reconcile]").click()
                        expect(form).to_have_count(0)
                        check(
                            "owned receipt recovery avoids second POST",
                            page.evaluate("()=>communicationPosts===1"),
                        )
                        page.evaluate("()=>window.fetch=window.savedFetch")
                        # Both 401 and 412 retain a usable metadata shell after private scrubbing.
                        for status in (401, 412):
                            page.locator("[data-action=crm-message-form]").first.click()
                            form = page.locator("#communicationForm")
                            form.locator("[name=body]").fill(f"PRIVATE-失效-{status}")
                            fill_proof(form)
                            page.evaluate(
                                """status=>{window.authFetch=fetch;window.fetch=async(url,opts)=>{if(String(url).endsWith('/communications')&&opts?.method==='POST')return new Response(JSON.stringify({detail:'synthetic identity precondition',auth_mode:'cloudflare'}),{status});return authFetch(url,opts);};}""",
                                status,
                            )
                            form.locator("button[type=submit]").click()
                            if status == 401:
                                expect(page.locator("#loginDialog")).to_be_visible()
                                page.locator("#loginDialog [data-action=login]").click()
                                expect(page.locator("#loginDialog")).not_to_be_visible()
                            expect(
                                form.locator("[data-action=assistance-reconcile]")
                            ).to_be_visible()
                            request_id = page.evaluate(
                                '(c)=>JSON.parse(sessionStorage.getItem("travel-assistance-intents:"+c))[0].request_id',
                                c,
                            )
                            check(
                                f"{status} clears private fields and preserves metadata reconciliation",
                                form.locator("[name=body]").count() == 0
                                and request_id is not None,
                            )
                            page.evaluate("()=>window.fetch=window.authFetch")
                            form.locator("[data-action=assistance-reconcile]").click()
                            expect(page.locator("#toast")).to_contain_text("尚未保存")
                            form.locator("[data-action=crm-open]").click()
                            page.locator("[data-action=crm-message-form]").first.click()
                            form = page.locator("#communicationForm")
                            form.locator("[name=body]").fill(
                                f"PRIVATE-重新核對-{status}"
                            )
                            save(form)
                            check(
                                f"{status} re-entry reuses original owned UUID",
                                api.get(
                                    path + "/assistance-receipts/" + request_id
                                ).json()["committed"],
                            )
                        case_open()
                        page.locator("[data-module=pretrip]").click()
                        page.locator("[data-action=files-open]").click()
                        page.locator("[data-action=files-service-open]").click()
                        page.locator("[data-action=files-service-form]").click()
                        form = page.locator("#travellerServiceForm")
                        form.locator("[name=segment_label]").fill("PRIVATE-去程")
                        form.locator("[name=ticket_number]").fill("PRIVATE-TICKET")
                        form.locator("[name=seat]").fill("PRIVATE-走道")
                        form.locator("[name=seat_status]").select_option("confirmed")
                        save(form)
                        check(
                            "ticket summary remains masked",
                            "PRIVATE-TICKET"
                            not in page.locator("#sheetBody").inner_text(),
                        )
                        page.locator("[data-action=files-service-reveal]").click()
                        expect(page.locator("[data-private]")).to_contain_text(
                            "PRIVATE-TICKET"
                        )
                        check(
                            "per-traveller ticket and independent request status revealed"
                        )
                        page.evaluate(
                            "()=>dispatchEvent(new Event('travel-actor-changed'))"
                        )
                        check(
                            "verified actor change scrubs all private ticket content",
                            "PRIVATE-TICKET"
                            not in page.locator("#sheetBody").inner_text(),
                        )
                        page.locator("#sheetBack").click()
                        expect(page.locator("#sheetBack")).to_have_text("返回名冊與原件")
                        page.locator("#sheetBack").click()
                        expect(page.locator(".private-section")).to_have_count(2)
                        check("traveller services Back returns to original files sheet")
                        row = api.get(path + "/operations").json()["bookings"][0]
                        roster_before = api.get(path + "/travel-files").json()[
                            "roster"
                        ]["expected_state"]
                        request(
                            "POST",
                            path + "/bookings/" + row["id"] + "/rebind",
                            proof(reason="核對異動", customer_details="新版服務確認"),
                        )
                        page.locator("[data-action=files-service-open]").click()
                        expect(page.locator("#sheetBody")).to_contain_text(
                            "旅客或訂購已變更，需重新核對"
                        )
                        check(
                            "stale booking binding is visible in traveller service UI"
                        )
                        page.locator(
                            '[data-action=files-service-form][data-id]:not([data-id=""])'
                        ).click()
                        save(page.locator("#travellerServiceForm"))
                        expect(page.locator("#sheetBody")).to_contain_text("目前有效")
                        check(
                            "traveller service recheck captures current booking revision"
                        )
                        page.locator("[data-action=files-service-archive]").click()
                        save(page.locator("#travellerServiceForm"))
                        expect(page.locator("#sheetBody")).to_contain_text("已封存")
                        check(
                            "traveller service archive preserves history without identity invalidation",
                            api.get(path + "/travel-files").json()["roster"][
                                "expected_state"
                            ]
                            == roster_before,
                        )
                        page.locator("#sheetBack").click()
                        case_open()
                        page.locator(
                            "[data-action=ops-open][data-module=tasks]"
                        ).click()
                        page.locator("#sheetBody [data-action=reminder-form]").click()
                        form = page.locator("#reminderForm")
                        expect(form).to_contain_text("自動提醒尚未啟用")
                        form.locator("[name=body]").fill("PRIVATE-催件通知")
                        save(form)
                        check(
                            "disabled reminders can be configured without outbound credentials"
                        )
                        expect(page.locator("#sheetBody")).to_contain_text("Email")
                        check(
                            "reminder readiness and saved rule visible",
                            len(api.get(path + "/reminders").json()["rules"]) == 1
                            and not api.get(path + "/reminders").json()["jobs"],
                        )
                        page.locator("#sheetBody [data-action=reminder-form]").click()
                        form = page.locator("#reminderForm")
                        form.locator("[name=repeat_hours]").select_option("24")
                        save(form)
                        check(
                            "daily repeat policy saves captured source revision",
                            api.get(path + "/reminders").json()["rules"][0][
                                "repeat_hours"
                            ]
                            == 24,
                        )
                        page.locator("#sheetBack").click()
                        expect(
                            page.locator("#sheetBody [data-action=service-open]")
                        ).to_be_visible()
                        check("reminder Back returns to original case tasks module")
                        page.locator("#sheetBody [data-action=reminder-open]").click()
                        # Seed an unknown provider result in this disposable DB only.
                        current_rule = api.get(path + "/reminders").json()["rules"][0]
                        job_id = str(uuid4())
                        timestamp = datetime.now(timezone.utc).isoformat()
                        with sqlite3.connect(Path(temp) / "desk.db") as db:
                            raw = json.loads(
                                db.execute(
                                    "SELECT payload_json FROM agency_reminders WHERE id=?",
                                    (current_rule["id"],),
                                ).fetchone()[0]
                            )
                            frozen = {
                                "encrypted": Fernet(env["PII_FERNET_KEY"].encode())
                                .encrypt(
                                    json.dumps(
                                        {
                                            "recipient": "synthetic@example.test",
                                            "body": "PRIVATE-原寄送内容",
                                        }
                                    ).encode()
                                )
                                .decode(),
                                "recipient_kind": "staff",
                                "customer_id": None,
                                "source_kind": raw["source_kind"],
                                "source_id": raw["source_id"],
                                "source_owner": "媽媽",
                            }
                            db.execute(
                                "INSERT INTO agency_notification_jobs(id,rule_id,case_id,rule_revision,source_fingerprint,occurrence_date,channel,status,send_at,next_attempt_at,retry_key,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (
                                    job_id,
                                    raw["id"],
                                    c,
                                    raw["revision"],
                                    raw["source_fingerprint"],
                                    datetime.now(timezone.utc).date().isoformat(),
                                    "email",
                                    "unknown",
                                    timestamp,
                                    timestamp,
                                    str(uuid4()),
                                    json.dumps(frozen),
                                    timestamp,
                                ),
                            )
                        page.locator("#sheetBack").click()
                        page.locator("#sheetBody [data-action=reminder-open]").click()
                        page.locator("[data-action=reminder-job-reconcile]").click()
                        form = page.locator("#reminderJobForm")
                        expect(form).to_contain_text("PRIVATE-原寄送内容")
                        check(
                            "unknown reconciliation reveals immutable actual sent content"
                        )
                        form.locator("[name=decision]").select_option("retry")
                        fill_proof(form)
                        form.locator("button[type=submit]").click()
                        expect(form.locator(".form-error")).to_be_visible()
                        check(
                            "unknown retry requires explicit duplicate-risk checkbox",
                            api.get(path + "/reminders").json()["jobs"][0]["status"]
                            == "unknown",
                        )
                        form.locator("[name=decision]").select_option("accepted")
                        save(form)
                        check(
                            "manual unknown confirmation records provider acceptance",
                            api.get(path + "/reminders").json()["jobs"][0]["status"]
                            == "accepted",
                        )
                        case_open()
                        page.locator("[data-action=crm-open]").click()
                        page.locator("[data-action=crm-reveal]").first.click()
                        page.locator("#sheetBack").click()
                        for width in (390, 768, 1360):
                            page.set_viewport_size({"width": width, "height": 900})
                            page.evaluate(
                                "()=>document.documentElement.dataset.font='xlarge'"
                            )
                            check(
                                f"CRM no overflow at {width}",
                                page.evaluate(
                                    "()=>document.documentElement.scrollWidth<=innerWidth&&sheetBody.scrollWidth<=sheetBody.clientWidth"
                                ),
                            )
                            check(
                                f"CRM buttons minimum 44px at {width}",
                                page.locator("#sheetBody button").evaluate_all(
                                    "(buttons)=>buttons.filter(b=>b.getClientRects().length).every(b=>b.getBoundingClientRect().height>=44)"
                                ),
                            )
                            page.screenshot(path=str(out / f"assistance-{width}.png"))
                        other = request(
                            "POST",
                            "/api/cases",
                            {"customer_name": "合成完成後追蹤", "adults": 1},
                        )
                        other_id = other["id"]
                        other_path = "/api/mom/cases/" + other_id
                        order = request(
                            "POST",
                            other_path + "/service-orders",
                            proof(
                                kind="incident",
                                title="合成旅中協助",
                                request_details="實際需求",
                                owner="媽媽",
                                due_at=(
                                    datetime.now(timezone.utc) + timedelta(hours=1)
                                ).isoformat(),
                            ),
                        )
                        order = request(
                            "POST",
                            other_path + "/service-orders/" + order["id"] + "/progress",
                            proof(
                                expected_revision=order["revision"],
                                stage="safety_assistance",
                                message="已提供協助",
                            ),
                        )
                        order = request(
                            "POST",
                            other_path + "/service-orders/" + order["id"] + "/resolve",
                            proof(
                                expected_revision=order["revision"],
                                summary="已處理",
                                customer_notified_checked=True,
                            ),
                        )
                        preserved = {
                            k: order.get(k)
                            for k in (
                                "status",
                                "assessment",
                                "decision",
                                "execution",
                                "resolution",
                            )
                        }
                        case_open(other_id)
                        page.locator(
                            "#sheetBody [data-action=ops-open][data-module=tasks]"
                        ).click()
                        page.locator(
                            "#sheetBody [data-action=service-open]"
                        ).first.click()
                        page.locator("#sheetBody [data-action=service-detail]").click()
                        page.locator("details.service-secondary").evaluate(
                            "(e)=>e.open=true"
                        )
                        page.locator("[data-intent=note]").click()
                        form = page.locator("#serviceOrderForm")
                        form.locator("[name=stage]").select_option("contact_supplier")
                        form.locator("[name=message]").fill("完成後追加聯絡")
                        save(form)
                        current = api.get(other_path + "/operations").json()[
                            "service_orders"
                        ][0]
                        check(
                            "completed service contact note preserves adopted execution and resolution",
                            {k: current.get(k) for k in preserved} == preserved,
                        )
                        linked = api.get(path + "/crm").json()["customer"]
                        request(
                            "POST",
                            other_path + "/customer-link",
                            proof(
                                customer_id=linked["id"],
                                expected_revision=0,
                                reason="明確關聯合成客戶",
                            ),
                        )
                        case_state = api.get(other_path + "/operations").json()[
                            "lifecycle"
                        ]["expected_state"]
                        request(
                            "POST",
                            other_path + "/lifecycle/close",
                            proof(
                                expected_state=case_state,
                                outcome="withdrawn",
                                reason="合成結案",
                            ),
                        )
                        case_open(other_id)
                        page.locator("[data-action=crm-open]").click()
                        page.locator("[data-action=crm-message-form]").click()
                        form = page.locator("#communicationForm")
                        form.locator("[name=body]").fill("PRIVATE-結案後聯絡")
                        save(form)
                        check(
                            "closed case accepts CRM contact without reopening business",
                            api.get("/api/cases/" + other_id).json()["status"]
                            == "closed"
                            and api.get(other_path + "/crm").json()["communications"][
                                0
                            ]["status"]
                            == "noted",
                        )
                        page.locator("[data-action=crm-customer-history]").click()
                        expect(
                            page.locator("#sheetBody [data-action=open-case]")
                        ).to_have_count(2)
                        check(
                            "explicit customer history links both cases including closed contact history"
                        )
                        page.locator("[data-action=close-sheet]").click()
                        page.evaluate(
                            """()=>{window.settingsFetch=fetch;window.settingsStatusCalls=0;window.fetch=async(url,opts)=>{if(String(url).endsWith('/reminder-status')){settingsStatusCalls++;return new Response(JSON.stringify({enabled:true,channels:{email:false,line:false},staff_recipients:{email:[],line:[]},worker_running:false,restore_pending:false,last_tick_at:null}),{status:200,headers:{'content-type':'application/json'}});}return settingsFetch(url,opts);};}"""
                        )
                        page.locator(".nav-item[data-nav=settings]").click()
                        expect(page.locator("#reminderReadiness")).to_contain_text(
                            "提醒排程暫時未運作"
                        )
                        check(
                            "opening settings refreshes observed worker readiness",
                            page.evaluate("()=>settingsStatusCalls>0"),
                        )
                        expect(page.locator("#reminderReadiness")).to_contain_text(
                            "此通道尚未設定；可以先保存停用的提醒"
                        )
                        check("absent channel has actionable configuration copy")
                        page.evaluate("()=>window.fetch=window.settingsFetch")
                        check("no JavaScript errors", not errors)
                        (out / "results.json").write_text(
                            json.dumps(
                                {
                                    "browser": args.browser,
                                    "executable_path": args.executable_path,
                                    "headed": args.headed,
                                    "checks": checks,
                                    "javascript_errors": errors,
                                    "source_sha256": sources,
                                },
                                ensure_ascii=False,
                                indent=2,
                            )
                        )
                        browser.close()
            finally:
                stop_server(server)
    assert source_manifest() == sources, "Source changed during verification"
    print(len(checks), "assistance browser checks passed")


if __name__ == "__main__":
    main()
