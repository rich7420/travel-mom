"""Exercise Mom's responsive workspace on disposable synthetic data."""

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

from cryptography.fernet import Fernet
import httpx
from playwright.sync_api import expect, sync_playwright

from browser_test_support import free_port, source_manifest, stop_server, wait_live


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--executable-path")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    if args.executable_path and args.browser != "chromium":
        parser.error("custom executable is only supported with chromium")
    out = args.output
    out.mkdir(parents=True, exist_ok=True)
    sources = source_manifest()
    checks, errors, measurements = [], [], []

    def check(label, condition):
        assert condition, label
        checks.append(label)

    with tempfile.TemporaryDirectory(prefix="mom-layout-") as temp:
        base = f"http://127.0.0.1:{free_port()}"
        env = {
            k: os.environ[k]
            for k in ("PATH", "LANG", "TZ", "TMPDIR")
            if k in os.environ
        }
        env.update(
            TRAVEL_DESK_DB=str(Path(temp) / "desk.db"),
            APP_ENV="dev",
            AUTH_MODE="token",
            TRAVEL_DESK_ADMIN_TOKEN="",
            OPENCLAW_ENABLED="false",
            LINE_ENABLED="false",
            TELEGRAM_ENABLED="false",
            REMINDERS_ENABLED="false",
            REMINDER_LINE_ENABLED="false",
            REMINDER_SMTP_ENABLED="false",
            PII_FERNET_KEY=Fernet.generate_key().decode(),
            ATTACHMENTS_DIR=str(Path(temp) / "files"),
            BACKUP_DIR=str(Path(temp) / "backups"),
        )
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
                    base.rsplit(":", 1)[1],
                ],
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                wait_live(base)
                with (
                    httpx.Client(base_url=base, trust_env=False) as api,
                    sync_playwright() as pw,
                ):

                    def post(path, payload):
                        response = api.post(path, json=payload)
                        assert response.status_code == 200, response.text
                        return response.json()

                    assert (
                        api.patch(
                            "/api/mom/preferences", json={"onboarding_complete": True}
                        ).status_code
                        == 200
                    )
                    start = datetime.now(timezone.utc).date() + timedelta(days=30)
                    notes = "希望去程早班機，回程下午。\n行李與餐食請另外核對。"
                    payload = dict(
                        destination="東京",
                        adults=2,
                        children=1,
                        children_ages=[8],
                        infants=1,
                        depart_date=start.isoformat(),
                        return_date=(start + timedelta(days=5)).isoformat(),
                        budget_twd=48000,
                        notes=notes,
                    )
                    cases = [
                        post(
                            "/api/cases",
                            {**payload, "customer_name": f"合成案例 {i + 1:02}"},
                        )
                        for i in range(6)
                    ]
                    browser = getattr(pw, args.browser).launch(
                        headless=not args.headed,
                        **(
                            {"executable_path": args.executable_path}
                            if args.executable_path
                            else {}
                        ),
                    )
                    try:
                        context = browser.new_context(
                            locale="zh-TW", reduced_motion="reduce"
                        )
                        page = context.new_page()
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(base)
                        page.wait_for_function(
                            "()=>state.preferences!==null&&state.home!==null&&state.cases.length===6"
                        )
                        expect(page.locator("#priorityList .work-card")).to_have_count(
                            4
                        )

                        def fits(label):
                            overflow = page.evaluate("""()=>[document.documentElement,...document.querySelectorAll('.hero-card,.sheet,.case-facts,.operation-tiles')]
                                .filter(el=>el.getBoundingClientRect().width && el.scrollWidth>el.clientWidth+1).map(el=>el.className||el.tagName)""")
                            check(
                                label + " content fits without clipping", not overflow
                            )
                            small = page.locator(
                                "button:visible, .guide-link:visible, summary:visible"
                            ).evaluate_all("""els=>els.filter(el=>{
                                const r=el.getBoundingClientRect();return r.height<43.9||r.width<43.9;
                            }).map(el=>el.textContent)""")
                            check(label + " controls at least 44px", not small)

                        for width in (1360, 1024, 768, 390, 360):
                            for scale in ("normal", "large", "xlarge"):
                                label = f"{width}px {scale}"
                                page.set_viewport_size({"width": width, "height": 900})
                                page.evaluate("scale=>applyFontScale(scale)", scale)
                                fits(label + " home")
                                if width == 1360:
                                    hero = page.locator(".hero-card").bounding_box()
                                    first = page.locator(
                                        "#priorityList .work-card"
                                    ).first.bounding_box()
                                    check(
                                        label
                                        + " first priority fully in initial viewport",
                                        first["y"] >= 0
                                        and first["y"] + first["height"] < 900,
                                    )
                                    check(label + " compact hero", hero["height"] < 260)
                                    measurements.append(
                                        {
                                            "width": width,
                                            "font": scale,
                                            "hero_height": hero["height"],
                                            "first_priority_y": first["y"],
                                        }
                                    )
                                page.screenshot(
                                    path=str(out / f"home-{width}-{scale}.png")
                                )
                                page.keyboard.press("Tab")
                                page.evaluate("id=>MomApp.openCase(id)", cases[0]["id"])
                                expect(page.locator(".case-facts")).to_be_visible()
                                expect(page.locator("#sheetTitle")).to_be_focused()
                                check(
                                    label + " keyboard entry has visible title focus",
                                    page.locator("#sheetTitle").evaluate(
                                        "el=>el.matches(':focus-visible') && parseFloat(getComputedStyle(el).outlineWidth)>0"
                                    ),
                                )
                                fits(label + " case")
                                expect(page.locator(".case-facts")).to_contain_text(
                                    "2 大人、1 小孩、1 嬰兒"
                                )
                                expect(page.locator(".case-notes dd")).to_have_text(
                                    notes
                                )
                                check(
                                    label + " all five work entries remain available",
                                    page.locator(".operation-tiles button").count()
                                    == 5,
                                )
                                page.screenshot(
                                    path=str(out / f"case-{width}-{scale}.png")
                                )
                                page.locator(".sheet").evaluate(
                                    "el=>el.scrollTop=el.scrollHeight"
                                )
                                close = page.locator(
                                    "#sheet .close-button"
                                ).bounding_box()
                                panel = page.locator(".sheet").bounding_box()
                                if width == 1360:
                                    header = page.locator(".sheet-head").bounding_box()
                                    measurements.append(
                                        {
                                            "font": scale,
                                            "scrolled_header_offset": header["y"]
                                            - panel["y"],
                                        }
                                    )
                                    check(
                                        label
                                        + " sticky header covers scrolling content",
                                        header["y"] - panel["y"] <= 0.5,
                                    )
                                    page.screenshot(
                                        path=str(
                                            out / f"scrolled-case-{width}-{scale}.png"
                                        )
                                    )
                                check(
                                    label + " close remains inside scrolled sheet",
                                    panel["y"] <= close["y"]
                                    and close["y"] + close["height"]
                                    <= min(900, panel["y"] + panel["height"]),
                                )
                                page.keyboard.press("Escape")
                                expect(page.locator("#sheet")).not_to_be_visible()

                        page.set_viewport_size({"width": 390, "height": 900})
                        page.evaluate("()=>applyFontScale('xlarge')")
                        page.evaluate("id=>MomApp.openCase(id)", cases[0]["id"])
                        expect(page.locator(".case-facts")).to_be_visible()
                        for module in (
                            "quotes",
                            "tasks",
                            "bookings",
                            "ledger",
                            "pretrip",
                        ):
                            page.locator(
                                f'.operation-tiles [data-module="{module}"] svg'
                            ).click()
                            expect(page.locator("#sheetBack")).to_be_visible()
                            page.locator(".sheet").evaluate(
                                "el=>el.scrollTop=el.scrollHeight"
                            )
                            page.locator("#sheetBack").click()
                            expect(page.locator(".case-facts")).to_be_visible()
                            expect(
                                page.locator(
                                    f'.operation-tiles [data-module="{module}"]'
                                )
                            ).to_be_focused()
                            check(module + " SVG entry and keyboard-focus return", True)
                        page.keyboard.press("Escape")

                        long_case = post(
                            "/api/cases",
                            {
                                **payload,
                                "customer_name": "合成長姓名" * 12,
                                "destination": "LONGDESTINATION" * 8,
                                "notes": "<script>privateTextOnly</script>\n"
                                + "長備註" * 100,
                            },
                        )
                        for width in (360, 768, 1360):
                            page.set_viewport_size({"width": width, "height": 900})
                            page.evaluate("id=>MomApp.openCase(id)", long_case["id"])
                            expect(page.locator(".case-facts")).to_be_visible()
                            fits(f"{width}px long name and notes")
                            check(
                                f"{width}px long title leaves space for work",
                                page.locator(".sheet-head").bounding_box()["height"]
                                < 200,
                            )
                            page.locator(".sheet-full-title summary").click()
                            expect(page.locator(".sheet-full-title p")).to_have_text(
                                long_case["customer_name"]
                                + " · "
                                + long_case["destination"]
                            )
                            page.locator(".sheet-full-title summary").click()
                            check(
                                f"{width}px notes remain text",
                                page.locator("#sheetBody script").count() == 0
                                and "<script>"
                                in page.locator(".case-notes").inner_text(),
                            )
                            page.screenshot(path=str(out / f"long-case-{width}.png"))
                            page.keyboard.press("Escape")

                        local_noon = datetime.now(timezone(timedelta(hours=8))).replace(
                            hour=12, minute=0, second=0, microsecond=0
                        )
                        for i in range(7):
                            post(
                                f"/api/mom/cases/{cases[0]['id']}/work-items",
                                dict(
                                    request_id=str(uuid4()),
                                    title=f"合成期限 {i + 1}",
                                    kind="reply",
                                    owner="合成同事",
                                    due_at=(
                                        local_noon - timedelta(days=i % 2)
                                    ).isoformat(),
                                    source="合成供應商通知",
                                    notes="保留完整來源與期限",
                                ),
                            )
                        page.evaluate("()=>MomApp.loadHome()")
                        expect(
                            page.locator("#homeDeadlines .operation-record")
                        ).to_have_count(7)
                        check(
                            "all seven urgent tasks remain unabridged",
                            page.locator("#homeDeadlines .operation-record").count()
                            == 7,
                        )
                        page.screenshot(path=str(out / "urgent-tasks.png"))
                        first_emphasis = page.locator(
                            "#priorityList .work-card button"
                        ).first.evaluate("el=>getComputedStyle(el).backgroundColor")
                        page.route(
                            "**/api/mom/home",
                            lambda route: route.fulfill(
                                status=503,
                                content_type="application/json",
                                body='{"detail":"synthetic unavailable"}',
                            ),
                        )
                        page.evaluate("()=>MomApp.loadHome()")
                        expect(
                            page.locator("#priorityList .load-error")
                        ).to_be_visible()
                        check(
                            "failed refresh retains priority work and retry",
                            page.locator("#priorityList .work-card").count() == 4,
                        )
                        check(
                            "failed refresh preserves first priority emphasis",
                            page.locator(
                                "#priorityList .work-card button"
                            ).first.evaluate("el=>getComputedStyle(el).backgroundColor")
                            == first_emphasis,
                        )
                        page.unroute("**/api/mom/home")
                        page.locator('[data-action="retry-home"]').click()
                        expect(page.locator("#priorityList .load-error")).to_have_count(
                            0
                        )
                        check("failed home refresh recovers", True)
                        check(
                            "no visible version",
                            "v0.8.1" not in page.locator("body").inner_text(),
                        )
                        check("no JavaScript errors", not errors)
                    finally:
                        browser.close()
            finally:
                stop_server(server)

    assert source_manifest() == sources, "Application changed during layout validation"
    (out / "results.json").write_text(
        json.dumps(
            {
                "browser": args.browser,
                "executable": args.executable_path,
                "headed": args.headed,
                "checks": checks,
                "javascript_errors": errors,
                "measurements": measurements,
                "source_sha256": sources,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"{len(checks)} workspace layout checks passed")


if __name__ == "__main__":
    main()
