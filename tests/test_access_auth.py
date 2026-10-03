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


@pytest.mark.parametrize('path', ['/', '/static/app.js', '/admin', '/admin-static/app.js', '/health',
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
