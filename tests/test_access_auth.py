from dataclasses import replace
from datetime import datetime, timezone
import json

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.cloudflare_access import AccessVerifier
from app.config import settings
from app.main import app


@pytest.fixture(scope='module')
def signing_keys():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    jwk.update(kid='test-key', alg='RS256')
    return private, jwk


def config(**changes):
    return replace(settings, auth_mode='cloudflare', public_base_url='https://travel.example.com',
                   cloudflare_access_issuer='https://family.cloudflareaccess.com',
                   cloudflare_access_audience='travel-audience', cloudflare_access_emails=('Mom@Example.com',),
                   cloudflare_access_admin_emails=('Admin@Example.com',), admin_token='legacy-secret', **changes)


def token(private, **changes):
    now = int(datetime.now(timezone.utc).timestamp())
    claims = dict(iss='https://family.cloudflareaccess.com', aud=['travel-audience'], exp=now+600,
                  iat=now, sub='test-user', email='mom@example.com', type='app')
    claims.update(changes)
    return jwt.encode(claims, private, algorithm='RS256', headers={'kid':'test-key'})


@pytest.fixture
def access_client(monkeypatch, signing_keys):
    import app.main as main
    import app.security as security
    secured = config()
    monkeypatch.setattr(main, 'settings', secured)
    monkeypatch.setattr(security, 'settings', secured)
    with TestClient(app) as client:
        verifier = app.state.access_verifier
        verifier.keys = {'test-key': jwt.PyJWK.from_dict(signing_keys[1])}
        verifier.refreshed_at = verifier.attempted_at = verifier.clock()
        yield client


def headers(private, **claims):
    return {'Cf-Access-Jwt-Assertion':token(private, **claims), 'Origin':'https://travel.example.com'}


@pytest.mark.parametrize('path', ['/', '/static/app.js', '/static/guide.html', '/static/guide.css', '/static/guide.js', '/admin', '/admin-static/app.js', '/health',
                                   '/docs', '/redoc', '/openapi.json', '/api/cases', '/unknown-route',
                                   '/webhooks/line', '/webhooks/line/'])
def test_access_defaults_to_protected_including_unknown_paths(access_client, path):
    response = access_client.get(path, headers={'X-Travel-Desk-Admin-Token':'legacy-secret',
                                                'Cf-Access-Authenticated-User-Email':'mom@example.com'})
    assert response.status_code == 401
    assert response.json()['auth_mode'] == 'cloudflare'
    assert response.headers['cache-control'] == 'no-store'


def test_liveness_and_exact_signed_channel_exemptions(access_client):
    assert access_client.get('/livez').json() == {'ok':True}
    assert access_client.post('/webhooks/line',json={'events':[]}).status_code == 503
    assert access_client.post('/webhooks/telegram',json={'update_id':99}).json()['disabled'] is True
    assert access_client.post('/webhooks/line/',json={'events':[]}).status_code == 401


def test_roles_and_session_do_not_expose_tokens_or_config(access_client, signing_keys):
    private = signing_keys[0]
    mom = headers(private,email='MOM@EXAMPLE.COM')
    session = access_client.get('/api/auth/session',headers=mom).json()
    assert session == {'mode':'cloudflare','email':'mom@example.com','role':'operator','logout_url':'/cdn-cgi/access/logout'}
    assert access_client.get('/api/cases',headers=mom).status_code == 200
    assert access_client.get('/health',headers=mom).status_code == 200
    assert access_client.get('/static/app.js',headers=mom).status_code == 200
    for asset in ['guide.html', 'guide.css', 'guide.js']:
        response = access_client.get(f'/static/{asset}', headers=mom)
        assert response.status_code == 200
        assert "'unsafe-inline'" not in response.headers['content-security-policy']
    for path in ['/admin','/admin-static/app.js','/api/system/readiness','/api/browser/tasks','/api/browser/lab/summary','/api/approvals','/api/hotels/site-grants','/api/mom/skill-feedback/summary','/api/unknown']:
        assert access_client.get(path,headers=mom).status_code == 403
    assert access_client.post('/api/browser/tasks',headers=mom,json={}).status_code == 403
    admin = headers(private,email='admin@example.com')
    assert access_client.get('/admin',headers=admin).status_code == 200
    assert access_client.get('/api/system/readiness',headers=admin).status_code == 200
    assert access_client.get('/api/cases',headers=admin).status_code == 200
    assert access_client.get('/api/cases',headers=headers(private,email='stranger@example.com')).status_code == 403


@pytest.mark.parametrize('claim,value', [('iss','https://attacker.cloudflareaccess.com'),('aud',['other-app']),
                                        ('exp',1),('nbf',9999999999),('email',''),('type','org')])
def test_invalid_claims_are_rejected(access_client, signing_keys, claim, value):
    response = access_client.get('/api/cases',headers=headers(signing_keys[0],**{claim:value}))
    assert response.status_code == 401 and response.json()['detail'] == 'login required'


def test_missing_email_and_forged_signatures_are_rejected(access_client,signing_keys):
    private = signing_keys[0]
    claims = jwt.decode(token(private),options={'verify_signature':False})
    claims.pop('email')
    missing = jwt.encode(claims,private,algorithm='RS256',headers={'kid':'test-key'})
    forged_key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    for invalid in [missing,token(forged_key),jwt.encode(claims,'irrelevant-long-test-secret-value',algorithm='HS256',headers={'kid':'test-key'})]:
        assert access_client.get('/api/cases',headers={'Cf-Access-Jwt-Assertion':invalid}).status_code == 401


def test_cross_origin_and_missing_origin_mutations_are_rejected(access_client,signing_keys):
    signed = headers(signing_keys[0])
    for origin in ['https://evil.example.com', 'null', '']:
        response = access_client.post('/api/cases',json={'customer_name':'拒絕案件'},headers={**signed,'Origin':origin})
        assert response.status_code == 403
    allowed = access_client.post('/api/cases',json={'customer_name':'登入操作測試'},headers=signed)
    assert allowed.status_code == 200
    case_id = allowed.json()['id']
    assert access_client.patch(f'/api/cases/{case_id}',json={'notes':'已登入修改'},headers=signed).status_code == 200


@pytest.mark.asyncio
async def test_jwks_single_refresh_unknown_key_throttle_and_rotation(monkeypatch,signing_keys):
    import asyncio
    import app.cloudflare_access as access
    calls = []
    active_keys = [{'kty':'RSA','kid':'malformed','n':'bad','e':'bad'},signing_keys[1]]
    transport = httpx.MockTransport(lambda request:(calls.append(request.url),httpx.Response(200,json={'keys':active_keys}))[1])
    original = httpx.AsyncClient
    monkeypatch.setattr(access.httpx,'AsyncClient',lambda **kw:original(transport=transport,**kw))
    verifier = AccessVerifier(config())
    clock = [1000.0]
    verifier.clock = lambda:clock[0]
    identities = await asyncio.gather(*(verifier.verify(token(signing_keys[0])) for _ in range(8)))
    assert len(calls) == 1 and all(identity.role == 'operator' for identity in identities)
    for _ in range(8):
        with pytest.raises(HTTPException) as exc:
            await verifier._key('unknown-kid')
        assert exc.value.status_code == 401
    assert len(calls) == 1
    clock[0] += 61
    active_keys = [{**signing_keys[1],'kid':'rotated-key'}]
    assert (await verifier._key('rotated-key')).key
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_jwks_failure_throttles_and_uses_only_bounded_cached_keys(monkeypatch,signing_keys):
    import app.cloudflare_access as access
    calls = []
    def unavailable(request):
        calls.append(request.url)
        raise httpx.ConnectError('offline',request=request)
    original = httpx.AsyncClient
    monkeypatch.setattr(access.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(unavailable),**kw))
    verifier = AccessVerifier(config())
    clock = [1000.0]
    verifier.clock = lambda:clock[0]
    for _ in range(5):
        with pytest.raises(HTTPException) as exc:
            await verifier.verify(token(signing_keys[0]))
        assert exc.value.status_code == 503
    assert len(calls) == 1
    verifier.keys = {'test-key':jwt.PyJWK.from_dict(signing_keys[1])}
    verifier.refreshed_at = 650
    assert (await verifier.verify(token(signing_keys[0]))).role == 'operator'
    clock[0] = 2000
    with pytest.raises(HTTPException) as exc:
        await verifier.verify(token(signing_keys[0]))
    assert exc.value.status_code == 503 and len(calls) == 2


@pytest.mark.parametrize('changes', [dict(auth_mode='cloudfare'),dict(cloudflare_access_audience=''),
                                     dict(cloudflare_access_emails=()),dict(cloudflare_access_admin_emails=()),
                                     dict(cloudflare_access_issuer='https://evil.example.com'),
                                     dict(public_base_url='http://travel.example.com'),
                                     dict(cloudflare_access_emails=('*@example.com',))])
def test_auth_configuration_fails_closed(monkeypatch,changes):
    import app.security as security
    monkeypatch.setattr(security,'settings',replace(config(),**changes))
    with pytest.raises(RuntimeError):
        security.validate_runtime_settings()


def test_local_mode_discovery_is_public_and_liveness_has_no_metadata():
    with TestClient(app) as client:
        assert client.get('/api/auth/session').json() == {'mode':'token'}
        assert client.get('/livez').json() == {'ok':True}


def test_access_operator_can_complete_web_workflow(access_client,signing_keys):
    signed = headers(signing_keys[0])
    for path in ['/api/mom/home','/api/mom/preferences','/api/airlines','/api/hotels/networks']:
        assert access_client.get(path,headers=signed).status_code == 200
    session = 'access-end-to-end'
    assert access_client.post(f'/api/guided/{session}/start',headers=signed).status_code == 200
    for answer in ['登入客人','東京','2026-11-18','2026-11-22','2大1小1嬰兒','10萬內']:
        completed = access_client.post(f'/api/guided/{session}/reply',json={'text':answer},headers=signed)
        assert completed.status_code == 200
    case_id = completed.json()['case_id']
    assert access_client.patch(f'/api/cases/{case_id}',json={'children_ages':[7]},headers=signed).status_code == 200
    assert access_client.get(f'/api/mom/cases/{case_id}',headers=signed).status_code == 200
    flight = access_client.post('/api/browser/flight-search',json={'case_id':case_id,'origin':'TPE','destination':'NRT','depart_date':'2026-11-18','return_date':'2026-11-22','adults':2,'children':1,'infants':1,'children_ages':[7]},headers=signed)
    assert flight.status_code == 200
    run_id = flight.json()['run']['id']
    assert access_client.get(f'/api/browser/runs/{run_id}',headers=signed).status_code == 200
    assert access_client.get(f'/api/mom/search-progress/flight/{run_id}',headers=signed).status_code == 200
    hotel = access_client.post('/api/browser/hotel-search',json={'case_id':case_id,'hotel_name':'Hilton Tokyo','official_url':'https://www.hilton.com/','checkin_date':'2026-11-18','checkout_date':'2026-11-22','adults':2,'children_ages':[7,1]},headers=signed)
    assert hotel.status_code == 200
    assert access_client.get(f"/api/browser/hotel-runs/{hotel.json()['run']['id']}",headers=signed).status_code == 200
    from tests.test_web_workflow import manual_payload
    for kind in ['flight','hotel']:
        option = access_client.post(f'/api/mom/cases/{case_id}/options',json=manual_payload(kind=kind),headers=signed)
        assert option.status_code == 200
        assert access_client.post(f'/api/mom/cases/{case_id}/selection',json={'option_id':option.json()['id']},headers=signed).status_code == 200
    assert access_client.get(f'/api/mom/cases/{case_id}/options',headers=signed).json()['can_draft_offer']
    draft = access_client.post('/api/customer-reply',json={'case_id':case_id,'incoming_text':'請提供方案'},headers=signed)
    assert draft.status_code == 200 and '60,000.20' in draft.json()['text']
    assert access_client.post('/api/mom/skill-feedback',json={'skill_key':'customer-reply','feedback_type':'accepted','source':'web_template','case_id':case_id,'draft_text':draft.json()['text']},headers=signed).status_code == 200
    for kind in ['flight','hotel']:
        assert access_client.delete(f'/api/mom/cases/{case_id}/selection/{kind}',headers=signed).status_code == 200
    assert access_client.get(f'/api/mom/cases/{case_id}/options',headers=signed).json()['selections'] == []
    assert access_client.get('/new-export-route',headers=signed).status_code == 403


def test_access_jwks_outage_http_returns_503(access_client,signing_keys,monkeypatch):
    verifier = app.state.access_verifier
    verifier.keys = {}
    verifier.attempted_at = verifier.clock()
    response = access_client.get('/api/cases',headers=headers(signing_keys[0]))
    assert response.status_code == 503 and response.json()['detail'] == 'login verification temporarily unavailable'


def test_access_origin_normalizes_hostname_and_default_port(access_client,signing_keys,monkeypatch):
    import app.security as security
    monkeypatch.setattr(security,'settings',replace(config(),public_base_url='https://TRAVEL.EXAMPLE.COM:443/'))
    security.validate_runtime_settings()
    response = access_client.post('/api/cases',json={'customer_name':'來源驗證'},headers=headers(signing_keys[0]))
    assert response.status_code == 200


def test_access_operator_agency_lifecycle_and_export_boundaries(access_client, signing_keys):
    from datetime import timedelta
    from uuid import uuid4
    from tests.test_web_workflow import manual_payload
    signed = headers(signing_keys[0])
    c = access_client.post('/api/cases', json={'customer_name':'營運登入測試','destination':'東京',
        'depart_date':'2026-11-18','return_date':'2026-11-22','adults':2,'children':1,'infants':1,'children_ages':[7]}, headers=signed).json()
    base = f"/api/mom/cases/{c['id']}"
    def post(suffix, data):
        response = access_client.post(base+suffix, json={'request_id':str(uuid4()), **data}, headers=signed)
        assert response.status_code == 200, response.text
        return response.json()
    for kind in ['flight','hotel']:
        option = access_client.post(base+'/options', json=manual_payload(kind=kind), headers=signed).json()
        assert access_client.post(base+'/selection',json={'option_id':option['id']},headers=signed).status_code == 200
    quote = post('/quotes', {'title':'對客報價','valid_until':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat(), 'includes':'公開內容','excludes':'退改條件'})
    proof={'reference':'PRIVATE-EVIDENCE','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True}
    for action in ['sent','accept']:
        post(f"/quotes/{quote['id']}/{action}", proof)
    for kind, doc_kind in [('flight','e_ticket'),('hotel','hotel_voucher')]:
        booking=post('/bookings', {**proof,'kind':kind,'title':'公開訂购','supplier':'PRIVATE-WINDOW','confirmation_number':kind+'-123','customer_details':'公開確認內容'})
        post(f"/bookings/{booking['id']}/rebind",{**proof,'reason':'供應商重新核對','customer_details':'公開確認內容'})
        doc=post('/documents',{'kind':doc_kind,'title':'公開憑證','required':True,'booking_id':booking['id']})
        response=access_client.patch(base+f"/documents/{doc['id']}",json={'request_id':str(uuid4()),**proof,'expected_revision':1,'status':'ready','customer_text':'已核對原檔'},headers=signed)
        assert response.status_code == 200, response.text
    post('/ledger',{**proof,'kind':'customer_receipt','amount':'100.10','currency':'TWD'})
    task=post('/work-items',{'kind':'pretrip','title':'交付','owner':'媽媽','due_at':datetime.now(timezone.utc).isoformat(),'source':'約定'})
    response=access_client.patch(base+f"/work-items/{task['id']}",json={'request_id':str(uuid4()),'expected_revision':1,'status':'done','reason':'已完成'},headers=signed)
    assert response.status_code == 200
    pack=post('/pretrip', {'title':'公開行前摘要'})
    post(f"/pretrip/{pack['id']}/deliver",{**proof,'channel':'LINE 人工'})
    for suffix in [f"/quotes/{quote['id']}/document",f"/pretrip/{pack['id']}/document"]:
        response=access_client.get(base+suffix,headers=signed)
        assert response.status_code == 200 and 'text/html' in response.headers['content-type']
        assert 'PRIVATE-EVIDENCE' not in response.text and 'PRIVATE-WINDOW' not in response.text
        assert 'no-store' in response.headers['cache-control']
        assert "'unsafe-inline'" not in response.headers['content-security-policy']
        assert access_client.get(base+suffix).status_code == 401
    assert access_client.get(base+'/operations',headers=signed).json()['accepted_quote_id']==quote['id']
    assert access_client.get('/api/mom/work-items',headers=signed).json()['timezone']=='Asia/Taipei'
    for suffix in ['/quotes','/work-items','/bookings','/ledger','/documents','/pretrip']:
        assert access_client.post(base+suffix,json={},headers={**signed,'Origin':'https://evil.example.com'}).status_code == 403
    for suffix in ['/operations/extra','/quotes/a/document/extra','/quotes/a/delete','/pretrip/a/void','/bookings/a/document','/documents/a/void']:
        assert access_client.post(base+suffix,json={},headers=signed).status_code == 403
    assert access_client.delete(base+'/quotes/'+quote['id'],headers=signed).status_code == 403
    assert access_client.patch(base+'/bookings/'+booking['id'],json={},headers=signed).status_code == 403


def test_lifecycle_routes_exact_authorization_origin_and_verified_actor(access_client, signing_keys):
    from uuid import uuid4
    from app.db import connect
    private=signing_keys[0]; mom=headers(private)
    case=access_client.post('/api/cases',headers=mom,json={'customer_name':'Access 結案合成測試'}).json()
    base=f"/api/mom/cases/{case['id']}"
    state=access_client.get(base+'/operations',headers=mom).json()['lifecycle']['expected_state']
    payload={'request_id':str(uuid4()),'expected_state':state,'reason':'客人取消詢問','reference':'合成對話',
             'occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,'outcome':'withdrawn'}
    assert access_client.post(base+'/lifecycle/close',json=payload).status_code==401
    assert access_client.post(base+'/lifecycle/close',headers={**mom,'Origin':'https://other.example'},json=payload).status_code==403
    for path in ('close/','close-extra','unknown'):
        assert access_client.post(base+'/lifecycle/'+path,headers=mom,json=payload).status_code==403
    assert access_client.patch(base+'/lifecycle/close',headers=mom,json=payload).status_code==403
    closed=access_client.post(base+'/lifecycle/close',headers=mom,json=payload)
    assert closed.status_code==200 and closed.json()['event']['actor']=='mom@example.com'
    state=access_client.get(base+'/operations',headers=mom).json()['lifecycle']['expected_state']
    reopened=access_client.post(base+'/lifecycle/reopen',headers=mom,json={k:v for k,v in {**payload,'request_id':str(uuid4()),'expected_state':state}.items() if k!='outcome'})
    assert reopened.status_code==200 and reopened.json()['status']=='intake'
    with connect() as db:
        assert db.execute("SELECT actor FROM audit_log WHERE case_id=? AND action='agency.case.reopen'",(case['id'],)).fetchone()[0]=='mom@example.com'


@pytest.mark.parametrize('path',['/api/browser/runs/synthetic/abandon','/api/browser/hotel-runs/synthetic/abandon','/api/browser/tasks/synthetic/abandon'])
def test_search_abandon_is_admin_only_and_origin_protected(access_client,signing_keys,path):
    private=signing_keys[0]
    assert access_client.post(path,headers=headers(private),json={}).status_code==403
    assert access_client.post(path,headers={**headers(private,email='admin@example.com'),'Origin':'https://wrong.example'},json={}).status_code==403
    assert access_client.post(path,headers=headers(private,email='admin@example.com'),json={}).status_code==422


def test_service_order_exact_routes_origin_identity_and_receipts(access_client, signing_keys):
    from datetime import timedelta
    from uuid import uuid4
    mom=headers(signing_keys[0])
    case=access_client.post('/api/cases',headers=mom,json={'customer_name':'Access服務工作單合成'}).json()
    base=f"/api/mom/cases/{case['id']}"
    payload={'request_id':str(uuid4()),'reference':'已核對','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,
             'kind':'incident','title':'立即協助','request_details':'已接到需求','owner':'媽媽','due_at':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
    assert access_client.post(base+'/service-orders',json=payload).status_code==401
    assert access_client.post(base+'/service-orders',json=payload,headers={**mom,'Origin':'https://evil.example'}).status_code==403
    order=access_client.post(base+'/service-orders',json=payload,headers=mom)
    assert order.status_code==200,order.text
    order=order.json();assert order['history'][0]['actor']=='mom@example.com'
    for suffix in ('service-orders/','service-orders/extra/delete','service-orders/x/progress/','service-order-receipts/x/extra'):
        assert access_client.post(base+'/'+suffix,json=payload,headers=mom).status_code==403
    for method,suffix in [('DELETE','service-orders/'+order['id']),('GET','service-orders/'+order['id']+'/progress'),('PATCH','service-orders/'+order['id']+'/settlement')]:
        assert access_client.request(method,base+'/'+suffix,headers=mom).status_code==403
    for action in ('assessment','decision','progress','settlement','resolve','reopen'):
        assert access_client.post(base+f"/service-orders/{order['id']}/{action}",json={},headers={**mom,'Origin':'null'}).status_code==403
        assert access_client.post(base+f"/service-orders/{order['id']}/{action}",json={},headers=mom).status_code==422
    assert access_client.get(base+'/service-order-receipts/'+payload['request_id'],headers=mom).json()=={'committed':True,'order_id':order['id']}
    assert access_client.get(base+'/service-order-receipts/'+payload['request_id'],headers=headers(signing_keys[0],email='admin@example.com')).status_code==409
    progress=access_client.post(base+f"/service-orders/{order['id']}/progress",headers=mom,json={**{k:v for k,v in payload.items() if k in {'reference','occurred_at','checked'}},'request_id':str(uuid4()),'expected_revision':order['revision'],'stage':'safety_assistance','message':'已完成立即協助'}).json()
    resolved=access_client.post(base+f"/service-orders/{order['id']}/resolve",headers=mom,json={**{k:v for k,v in payload.items() if k in {'reference','occurred_at','checked'}},'request_id':str(uuid4()),'expected_revision':progress['revision'],'summary':'已通知客人','customer_notified_checked':True})
    assert resolved.status_code==200,resolved.text
    state=access_client.get(base+'/operations',headers=mom).json()['lifecycle']['expected_state']
    closed=access_client.post(base+'/lifecycle/close',headers=mom,json={**{k:v for k,v in payload.items() if k in {'reference','occurred_at','checked'}},'request_id':str(uuid4()),'expected_state':state,'reason':'服務已完成','outcome':'completed','supplier_settlement_checked':True})
    assert closed.status_code==200,closed.text


@pytest.mark.parametrize('method,suffix,fields', [
    ('POST', '/service-orders', {'kind':'incident','title':'身分綁定','request_details':'需求','owner':'媽媽','due_at':'2030-01-01T00:00:00Z'}),
    ('PATCH', '/service-orders/missing', {'expected_revision':1,'owner':'媽媽','due_at':'2030-01-01T00:00:00Z','urgency':'normal','reason':'核對'}),
    ('POST', '/service-orders/missing/assessment', {'expected_revision':1,'supplier_reply':'回覆','proposal':'方案','terms_reference':'依據','valid_until':'2030-01-01T00:00:00Z','reason':'核對'}),
    ('POST', '/service-orders/missing/decision', {'expected_revision':1,'assessment_revision':1,'decision':'approved','customer_reply':'採用'}),
    ('POST', '/service-orders/missing/progress', {'expected_revision':1,'stage':'note','message':'聯絡'}),
    ('POST', '/service-orders/missing/settlement', {'expected_revision':1,'kind':'customer_receipt','amount':'10','currency':'TWD'}),
    ('POST', '/service-orders/missing/resolve', {'expected_revision':1,'summary':'處理完成','customer_notified_checked':True}),
    ('POST', '/service-orders/missing/reopen', {'expected_revision':1,'reason':'再核對'}),
])
def test_service_mutations_bind_form_actor_before_command(access_client, signing_keys, method, suffix, fields):
    from uuid import uuid4
    from app.db import connect
    signed=headers(signing_keys[0], email='admin@example.com')
    case=access_client.post('/api/cases',headers=signed,json={'customer_name':'切換身分拒絕合成'}).json()
    base=f"/api/mom/cases/{case['id']}"
    payload={'request_id':str(uuid4()),'reference':'核對','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,**fields}
    if '/missing' in suffix:
        order=access_client.post(base+'/service-orders',headers=signed,json={
            'request_id':str(uuid4()),'reference':'核對','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,
            'kind':'incident','title':'真實可修改工作單','request_details':'需求','owner':'媽媽','due_at':'2030-01-01T00:00:00Z'}).json()
        suffix=suffix.replace('/missing','/'+order['id'])
    snapshot=access_client.get(base+'/operations',headers=signed).json()
    with connect() as db:
        before={table:db.execute(f'SELECT COUNT(*) FROM {table} WHERE case_id=?',(case['id'],)).fetchone()[0]
                for table in ('agency_commands','agency_service_orders','agency_ledger','audit_log')}
    response=access_client.request(method,base+suffix,json=payload,headers={**signed,'X-Travel-Service-Actor':'mom%40example.com'})
    assert response.status_code==412,response.text
    with connect() as db:
        assert before=={table:db.execute(f'SELECT COUNT(*) FROM {table} WHERE case_id=?',(case['id'],)).fetchone()[0] for table in before}
    assert access_client.get(base+'/service-order-receipts/'+payload['request_id'],headers=signed).json()=={'committed':False}
    assert access_client.get(base+'/operations',headers=signed).json()==snapshot


def test_service_actor_header_encoding_and_idempotent_conflict(access_client, signing_keys):
    from urllib.parse import quote
    from uuid import uuid4
    mom=headers(signing_keys[0])
    case=access_client.post('/api/cases',headers=mom,json={'customer_name':'身分編碼合成'}).json()
    base=f"/api/mom/cases/{case['id']}"
    payload={'request_id':str(uuid4()),'reference':'核對','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,
             'kind':'incident','title':'原始需求','request_details':'需求','owner':'媽媽','due_at':'2030-01-01T00:00:00Z'}
    for invalid in ('%', '%GG', '%FF', ''):
        r=access_client.post(base+'/service-orders',json=payload,headers={**mom,'X-Travel-Service-Actor':invalid})
        assert r.status_code==(412 if invalid=='' else 400),r.text
    actor=quote(' MOM@EXAMPLE.COM ')
    r=access_client.post(base+'/service-orders',json=payload,headers={**mom,'X-Travel-Service-Actor':actor})
    assert r.status_code==200,r.text
    assert access_client.post(base+'/service-orders',json=payload,headers=mom).json()==r.json()
    assert access_client.post(base+'/service-orders',json={**payload,'title':'更改文字'},headers=mom).status_code==409
    assert access_client.get(base+'/service-order-receipts/'+payload['request_id'],headers=mom).json()=={'committed':True,'order_id':r.json()['id']}
    wrong={**mom,'X-Travel-Service-Actor':'admin%40example.com'}
    assert access_client.get(base+'/service-order-receipts/'+payload['request_id'],headers=wrong).status_code==412
    assert len(access_client.get(base+'/operations',headers=mom).json()['service_orders'])==1
    # Match AccessVerifier's Unicode normalization, not just ASCII lowercasing.
    app.state.access_verifier.operators.add('strasse@example.com')
    unicode_actor=headers(signing_keys[0],email='Straße@example.com')
    response=access_client.post(base+'/service-orders',json={**payload,'request_id':str(uuid4())},
                               headers={**unicode_actor,'X-Travel-Service-Actor':quote('STRAẞE@EXAMPLE.COM')})
    assert response.status_code==200,response.text
    assert response.json()['history'][0]['actor']=='strasse@example.com'


def test_ready_settlement_wrong_actor_guard_writes_nothing_then_owner_succeeds(access_client, signing_keys):
    from app.db import connect
    from uuid import uuid4
    signed=headers(signing_keys[0])
    case=access_client.post('/api/cases',headers=signed,json={'customer_name':'可收款身分綁定合成'}).json()
    base=f"/api/mom/cases/{case['id']}"
    def proof(**extra):
        return {'request_id':str(uuid4()),'reference':'已核對','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,**extra}
    def post(suffix, payload):
        response=access_client.post(base+suffix,headers=signed,json=payload)
        assert response.status_code==200,response.text
        return response.json()
    order=post('/service-orders',proof(kind='incident',title='可收款工作單',request_details='需求',owner='媽媽',due_at='2030-01-01T00:00:00Z'))
    order_path='/service-orders/'+order['id']
    order=post(order_path+'/assessment',proof(expected_revision=order['revision'],supplier_reply='回覆',proposal='方案',terms_reference='依據',valid_until='2030-01-01T00:00:00Z',reason='核對',amounts=[{'currency':'TWD','customer_receipt':'10','final_customer_due':'10'}]))
    order=post(order_path+'/decision',proof(expected_revision=order['revision'],assessment_revision=order['assessment']['revision'],decision='approved',customer_reply='採用'))
    order=post(order_path+'/progress',proof(expected_revision=order['revision'],stage='start'))
    order=post(order_path+'/progress',proof(expected_revision=order['revision'],stage='supplier_result',outcome='confirmed',details='正式完成通知'))
    payload=proof(expected_revision=order['revision'],kind='customer_receipt',amount='10',currency='TWD')
    with connect() as db:
        before={table:db.execute(f'SELECT COUNT(*) FROM {table} WHERE case_id=?',(case['id'],)).fetchone()[0]
                for table in ('agency_commands','agency_service_orders','agency_ledger','audit_log')}
    before_order=access_client.get(base+'/operations',headers=signed).json()['service_orders'][0]
    rejected=access_client.post(base+order_path+'/settlement',headers={**signed,'X-Travel-Service-Actor':'admin%40example.com'},json=payload)
    assert rejected.status_code==412,rejected.text
    with connect() as db:
        assert before=={table:db.execute(f'SELECT COUNT(*) FROM {table} WHERE case_id=?',(case['id'],)).fetchone()[0] for table in before}
    assert access_client.get(base+'/operations',headers=signed).json()['service_orders'][0]==before_order
    recorded=post(order_path+'/settlement',payload)
    assert recorded['revision']==order['revision']+1
    assert len(access_client.get(base+'/operations',headers=signed).json()['ledger'])==1
