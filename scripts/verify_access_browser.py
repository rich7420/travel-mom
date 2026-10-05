"""Synthetic HTTPS signed-auth E2E, not Cloudflare edge/IdP/Tunnel/MFA validation.

Playwright headers stand in for the edge. Real app middleware, RSA verification,
Origin guards and login recovery run against an isolated database. No app test hook.
"""
from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from cryptography import x509
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import httpx
import jwt
from playwright.sync_api import expect, sync_playwright

from browser_test_support import free_port, source_manifest, stop_server, wait_live

ROOT = Path(__file__).resolve().parents[1]
ISSUER = 'https://e2e.cloudflareaccess.com'
AUDIENCE = 'synthetic-travel-desk'
MOM = 'mom@example.test'
ADMIN = 'admin@example.test'


def serve(args):
    # Only a disposable test subprocess may seed synthetic public keys. No verify
    # method is replaced and the production application contains no bypass.
    if os.environ.get('APP_ENV') != 'dev' or os.environ.get('CLOUDFLARE_ACCESS_ISSUER') != ISSUER:
        raise RuntimeError('Synthetic runner requires APP_ENV=dev and its fixed test issuer')
    sys.path.insert(0, str(ROOT))
    from app.main import app
    import uvicorn
    original = app.router.lifespan_context

    @asynccontextmanager
    async def test_lifespan(application):
        async with original(application):
            verifier = application.state.access_verifier
            key = jwt.PyJWK.from_dict(json.loads(Path(args.jwk).read_text()), algorithm='RS256')
            verifier.keys = {'synthetic-key': key}
            # Freeze only cache time, not JWT wall time: tests must never refresh
            # the synthetic Cloudflare domain, even on a slow browser/unknown kid.
            verifier.clock = lambda: 0.0
            verifier.refreshed_at = verifier.attempted_at = 0.0
            yield

    app.router.lifespan_context = test_lifespan
    redirect_state = Path(args.jwk).parent / 'edge-redirect-path'

    async def synthetic_edge(scope, receive, send):
        # Real HTTP redirects work in all engines (WebKit cannot route.fulfill 302).
        # This wrapper simulates only edge login routing; all normal traffic uses app.
        try:
            redirect_path = redirect_state.read_text()
        except FileNotFoundError:
            redirect_path = ''
        if (scope['type'] == 'http' and scope['method'] == 'GET'
                and scope['path'] == redirect_path
                and redirect_path in {'/api/auth/session', '/api/system/backup-status'}):
            await send({'type': 'http.response.start', 'status': 302,
                        'headers': [(b'location', (ISSUER + '/cdn-cgi/access/login').encode())]})
            await send({'type': 'http.response.body', 'body': b''})
            return
        await app(scope, receive, send)

    uvicorn.run(synthetic_edge, host='127.0.0.1', port=args.port,
                ssl_certfile=args.cert, ssl_keyfile=args.key)


def certificate(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([
                x509.DNSName('localhost'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            .sign(key, hashes.SHA256()))
    key_path = root / 'tls.key'
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    key_path.chmod(0o600)
    cert_path = root / 'tls.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', choices=('chromium', 'firefox', 'webkit'), default='chromium')
    parser.add_argument('--output', default='data/completion-review/access-browser')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    for name in ('cert', 'key', 'jwk'):
        parser.add_argument('--' + name, help=argparse.SUPPRESS)
    parser.add_argument('--port', type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        serve(args)
        return
    sources = source_manifest()
    started_at = datetime.now(timezone.utc).isoformat()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []

    def check(label, condition=True):
        assert condition, label
        checks.append(label)

    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def token(email=MOM, *, expired=False, key=signing_key):
        now = int(time.time())
        return jwt.encode({'iss': ISSUER, 'aud': AUDIENCE, 'sub': email, 'email': email,
                           'type': 'app', 'iat': now - 300, 'exp': now - 120 if expired else now + 1800},
                          key, algorithm='RS256', headers={'kid': 'synthetic-key'})

    def headers(value):
        return {'Cf-Access-Jwt-Assertion': value}

    with tempfile.TemporaryDirectory(prefix='mom-access-browser-') as temp:
        root = Path(temp)
        base = f'https://localhost:{free_port()}'
        cert, key = certificate(root)
        jwk = root / 'public-jwk.json'
        jwk.write_text(jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key()))
        env = {**os.environ, 'TRAVEL_DESK_DB': str(root / 'desk.db'), 'APP_ENV': 'dev',
               'AUTH_MODE': 'cloudflare', 'PUBLIC_BASE_URL': base, 'CLOUDFLARE_ACCESS_ISSUER': ISSUER,
               'CLOUDFLARE_ACCESS_AUDIENCE': AUDIENCE, 'CLOUDFLARE_ACCESS_EMAILS': MOM,
               'CLOUDFLARE_ACCESS_ADMIN_EMAILS': ADMIN, 'TRAVEL_DESK_ADMIN_TOKEN': 'synthetic-legacy',
               'PII_FERNET_KEY': Fernet.generate_key().decode(), 'ATTACHMENTS_DIR': str(root / 'files'),
               'BACKUP_DIR': str(root / 'backups'), 'OPENCLAW_ENABLED': 'false',
               'LINE_ENABLED': 'false', 'TELEGRAM_ENABLED': 'false',
               'HTTPS_PROXY': 'http://127.0.0.1:9', 'ALL_PROXY': 'http://127.0.0.1:9',
               'NO_PROXY': 'localhost,127.0.0.1'}
        with (out / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve',
                                       '--port', base.rsplit(':', 1)[1], '--cert', str(cert),
                                       '--key', str(key), '--jwk', str(jwk)], cwd=ROOT, env=env,
                                      stdout=log, stderr=log)
            try:
                wait_live(base, verify=False)
                mom_token, admin_token = token(), token(ADMIN)
                with httpx.Client(base_url=base, verify=False, trust_env=False,
                                  headers={**headers(mom_token), 'Origin': base}, timeout=5) as api:
                    check('HTTPS rejects unsigned and legacy-token access',
                          httpx.get(base + '/api/cases', verify=False, trust_env=False,
                                    headers={'X-Travel-Desk-Admin-Token': 'synthetic-legacy'}).status_code == 401)
                    forged = token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048))
                    check('HTTPS rejects forged signature', api.get('/api/cases', headers=headers(forged)).status_code == 401)
                    check('HTTPS rejects unlisted signed identity', api.get('/api/cases', headers=headers(token('stranger@example.test'))).status_code == 403)
                    response = api.patch('/api/mom/preferences', json={'onboarding_complete': True})
                    assert response.status_code == 200, response.text
                    case = api.post('/api/cases', json={'customer_name': '合成簽章登入', 'destination': '東京'}).json()
                    c = case['id']
                    path = f'/api/mom/cases/{c}'
                    traveller = api.post(path + '/travellers', json={
                        'request_id': str(uuid4()), 'name': '合成登入私密姓名', 'category': 'adult',
                        'date_of_birth': '1990-01-01', 'passport_number': 'SIGNED-SYNTHETIC-PASSPORT',
                        'passport_expiry': '2030-01-01', 'nationality': 'TW'}).json()
                    check('operator cannot read admin backup status', api.get('/api/system/backup-status').status_code == 403)
                    with sync_playwright() as pw:
                        browser = getattr(pw, args.browser).launch()
                        context = browser.new_context(ignore_https_errors=True, extra_http_headers=headers(mom_token), locale='zh-TW')
                        page = context.new_page()
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(base)
                        page.wait_for_function('()=>state.preferences!==null&&state.cases.length===1')
                        check('Mom identity displayed and admin entry hidden',
                              page.locator('#headerIdentity').inner_text() == MOM and not page.locator('#adminTools').is_visible())
                        guide = context.new_page()
                        guide.goto(base + '/static/guide.html#pretrip')
                        check('signed Mom can read embedded guide', guide.locator('#pretrip').count() == 1)
                        guide.close()

                        def reveal():
                            page.evaluate('(id)=>MomApp.openCase(id)', c)
                            page.locator('#sheetBody [data-module=pretrip]').click()
                            page.locator('[data-action=files-open]').click()
                            page.locator('[data-action=files-reveal]').click()
                            expect(page.locator('[data-private]')).to_contain_text('SIGNED-SYNTHETIC-PASSPORT')

                        reveal()
                        resume_marker = page.evaluate('()=>window.e2eResumeMarker=crypto.randomUUID()')
                        context.set_extra_http_headers(headers(token(expired=True)))
                        result = page.evaluate("async()=>{try{await MomApp.api('/api/auth/session');return 'unexpected';}catch(e){return e.name;}}")
                        expect(page.locator('#loginDialog')).to_be_visible()
                        check('real expired JWT clears private DOM and opens login', result == 'ReauthenticationError' and 'SIGNED-SYNTHETIC-PASSPORT' not in page.locator('#sheetBody').inner_text())
                        context.set_extra_http_headers(headers(mom_token))
                        page.locator('#loginDialog [data-action=login]').click()
                        expect(page.locator('#loginDialog')).not_to_be_visible()
                        page.locator('#sheet [data-action=close-sheet]').click()
                        reveal()
                        check('fresh signed identity resumes without page reload', page.evaluate('()=>window.e2eResumeMarker') == resume_marker)
                        (root / 'edge-redirect-path').write_text('/api/auth/session')
                        result = page.evaluate("async()=>{try{await MomApp.api('/api/auth/session');return 'unexpected';}catch(e){return e.name;}}")
                        expect(page.locator('#loginDialog')).to_be_visible()
                        check('simulated edge redirect clears private DOM and opens login', result == 'ReauthenticationError' and 'SIGNED-SYNTHETIC-PASSPORT' not in page.locator('#sheetBody').inner_text())
                        (root / 'edge-redirect-path').unlink()
                        page.locator('#loginDialog [data-action=login]').click()
                        expect(page.locator('#loginDialog')).not_to_be_visible()
                        check('edge-redirect recovery resumes same case', page.evaluate('()=>document.querySelector("#sheet").open'))
                        # Expire during a real binary POST: input is scrubbed, UUID survives,
                        # and a fresh identity retries exactly that uncommitted intent.
                        doc = api.post(path + '/documents', json={'request_id': str(uuid4()), 'kind': 'other', 'title': '合成登入上傳', 'required': False}).json()
                        page.locator('#sheet [data-action=close-sheet]').click()
                        page.evaluate('(id)=>MomApp.openCase(id)', c)
                        page.locator('#sheetBody [data-module=pretrip]').click()
                        page.locator('[data-action=files-open]').click()
                        page.locator('[data-intent=upload]').click()
                        form = page.locator('#travelFileForm')
                        file = {'name': 'private-expiry-name.pdf', 'mimeType': 'application/pdf', 'buffer': b'%PDF-1.4\nsynthetic expiry original'}
                        form.locator('[name=file]').set_input_files(file)
                        upload_requests = []
                        page.on('request', lambda request: upload_requests.append(request.url) if request.method == 'POST' and '/attachments?' in request.url else None)
                        context.set_extra_http_headers(headers(token(expired=True)))
                        form.locator('button[type=submit]').click()
                        expect(page.locator('#loginDialog')).to_be_visible()
                        check('expired upload removes selected file from private DOM', form.locator('[name=file]').count() == 0 and not api.get(path + '/travel-files').json()['attachments'])
                        pending = page.evaluate('(id)=>sessionStorage.getItem("travel-upload-intents:"+id)', c)
                        check('expired upload retains non-sensitive retry UUID only', len(json.loads(pending)) == 1 and 'private-expiry-name' not in pending and 'synthetic expiry original' not in pending)
                        context.set_extra_http_headers(headers(mom_token))
                        page.locator('#loginDialog [data-action=login]').click()
                        expect(page.locator('#loginDialog')).not_to_be_visible()
                        page.evaluate('(id)=>MomApp.openCase(id)', c)
                        page.locator('#sheetBody [data-module=pretrip]').click()
                        page.locator('[data-action=files-open]').click()
                        expect(page.locator('#sheetBody')).to_contain_text('上次上傳尚未查到已保存紀錄')
                        page.locator('[data-intent=upload]').click()
                        page.locator('#travelFileForm [name=file]').set_input_files(file)
                        page.locator('#travelFileForm button[type=submit]').click()
                        expect(page.locator('[data-action=files-download]')).to_be_visible()
                        check('fresh login resumes uncommitted upload with identical UUID', len(upload_requests) == 2 and upload_requests[0] == upload_requests[1] and len(api.get(path + '/travel-files').json()['attachments']) == 1)
                        check('successful resumed upload clears its receipt', page.evaluate('(id)=>sessionStorage.getItem("travel-upload-intents:"+id)===null', c))
                        with page.expect_download() as event:
                            page.locator('[data-action=files-download]').click()
                        check('signed operator can download private original', event.value.failure() is None)
                        denied = context.new_page()
                        check('Mom admin-page navigation receives 403', denied.goto(base + '/admin').status == 403)
                        denied.close()
                        before = len(api.get('/api/cases').json())
                        attacker = context.new_page()
                        attacker.route('https://attacker.test/**', lambda route: route.fulfill(
                            content_type='text/html', body=f'<form method="post" action="{base}/api/cases"><input name="customer_name" value="attacker"><button>Submit</button></form>'))
                        attacker.goto('https://attacker.test/')
                        with attacker.expect_response(lambda r: r.url == base + '/api/cases') as response:
                            attacker.get_by_role('button', name='Submit').click()
                        check('browser-generated cross-site Origin reaches app and gets 403', response.value.status == 403 and response.value.json().get('detail') == 'request origin not allowed')
                        check('Origin rejection leaves case count unchanged', len(api.get('/api/cases').json()) == before)
                        attacker.close()
                        # Real signed identities share a tab while uncertain service writes
                        # retain metadata. Neither account may replay the other's UUID.
                        page.on('dialog', lambda dialog: dialog.accept())
                        def service_orders():
                            page.evaluate('(id)=>MomApp.openCase(id)', c)
                            page.locator('#sheetBody [data-module=tasks]').click()
                            page.locator('[data-action=service-open]').click()
                            expect(page.locator('#sheetBody > h3')).to_have_text('改退與旅中工作單')

                        def service_form(intent):
                            target=page.locator(f'#sheetBody [data-intent="{intent}"]')
                            target.evaluate('(el)=>{if(el.closest("details"))el.closest("details").open=true;}')
                            target.click()
                            expect(page.locator('#serviceOrderForm')).to_be_visible()
                            return page.locator('#serviceOrderForm')

                        def service_proof(form):
                            form.locator('[name=reference]').fill('合成身分核對')
                            form.locator('[name=checked]').check()

                        service_orders(); form=service_form('create')
                        form.locator('[name=title]').fill('媽媽帳號待確認工作單')
                        form.locator('[name=request_details]').fill('合成需求')
                        service_proof(form)
                        page.evaluate("""()=>{window.originalFetch=fetch;window.fetch=async(url,opts)=>{const r=await originalFetch(url,opts);if(String(url).endsWith('/service-orders')&&opts?.method==='POST')throw new TypeError('synthetic committed response lost');return r;};}""")
                        form.locator('button[type=submit]').click()
                        expect(form.locator('[data-action=service-reconcile]')).to_be_visible()
                        metadata=page.evaluate('(id)=>JSON.parse(sessionStorage.getItem("travel-service-intents:"+id))',c)
                        order=api.get(path+'/operations').json()['service_orders'][0]
                        check('uncertain service write retains verified actor metadata only',len(metadata)==1 and metadata[0]['actor']==MOM and '合成身分核對' not in json.dumps(metadata))
                        context.set_extra_http_headers(headers(admin_token));page.reload()
                        page.wait_for_function('(email)=>state.auth?.email===email&&state.preferences!==null',arg=ADMIN)
                        service_orders()
                        expect(page.locator('#sheetBody')).to_contain_text('其他登入身分的待確認操作')
                        check('new signed actor reads orders without replaying foreign intent',len(api.get(path+'/operations').json()['service_orders'])==1 and page.evaluate('(id)=>JSON.parse(sessionStorage.getItem("travel-service-intents:"+id))[0].actor',c)==MOM)
                        form=service_form('create');form.locator('[name=title]').fill('管理員獨立工作單');form.locator('[name=request_details]').fill('另一筆合成需求');service_proof(form);form.locator('button[type=submit]').click()
                        expect(page.locator('#serviceOrderForm')).to_have_count(0)
                        check('successful new-actor write preserves original uncertain metadata',len(api.get(path+'/operations').json()['service_orders'])==2 and len(page.evaluate('(id)=>JSON.parse(sessionStorage.getItem("travel-service-intents:"+id))',c))==1)
                        # Exercise legacy metadata with no actor against the real 409 guard.
                        page.evaluate('(id)=>{const key="travel-service-intents:"+id;const items=JSON.parse(sessionStorage.getItem(key));delete items[0].actor;sessionStorage.setItem(key,JSON.stringify(items));}',c)
                        check('backend still denies another actor receipt',api.get(path+'/service-order-receipts/'+metadata[0]['request_id'],headers=headers(admin_token)).status_code==409)
                        service_orders();expect(page.locator('#sheetBody')).to_contain_text('其他登入身分的待確認操作')
                        check('legacy wrong-actor receipt does not block list and remains stored',page.evaluate('(id)=>JSON.parse(sessionStorage.getItem("travel-service-intents:"+id))[0].unavailable_for',c)==ADMIN and page.locator('#sheetBody [data-action=service-detail]').count()==2)
                        service_orders();check('reopening list stays usable after foreign legacy receipt',page.locator('#sheetBody [data-action=service-detail]').count()==2)
                        context.set_extra_http_headers(headers(mom_token));page.reload()
                        page.wait_for_function('(email)=>state.auth?.email===email&&state.preferences!==null',arg=MOM)
                        service_orders()
                        check('original signed actor reconciles legacy receipt without duplicate write',page.evaluate('(id)=>sessionStorage.getItem("travel-service-intents:"+id)===null',c) and len(api.get(path+'/operations').json()['service_orders'])==2)
                        page.locator(f'#sheetBody [data-action=service-detail][data-id="{order["id"]}"]').click();form=service_form('note');form.locator('[name=message]').fill('原登入填寫的內容');service_proof(form)
                        context.set_extra_http_headers(headers(admin_token));page.evaluate('()=>loadSession()')
                        history_before=api.get(path+'/operations').json()['service_orders'][0]['history']
                        form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_contain_text('操作帳號已變更')
                        check('account change during form blocks submission and preserves typed content',form.locator('[name=message]').input_value()=='原登入填寫的內容' and api.get(path+'/operations').json()['service_orders'][0]['history']==history_before)
                        admin_context = browser.new_context(ignore_https_errors=True, extra_http_headers=headers(admin_token))
                        admin = admin_context.new_page()
                        admin.on('pageerror', lambda e: errors.append(str(e)))
                        admin.goto(base + '/admin')
                        admin.wait_for_function("()=>authMode==='cloudflare'")
                        admin.get_by_role('button', name='備份狀態', exact=True).click()
                        expect(admin.locator('#modalBody')).to_contain_text('尚無紀錄')
                        check('signed admin sees observed backup status')
                        admin_context.set_extra_http_headers(headers(token(ADMIN, expired=True)))
                        result = admin.evaluate("async()=>{try{await api('/api/system/backup-status');return 'unexpected';}catch(e){return e.name;}}")
                        expect(admin.locator('#adminLoginDialog')).to_be_visible()
                        check('admin real expiry opens dedicated login', result == 'ReauthenticationError')
                        admin_context.set_extra_http_headers(headers(admin_token))
                        admin.locator('#adminRelogin').click()
                        expect(admin.locator('#adminLoginDialog')).not_to_be_visible()
                        admin.wait_for_function("()=>authMode==='cloudflare'")
                        (root / 'edge-redirect-path').write_text('/api/system/backup-status')
                        result = admin.evaluate("async()=>{try{await api('/api/system/backup-status');return 'unexpected';}catch(e){return e.name;}}")
                        expect(admin.locator('#adminLoginDialog')).to_be_visible()
                        check('admin simulated edge redirect opens dedicated login', result == 'ReauthenticationError')
                        browser.close()
                    with sqlite3.connect(root / 'desk.db') as db:
                        actors = db.execute("SELECT actor,payload_json FROM audit_log WHERE action='agency.traveller.reveal'").fetchall()
                        check('private reads audit verified identity without passport contents', len(actors) >= 2 and all(actor == MOM and 'SIGNED-SYNTHETIC-PASSPORT' not in payload for actor, payload in actors))
                    check('no JavaScript errors', not errors)
            finally:
                stop_server(server)
        check('key verification made no remote refresh attempt', 'Access signing keys unavailable' not in (out / 'server.log').read_text())
    assert not root.exists(), 'Disposable identity database and keys not removed'
    assert source_manifest() == sources, 'Application or runner changed during verification'
    (out / 'results.json').write_text(json.dumps({
        'browser': args.browser, 'checks': checks, 'javascript_errors': errors,
        'started_at': started_at, 'source_sha256': sources,
        'scope': 'Browser-injected JWT stands in for Cloudflare edge; no real IdP, cookies, Tunnel or MFA.'}, ensure_ascii=False, indent=2))
    print(f'{len(checks)} signed-auth browser checks passed')


if __name__ == '__main__':
    main()
