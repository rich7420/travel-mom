"""Prove service E2E assertions detect specific frontend regressions in copies.

Runs unmodified auth/order baselines before four independent negative controls.
Never modifies the working application or uses the live database. Requires the
same Python/Playwright/browser installation as verify_access_browser.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise AssertionError(f'Negative-control target changed: {old!r}')
    return source.replace(old, new, 1)


def mutate(source, control):
    if control == 'actor-await':
        # Keep the initial form check so failure must reach the awaited receipt.
        source = replace_once(source, '    assertActor(actor);\n    return result;', '    return result;')
        source = replace_once(source, '    assertActor(op.actor);\n    retain(op.c,', '    retain(op.c,')
        source = replace_once(source, '      assertActor(op.actor);\n    } catch (err)', '    } catch (err)')
        return replace_once(source, '          headers: actorHeaders(op.actor),\n', '')
    if control == 'owner-recovery':
        return replace_once(source, 'for (const item of storedIntents(c))', 'for (const item of pending(c))')
    if control == 'conflict-discard':
        return replace_once(source, '      try {\n        // A 4xx can describe', '''      if (err.status === 409) {
        forget(op.c, request);
        op.request = null;
        op.frozenPayload = null;
        throw err;
      }
      try {
        // A 4xx can describe''')
    if control == 'contact-snapshot':
        return replace_once(source, '    // The sent snapshot stays immutable in memory until receipt reconciliation.', '''    if (f?.serviceOperation.frozenPayload?.contact)
      f.serviceOperation.frozenPayload.contact = "";''')
    raise ValueError(control)


def failure_target(source, anchor, assertion, diagnostic):
    """Locate the exact expectation; its preceding named check may never run."""
    if source.count(anchor) != 1:
        raise AssertionError('Expected failure scenario changed: ' + anchor)
    start = source.index(anchor)
    position = source.index(assertion, start)
    return source.count('\n', 0, position) + 1, diagnostic


def source_hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for directory in ('app', 'scripts') for path in sorted((root / directory).rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts}


def run_browser(lab, runner, browser, output, log_path, *, timeout=180):
    with log_path.open('w') as log:
        process = subprocess.Popen([sys.executable, str(lab / 'scripts' / runner),
                                    '--browser', browser, '--output', str(output)],
                                   cwd=lab, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        finally:
            # Kill only this disposable runner's process group, including any
            # uvicorn child left by timeout/error. A timeout is never a detection.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            # The parent can exit while a child ignores TERM. Do not leave that
            # child serving a disposable database after removing its directory.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'firefox', 'webkit'), default='chromium')
    parser.add_argument('--output', default='data/e2e-review/service-negative-controls')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    before = source_hashes(root)
    baselines, controls = [], []
    scenarios = (
        ('baseline-auth', 'verify_access_browser.py', None),
        ('baseline-orders', 'verify_service_orders.py', None),
        ('actor-await', 'verify_access_browser.py', (
            "page.route('**/service-order-receipts/'+pending_id,switch_during_receipt)",
            "form.locator('button[type=submit]').click();expect(form.locator('.form-error'))",
            "AssertionError: Locator expected to contain text '操作帳號已變更'")),
        ('owner-recovery', 'verify_access_browser.py', (
            "check('actual saved actor recovers historically mislabeled and quarantined intent without replay'",
            "check('actual saved actor recovers historically mislabeled and quarantined intent without replay'",
            'AssertionError: actual saved actor recovers historically mislabeled and quarantined intent without replay')),
        ('conflict-discard', 'verify_access_browser.py', (
            "page.route('**/service-order-receipts/'+shared_id,commit_between_receipt_and_post)",
            "form.locator('button[type=submit]').click();expect(page.locator('#serviceOrderForm')).to_have_count(0)",
            "AssertionError: Locator expected to have count '0'")),
        ('contact-snapshot', 'verify_service_orders.py', (
            "check('expiry redacts visible contact without changing sent frozen snapshot'",
            "check('expiry redacts visible contact without changing sent frozen snapshot'",
            'AssertionError: expiry redacts visible contact without changing sent frozen snapshot')),
    )
    try:
        for name, runner, target in scenarios:
            with tempfile.TemporaryDirectory(prefix='mom-service-negative-') as temp:
                lab = Path(temp)
                for directory in ('app', 'scripts'):
                    shutil.copytree(root / directory, lab / directory,
                                    ignore=shutil.ignore_patterns('__pycache__'))
                expected = failure_target((lab / 'scripts' / runner).read_text(), *target) if target else None
                if target:
                    path = lab / 'app' / 'mom_static' / 'service-orders.js'
                    path.write_text(mutate(path.read_text(), name))
                started = time.monotonic()
                log_path = output / (name + '.log')
                code = run_browser(lab, runner, args.browser, output / name, log_path)
                log = log_path.read_text()
                result = {'control': name, 'exit_code': code,
                          'elapsed_seconds': round(time.monotonic() - started, 2)}
                if target:
                    line, diagnostic = expected
                    frame = f'File "{lab / "scripts" / runner}", line {line}, in main'
                    assert code == 1 and frame in log and diagnostic in log, (name, code, log[-4000:])
                    result.update(assertion_line=line, detected_assertion=diagnostic)
                    controls.append(result)
                else:
                    assert code == 0, (name, code, log[-4000:])
                    baselines.append(result)
            assert not lab.exists(), 'Disposable application copy not removed'
            print(f'{args.browser} {name}: expected result verified; copy removed', flush=True)
    finally:
        assert source_hashes(root) == before, 'Working application or runners changed'
    (output / 'results.json').write_text(json.dumps({
        'browser': args.browser, 'baselines': baselines, 'negative_controls': controls,
        'source_sha256': before, 'working_sources_unchanged': True,
        'scope': 'Disposable frontend mutants; synthetic JWT edge, not real Cloudflare/IdP.'}, indent=2))


if __name__ == '__main__':
    main()
