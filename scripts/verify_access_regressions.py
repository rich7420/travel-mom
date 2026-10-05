"""Prove the HTTPS security E2E detects Origin/cache regressions in disposable copies.

Never edits the working application. Requires the same Playwright Chromium setup
as verify_access_browser.py; outputs contain only synthetic data.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='data/completion-review/access-negative-controls')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    for name in ('origin', 'cache'):
        with tempfile.TemporaryDirectory(prefix='mom-negative-control-') as temp:
            lab = Path(temp)
            shutil.copytree(root / 'app', lab / 'app', ignore=shutil.ignore_patterns('__pycache__'))
            (lab / 'scripts').mkdir()
            for filename in ('verify_access_browser.py', 'browser_test_support.py'):
                shutil.copy2(root / 'scripts' / filename, lab / 'scripts' / filename)
            if name == 'origin':
                path = lab / 'app' / 'security.py'
                source = path.read_text()
                start = source.index('def verify_access_origin(')
                end = source.index('\n_BASE=', start)
                path.write_text(source[:start] + 'def verify_access_origin(request):\n    pass\n' + source[end:])
                expected = 'browser-generated cross-site Origin reaches app and gets 403'
            else:
                path = lab / 'scripts' / 'verify_access_browser.py'
                source = path.read_text().replace("verifier.keys = {'synthetic-key': key}", 'verifier.keys = {}')
                source = source.replace('verifier.refreshed_at = verifier.attempted_at = 0.0',
                                        "verifier.refreshed_at = verifier.attempted_at = float('-inf')")
                path.write_text(source)
                expected = 'HTTPS rejects forged signature'
            started = time.monotonic()
            run = subprocess.run([sys.executable, str(lab / 'scripts' / 'verify_access_browser.py'),
                                  '--output', str(output / name)], cwd=lab,
                                 capture_output=True, text=True, timeout=90)
            (output / (name + '.log')).write_text(run.stdout + run.stderr)
            assert run.returncode != 0 and expected in run.stderr, (name, run.returncode, run.stderr)
            elapsed = time.monotonic() - started
            if name == 'cache':
                assert elapsed < 15, 'Unseeded cache did not fail fast'
                assert 'Access signing keys unavailable' in (output / name / 'server.log').read_text()
            checks.append({'control': name, 'detected_assertion': expected, 'elapsed_seconds': round(elapsed, 2)})
        assert not lab.exists(), 'Disposable application copy not removed'
        print(f'{name}: expected regression detected and disposable copy removed')
    (output / 'results.json').write_text(json.dumps({'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
