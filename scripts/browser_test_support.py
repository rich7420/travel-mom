"""Small lifecycle helpers for disposable browser-test servers."""
import socket
import subprocess
import time

import httpx


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def wait_live(base, *, verify=True):
    with httpx.Client(verify=verify, trust_env=False, timeout=.5) as api:
        for _ in range(100):
            try:
                if api.get(base + '/livez').status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.1)
    raise RuntimeError('Disposable server did not start; inspect server.log')


def stop_server(server):
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()


def source_manifest():
    """Tie browser evidence to the exact app and runner sources, excluding bytecode."""
    import hashlib
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    files = [path for path in (root / 'app').rglob('*')
             if path.is_file() and '__pycache__' not in path.parts]
    files += [root / 'scripts' / name for name in
              ('browser_test_support.py', 'verify_travel_files.py', 'verify_access_browser.py', 'verify_service_orders.py', 'verify_agency_assistance.py')
              if (root / 'scripts' / name).exists()]
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(files)}
