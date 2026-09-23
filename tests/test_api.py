from fastapi.testclient import TestClient
from app.main import app

client=TestClient(app)


def test_health_and_demo():
    with client:
        assert client.get('/health').status_code==200
        r=client.get('/api/demo/flights')
        assert r.status_code==200
        assert r.json()['customer_safe'] is False


def test_payment_approval_denied():
    with client:
        r=client.post('/api/approvals', json={'case_id':None,'action_type':'payment','summary':'pay now','amount_twd':1000})
        assert r.status_code==403


def test_airlines_and_structured_flight_search_endpoint():
    with client:
        air = client.get('/api/airlines')
        assert air.status_code == 200
        assert len(air.json()['airlines']) == 8
        r = client.post('/api/browser/flight-search', json={
            'origin':'TPE','destination':'KIX','depart_date':'2026-10-18','return_date':'2026-10-22',
            'adults':2,'children':0,'infants':0,'airline_codes':['CI','JX','CX']
        })
        assert r.status_code == 200
        assert len(r.json()['tasks']) == 3


def test_flight_compare_endpoint_accepts_task_batch():
    payload = {
        "origin": "TPE", "destination": "NRT", "depart_date": "2026-10-18", "return_date": "2026-10-22",
        "adults": 1, "airline_codes": ["CI"]
    }
    created = client.post('/api/browser/flight-search', json=payload)
    assert created.status_code == 200
    task_id = created.json()['tasks'][0]['id']
    compared = client.post('/api/browser/flight-search/compare', json={"task_ids": [task_id]})
    assert compared.status_code == 200
    body = compared.json()
    assert body['schema_version'] == 'flight-comparison-v1'
    assert body['task_states'][0]['state'] == 'needs_result'


def test_configuration_readiness_endpoint():
    with client:
        response = client.get('/api/system/readiness')
    assert response.status_code == 200
    body = response.json()
    assert body['schema_version'] == 'configuration-readiness-v2'
    assert body['offline_poc_ready'] is True
    assert any(check['key'] == 'agent_separation' for check in body['checks'])


def test_line_webhook_is_default_deny_when_channel_disabled():
    with client:
        response = client.post('/webhooks/line', json={'events': []})
    assert response.status_code == 503
    assert response.json()['detail'] == 'LINE channel is disabled'


def test_telegram_webhook_is_default_deny_when_channel_disabled():
    with client:
        response = client.post(
            '/webhooks/telegram',
            json={
                'update_id': 1,
                'message': {'chat': {'id': 12345}, 'text': '測試'},
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body['ok'] is False
    assert body['disabled'] is True
    assert body['handled'] == 0


def test_telegram_webhook_secret_verifier(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException
    import app.channels.telegram as telegram_channel

    monkeypatch.setattr(
        telegram_channel,
        'settings',
        SimpleNamespace(telegram_enabled=True, telegram_webhook_secret='expected-secret'),
    )
    telegram_channel.verify_webhook_secret('expected-secret')
    with pytest.raises(HTTPException) as exc:
        telegram_channel.verify_webhook_secret('wrong-secret')
    assert exc.value.status_code == 401

    monkeypatch.setattr(
        telegram_channel,
        'settings',
        SimpleNamespace(telegram_enabled=True, telegram_webhook_secret=''),
    )
    with pytest.raises(HTTPException) as missing:
        telegram_channel.verify_webhook_secret(None)
    assert missing.value.status_code == 503


def test_hotel_network_registry_and_structured_search_endpoint():
    with client:
        networks = client.get('/api/hotels/networks')
        assert networks.status_code == 200
        codes = {row['code'] for row in networks.json()['networks']}
        assert {'MARRIOTT', 'HILTON', 'HYATT'}.issubset(codes)
        created = client.post('/api/browser/hotel-search', json={
            'hotel_name': 'Hilton Tokyo',
            'official_url': 'https://www.hilton.com/en/hotels/tyohitw-hilton-tokyo/',
            'checkin_date': '2026-10-18',
            'checkout_date': '2026-10-22',
            'rooms': 1,
            'adults': 2,
            'children_ages': [],
            'currency_preference': 'TWD',
            'breakfast_required': True,
            'free_cancellation_preferred': True,
        })
    assert created.status_code == 200
    body = created.json()
    assert body['run']['request']['hotel_name'] == 'Hilton Tokyo'
    assert body['task']['expected_schema'] == 'hotel-search-v1'


def test_unknown_hotel_domain_is_default_deny_and_ota_grant_is_rejected():
    with client:
        denied = client.post('/api/browser/hotel-search', json={
            'hotel_name': 'Unknown Hotel',
            'official_url': 'https://unknown-hotel.invalid/book',
            'checkin_date': '2026-10-18',
            'checkout_date': '2026-10-20',
            'adults': 2,
        })
        ota = client.post('/api/hotels/site-grants', json={
            'hotel_name': 'Fake Official Hotel',
            'official_url': 'https://www.booking.com/hotel/example.html',
            'trust_source': 'human',
        })
    assert denied.status_code == 400
    assert '尚未信任' in denied.json()['detail']
    assert ota.status_code == 400
    assert 'OTA' in ota.json()['detail']


def test_independent_hotel_site_grant_can_be_revoked():
    domain = 'https://api-test-independent-hotel.example/booking'
    with client:
        created = client.post('/api/hotels/site-grants', json={
            'hotel_name': 'API Test Independent Hotel',
            'official_url': domain,
            'trust_source': 'human',
            'notes': 'human verified test grant',
        })
        assert created.status_code == 200
        grant_id = created.json()['id']
        revoked = client.post(f'/api/hotels/site-grants/{grant_id}/revoke')
        assert revoked.status_code == 200
        assert revoked.json()['status'] == 'revoked'
        denied = client.post('/api/browser/hotel-search', json={
            'hotel_name': 'API Test Independent Hotel',
            'official_url': domain,
            'checkin_date': '2026-10-18',
            'checkout_date': '2026-10-20',
            'adults': 2,
        })
    assert denied.status_code == 400
    assert '尚未信任' in denied.json()['detail']


def test_v081_mom_frontend_and_admin_workbench_are_split():
    with client:
        mom = client.get('/')
        admin = client.get('/admin')
    assert mom.status_code == 200
    assert admin.status_code == 200
    assert '旅行社小幫手' in mom.text
    assert '查飯店' in mom.text
    assert 'onclick=' not in mom.text
    assert '飯店官網信任' in admin.text
