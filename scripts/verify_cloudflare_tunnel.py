"""Real Quick Tunnel acceptance on disposable data, never the live desk.

Requires an independently verified cloudflared binary and its SHA256. Executes
the existing 48 assistance journeys through public HTTPS, with real token login.
This does not certify a named Tunnel, Access identities, MFA or human acceptance.
"""

import argparse
import ast
from contextlib import contextmanager
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from playwright.sync_api import (
    BrowserType,
    Error as PlaywrightError,
    expect,
    sync_playwright,
)

from browser_test_support import source_manifest, stop_server

ROOT = Path(__file__).resolve().parents[1]


def command_checks(source):
    return [
        ast.dump(node)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "check"
    ]


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise AssertionError("Runner integration changed: " + old)
    return source.replace(old, new, 1)


def minimal_env():
    # No dotenv or inherited credentials, and no replacement of the user's HOME.
    return {
        k: os.environ[k] for k in ("PATH", "LANG", "TZ", "TMPDIR") if k in os.environ
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cloudflared", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--browser", choices=("chromium", "firefox", "webkit"), default="chromium"
    )
    parser.add_argument("--executable-path")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--protected-edge", action="store_true")
    args = parser.parse_args()
    binary = args.cloudflared.resolve()
    if not re.fullmatch(r"[a-f0-9]{64}", args.expected_sha256):
        parser.error("expected SHA256 must contain 64 lowercase hex characters")
    out = args.output.resolve()
    if (out / "pids.json").exists():
        for record in json.loads((out / "pids.json").read_text()):
            current = subprocess.run(
                ["ps", "-ww", "-p", str(record["pid"]), "-o", "command="],
                capture_output=True,
                text=True,
            )
            if current.returncode == 0 and current.stdout.strip() == record["command"]:
                parser.error(
                    f"Previous owned process is still running: PID {record['pid']}"
                )
    if out.exists() and any(out.iterdir()):
        parser.error("output must be a new or empty evidence directory")
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)  # Access logs include the real public client IP.
    git_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    diff_sha = hashlib.sha256(
        subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=ROOT)
    ).hexdigest()
    pid_records = []
    token = secrets.token_hex(32)
    harness_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    sources = source_manifest()
    tunnels, browsers, probes = [], [], []
    cleanup = {"tunnel_pids_gone": [], "browser_pids_gone": []}
    started_requests, unauthorized_after_login = set(), []
    login = {"initial_401": False, "preferences_loaded": False, "accepted": False}
    origin = None
    local_origin = None
    journeys_completed = False
    main_stopped_verified = False
    original_launch = BrowserType.launch

    def record_process(pid, role):
        command = subprocess.check_output(
            ["ps", "-ww", "-p", str(pid), "-o", "command="], text=True
        ).strip()
        pid_records.append(
            {"pid": pid, "pgid": os.getpgid(pid), "role": role, "command": command}
        )
        pending = out / "pids.json.tmp"
        pending.write_text(json.dumps(pid_records, indent=2))
        pending.replace(out / "pids.json")

    def spawn_server(*values, **options):
        server = subprocess.Popen(*values, **options)
        try:
            record_process(server.pid, "origin")
        except BaseException:
            stop_server(server)
            raise
        return server

    def check(label, condition):
        if not condition:
            raise AssertionError(label)
        probes.append(label)
        print("PASS", label, flush=True)

    def stop_tunnel(proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
        if proc.pid not in cleanup["tunnel_pids_gone"]:
            cleanup["tunnel_pids_gone"].append(proc.pid)

    def wait_stopped(url):
        deadline = time.monotonic() + 30
        with httpx.Client(trust_env=False, timeout=5, follow_redirects=False) as client:
            while time.monotonic() < deadline:
                try:
                    response = client.get(
                        url + "/livez", params={"cleanup": uuid4().hex}
                    )
                    if (
                        response.status_code == 200
                        and response.text.strip() == '{"ok":true}'
                    ):
                        time.sleep(0.5)
                        continue
                    if response.status_code < 500:
                        # A login redirect/denial proves only gating, not teardown.
                        time.sleep(0.5)
                        continue
                    return True
                except httpx.HTTPError:
                    return True
        return False

    with tempfile.TemporaryDirectory(prefix="mom-real-tunnel-") as tunnel_temp:
        config = Path(tunnel_temp) / "empty.yml"
        config.write_text("{}\n")
        os.chmod(config, 0o600)

        def start_tunnel(local, protected=False):
            assert re.fullmatch(r"http://127\.0\.0\.1:[0-9]+", local)
            assert (
                hashlib.sha256(binary.read_bytes()).hexdigest() == args.expected_sha256
            )
            name = "protected" if protected else "public"
            log_path = out / (name + "-tunnel.log")
            command = [
                str(binary),
                "tunnel",
                "--config",
                str(config),
                "--no-autoupdate",
                "--loglevel",
                "info",
                "--metrics",
                "127.0.0.1:0",
                "--management-diagnostics=false",
                "--grace-period",
                "2s",
                "--url",
                local,
            ]
            if protected:
                command += ["--allowed-mail", "acceptance@example.invalid"]
            connector_env = {**minimal_env(), "TUNNEL_TRANSPORT_PROTOCOL": "http2"}
            with log_path.open("w") as log:
                proc = subprocess.Popen(
                    command,
                    cwd=tunnel_temp,
                    env=connector_env,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
            tunnels.append(proc)
            record_process(proc.pid, name + " tunnel")
            deadline = time.monotonic() + 120
            url = None
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError("cloudflared exited; inspect " + str(log_path))
                text = log_path.read_text()
                candidates = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
                candidates = [
                    v for v in candidates if v != "https://api.trycloudflare.com"
                ]
                if candidates and "Registered tunnel connection" in text:
                    assert "Requesting new quick Tunnel" in text
                    url = candidates[0]
                    break
                time.sleep(0.25)
            if not url:
                raise RuntimeError(
                    "Tunnel registration timed out; inspect " + str(log_path)
                )
            assert re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", url)
            with httpx.Client(
                trust_env=False, timeout=10, follow_redirects=False
            ) as client:
                while time.monotonic() < deadline:
                    try:
                        response = client.get(url + "/livez")
                        ready = (
                            response.status_code == 200
                            and response.json() == {"ok": True}
                            if not protected
                            else (
                                response.status_code in (401, 403)
                                or response.is_redirect
                                and urlsplit(
                                    response.headers.get("location", "")
                                ).hostname
                                != urlsplit(url).hostname
                            )
                        )
                        if ready:
                            return proc, url
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(0.5)
            raise RuntimeError(
                "Public HTTPS readiness timed out; inspect " + str(log_path)
            )

        def public_start(local):
            nonlocal origin, local_origin
            local_origin = local
            _, origin = start_tunnel(local)
            with httpx.Client(
                trust_env=False, timeout=20, follow_redirects=False
            ) as client:
                for path in (
                    "/api/cases",
                    "/api/mom/customers",
                    "/api/system/readiness",
                ):
                    r = client.get(origin + path)
                    check(
                        "anonymous public request denied: " + path, r.status_code == 401
                    )
                    check(
                        "private API response cannot be cached: " + path,
                        r.headers.get("cache-control") == "no-store",
                    )
                for headers in (
                    {"Authorization": "Bearer wrong"},
                    {"x-travel-desk-admin-token": "wrong"},
                    {"cf-access-jwt-assertion": "forged"},
                ):
                    check(
                        "untrusted credential does not replace test token: "
                        + next(iter(headers)),
                        client.get(origin + "/api/cases", headers=headers).status_code
                        == 401,
                    )
                check(
                    "URL parameter does not authenticate",
                    client.get(origin + "/api/cases?token=wrong").status_code == 401,
                )
                check(
                    "direct origin also denies anonymous",
                    client.get(local + "/api/cases").status_code == 401,
                )
                for path in ("/docs", "/redoc", "/openapi.json"):
                    check(
                        "production disables " + path,
                        client.get(origin + path).status_code == 404,
                    )
                check(
                    "admin shell loads before login; private APIs remain protected",
                    client.get(origin + "/admin").status_code == 200,
                )
                health = client.get(origin + "/health").json()
                check(
                    "public health conceals database path",
                    health["db_path"] == "configured",
                )
                check(
                    "integrations remain disabled",
                    not any(
                        health[k]
                        for k in (
                            "openclaw_enabled",
                            "line_enabled",
                            "telegram_enabled",
                        )
                    ),
                )
                check(
                    "static traversal cannot disclose configuration",
                    client.get(origin + "/static/..%2f.env").status_code == 404,
                )
                check(
                    "disabled LINE webhook refuses input",
                    client.post(origin + "/webhooks/line", json={}).status_code == 503,
                )
                telegram = client.post(origin + "/webhooks/telegram", json={})
                check(
                    "disabled Telegram webhook performs no work",
                    telegram.status_code == 200
                    and telegram.json()
                    == {"ok": False, "disabled": True, "handled": 0, "duplicates": 0},
                )
            return origin

        def same_origin_route(route):
            if (
                origin
                and urlsplit(route.request.url).scheme == "https"
                and urlsplit(route.request.url).netloc == urlsplit(origin).netloc
            ):
                route.continue_()
            else:
                route.abort()

        def launch(self, *values, **options):
            browser = original_launch(self, *values, **options)
            browsers.append(browser)
            if args.browser == "chromium":
                cdp = browser.new_browser_cdp_session()
                pid = next(
                    v["id"]
                    for v in cdp.send("SystemInfo.getProcessInfo")["processInfo"]
                    if v["type"] == "browser"
                )
                actual = subprocess.check_output(
                    ["ps", "-ww", "-p", str(pid), "-o", "command="], text=True
                ).strip()
                if args.executable_path:
                    assert actual.startswith(
                        str(Path(args.executable_path).resolve()) + " "
                    )
                check(
                    "owned native browser uses isolated profile",
                    "--user-data-dir=" in actual,
                )
                check(
                    "native browser visibility matches request",
                    ("--headless" not in actual) == args.headed,
                )
                cleanup["browser_pids_gone"].append(pid)
                record_process(pid, "browser main process")
                (out / "browser-proof.json").write_text(
                    json.dumps(
                        {
                            "pid": pid,
                            "version": browser.version,
                            "headed": args.headed,
                            "executable": args.executable_path,
                        },
                        indent=2,
                    )
                )
            return browser

        def browser_watch(page):
            def response_seen(response):
                if response.status == 401 and not login["accepted"]:
                    login["initial_401"] = True

            page.on("response", response_seen)
            page.on(
                "request",
                lambda r: started_requests.add(r) if login["accepted"] else None,
            )
            page.on(
                "response",
                lambda r: (
                    unauthorized_after_login.append(r.url)
                    if r.status == 401 and r.request in started_requests
                    else None
                ),
            )

        def browser_login(page):
            expect(page.locator("#tokenDialog")).to_be_visible(timeout=20000)
            check("initial real 401 opens token dialog", login["initial_401"])
            try:
                page.locator("#tokenInput").fill(token)
                login["accepted"] = True
                page.locator("#tokenForm button[type=submit]").click()
            except PlaywrightError:
                raise RuntimeError(
                    "Token dialog interaction failed; credential detail omitted"
                ) from None
            expect(page.locator("#tokenDialog")).not_to_be_visible()
            page.wait_for_function("()=>state.preferences!==null&&state.cases.length>0")
            login["preferences_loaded"] = True

        def mark_completed():
            nonlocal journeys_completed
            journeys_completed = True

        @contextmanager
        def public_playwright():
            with sync_playwright() as pw:
                try:
                    yield pw
                finally:
                    # Close the connector and browser before Playwright's event loop exits.
                    finish_public_tests()

        def finish_public_tests():
            nonlocal main_stopped_verified
            try:
                for proc in tunnels:
                    stop_tunnel(proc)
                if origin:
                    check(
                        "main public endpoint unavailable after stop",
                        wait_stopped(origin),
                    )
                    main_stopped_verified = True
                if args.protected_edge and local_origin and journeys_completed:
                    proc, url = start_tunnel(local_origin, protected=True)
                    marker = "/edge-denial-" + uuid4().hex
                    try:
                        with httpx.Client(
                            trust_env=False, timeout=20, follow_redirects=False
                        ) as client:
                            # The official quicktunnelauth handler starts login
                            # via login.trycloudflare.com, before Cloudflare Access.
                            r = client.get(
                                url + marker, headers={"Accept": "text/html"}
                            )
                        location = r.headers.get("location", "")
                        login_host = urlsplit(location).hostname
                        (out / "protected-edge-response.json").write_text(
                            json.dumps(
                                {
                                    "status": r.status_code,
                                    "location": location,
                                    "body_sha256": hashlib.sha256(
                                        r.content
                                    ).hexdigest(),
                                },
                                indent=2,
                            )
                        )
                        is_access_redirect = (
                            r.is_redirect
                            and urlsplit(location).scheme == "https"
                            and login_host
                            and (
                                login_host == "login.trycloudflare.com"
                                or login_host.endswith(".cloudflareaccess.com")
                            )
                        )
                        is_access_denial = (
                            r.status_code in (401, 403)
                            and "cloudflare access" in r.text.lower()
                        )
                        check(
                            "protected edge rejects unique anonymous probe",
                            is_access_redirect or is_access_denial,
                        )
                        check(
                            "origin log captures the unprotected positive control",
                            "GET /api/cases?token=wrong"
                            in (out / "server.log").read_text(),
                        )
                        check(
                            "protected probe never reaches origin",
                            marker not in (out / "server.log").read_text(),
                        )
                        if is_access_redirect:
                            context = browsers[-1].new_context(
                                viewport={"width": 1360, "height": 900}
                            )
                            allowed_hosts = {urlsplit(url).hostname, login_host}

                            def get_only(route):
                                request = route.request
                                if (
                                    request.method == "GET"
                                    and urlsplit(request.url).scheme == "https"
                                    and (
                                        urlsplit(request.url).hostname in allowed_hosts
                                        or (
                                            urlsplit(request.url).hostname or ""
                                        ).endswith(".cloudflareaccess.com")
                                    )
                                ):
                                    route.continue_()
                                else:
                                    route.abort()

                            context.route("**/*", get_only)
                            page = context.new_page()
                            page.goto(url, wait_until="domcontentloaded")
                            expect(page.locator('input[type="email"]')).to_be_visible()
                            page.screenshot(
                                path=str(out / "protected-access-login.png")
                            )
                            check(
                                "real Access email login page shown without submitting OTP",
                                page.locator('input[type="email"]').is_visible()
                                and (
                                    urlsplit(page.url).hostname == login_host
                                    or (urlsplit(page.url).hostname or "").endswith(
                                        ".cloudflareaccess.com"
                                    )
                                ),
                            )
                            context.close()
                    finally:
                        stop_tunnel(proc)
                        check(
                            "protected public endpoint unavailable after stop",
                            wait_stopped(url),
                        )
            finally:
                for proc in tunnels:
                    stop_tunnel(proc)
                for browser in browsers:
                    if browser.is_connected():
                        browser.close()
                browsers.clear()

        def cleanup_server(server):
            try:
                for proc in tunnels:
                    stop_tunnel(proc)
                if origin and not main_stopped_verified:
                    check(
                        "main public endpoint unavailable after early failure",
                        wait_stopped(origin),
                    )
            finally:
                stop_server(server)
                for pid in cleanup["browser_pids_gone"]:
                    check(
                        "owned browser PID is gone",
                        subprocess.run(
                            ["kill", "-0", str(pid)], capture_output=True
                        ).returncode
                        != 0,
                    )
                assert server.poll() is not None
                cleanup["server_pid_gone"] = server.pid
                (out / "cleanup.json").write_text(json.dumps(cleanup, indent=2))

        original = (ROOT / "scripts/verify_agency_assistance.py").read_text()
        adapted = replace_once(
            original, '"APP_ENV": "dev",', '"APP_ENV": "production",'
        )
        adapted = replace_once(
            adapted,
            '"TRAVEL_DESK_ADMIN_TOKEN": "",',
            '"TRAVEL_DESK_ADMIN_TOKEN": TUNNEL_TEST_TOKEN,',
        )
        adapted = replace_once(adapted, "**os.environ,", "**minimal_env(),")
        adapted = replace_once(
            adapted, "server = subprocess.Popen(", "server = spawn_server("
        )
        adapted = replace_once(
            adapted,
            "stderr=log,\n            )",
            "stderr=log,\n                start_new_session=True,\n            )",
        )
        adapted = replace_once(
            adapted,
            "wait_live(base)",
            "wait_live(base)\n                base = public_start(base)",
        )
        adapted = replace_once(
            adapted, "with sync_playwright() as pw:", "with public_playwright() as pw:"
        )
        adapted = replace_once(
            adapted,
            "with httpx.Client(base_url=base, trust_env=False) as api:",
            'with httpx.Client(base_url=base, trust_env=False, timeout=30, headers={"x-travel-desk-admin-token": TUNNEL_TEST_TOKEN}) as api:',
        )
        adapted = replace_once(
            adapted,
            "                    api.patch(",
            "                    assert api.patch(",
        )
        adapted = replace_once(
            adapted,
            'json={"onboarding_complete": True}\n                    )',
            'json={"onboarding_complete": True}\n                    ).status_code == 200',
        )
        adapted = replace_once(
            adapted,
            "                        page.goto(base)",
            "                        browser_watch(page)\n                        page.goto(base)\n                        browser_login(page)",
        )
        adapted = replace_once(
            adapted,
            "                        page = context.new_page()",
            '                        context.route("**/*", same_origin_route)\n                        page = context.new_page()',
        )
        adapted = replace_once(
            adapted,
            '                        check("no JavaScript errors", not errors)',
            '                        check("no JavaScript errors", not errors)\n                        assert login["initial_401"] and login["preferences_loaded"] and not unauthorized_after_login\n                        checks.append("real production-token dialog login over Cloudflare with no later401")',
        )
        adapted = replace_once(
            adapted,
            "                        browser.close()",
            "                        mark_completed()",
        )
        adapted = replace_once(
            adapted,
            "                stop_server(server)",
            "                cleanup_server(server)",
        )
        assert command_checks(original) == command_checks(adapted), (
            "Existing check expressions were changed"
        )
        (out / "adapted_agency_assistance.py").write_text(adapted)
        (out / "runner-adaptation.diff").write_text(
            "".join(
                difflib.unified_diff(
                    original.splitlines(True),
                    adapted.splitlines(True),
                    fromfile="original",
                    tofile="isolated-public-runner",
                )
            )
        )
        old_argv = sys.argv
        old_handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}

        def interrupted(*_):
            for signum in old_handlers:
                signal.signal(signum, signal.SIG_IGN)
            raise KeyboardInterrupt("Acceptance interrupted")

        try:
            for signum in old_handlers:
                signal.signal(signum, interrupted)
            BrowserType.launch = launch
            expect.set_options(timeout=15000)
            sys.argv = [
                "verify_agency_assistance.py",
                "--browser",
                args.browser,
                "--out",
                str(out),
            ]
            if args.headed:
                sys.argv.append("--headed")
            if args.executable_path:
                sys.argv += ["--executable-path", args.executable_path]
            exec(
                compile(adapted, str(out / "adapted_agency_assistance.py"), "exec"),
                {
                    "__name__": "__main__",
                    "TUNNEL_TEST_TOKEN": token,
                    "minimal_env": minimal_env,
                    "spawn_server": spawn_server,
                    "public_start": public_start,
                    "browser_login": browser_login,
                    "browser_watch": browser_watch,
                    "public_playwright": public_playwright,
                    "mark_completed": mark_completed,
                    "same_origin_route": same_origin_route,
                    "cleanup_server": cleanup_server,
                    "login": login,
                    "unauthorized_after_login": unauthorized_after_login,
                },
            )
        finally:
            BrowserType.launch = original_launch
            sys.argv = old_argv
            try:
                for proc in tunnels:
                    stop_tunnel(proc)
                for browser in browsers:
                    if browser.is_connected():
                        browser.close()
            finally:
                for signum, handler in old_handlers.items():
                    signal.signal(signum, handler)
        assert source_manifest() == sources
        assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == harness_sha
        assert len(json.loads((out / "results.json").read_text())["checks"]) == 49
        (out / "tunnel-results.json").write_text(
            json.dumps(
                {
                    "checks": probes,
                    "public_url": origin,
                    "auth_mode": "production token",
                    "browser_journeys": 49,
                    "cloudflared_sha256": args.expected_sha256,
                    "adapted_runner_sha256": hashlib.sha256(
                        adapted.encode()
                    ).hexdigest(),
                    "harness_sha256": harness_sha,
                    "git_head": git_head,
                    "uncommitted_diff_sha256": diff_sha,
                    "original_checks_unchanged": True,
                    "source_sha256": sources,
                    "limits": [
                        "No named Tunnel or real Access/OTP/MFA/user-role acceptance",
                        "Synthetic data only; no outbound notifications",
                        "Test token is visible to Cloudflare TLS termination",
                        "Same-origin fence covers page traffic, not browser background services",
                        "Browser cleanup checks the main PID, not all helper/crash-reporter processes",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    print(
        "PASS:49 browser journeys over real Cloudflare HTTPS; public probes and cleanup verified"
    )


if __name__ == "__main__":
    main()
