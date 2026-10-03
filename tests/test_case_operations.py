from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db import connect, init_db
from app.operations_models import QuoteCreate
from app.services import case_operations as service


def moment(hours=0):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def intent(**payload):
    return {'request_id': str(uuid4()), **payload}


def evidence(**payload):
    return intent(reference='PRIVATE-CHECK-REFERENCE', occurred_at=moment(), checked=True, **payload)


@pytest.fixture
def client():
    with TestClient(app) as value:
        yield value


def family(client):
    start = datetime.now(timezone.utc).date() + timedelta(days=14)
    case = client.post('/api/cases', json={'customer_name': '業務測試'+uuid4().hex[:6], 'destination': '東京',
        'depart_date': start.isoformat(), 'return_date': (start+timedelta(days=4)).isoformat(),
        'adults': 2, 'children': 1, 'children_ages': [7], 'infants': 1}).json()
    ids = []
    for kind, amount in [('flight', '30000.10'), ('hotel', '20000.20')]:
        option = client.post(f"/api/mom/cases/{case['id']}/options", json={'kind': kind,
            'supplier_name': 'PRIVATE-SUPPLIER', 'source_reference': 'PRIVATE-SOURCE',
            'title': kind+'對客方案', 'details': '全案旅客內容', 'conditions': '已列退改條件',
            'total_amount': amount, 'currency': 'TWD', 'observed_at': moment(),
            'confirmed_for_case': True}).json()
        assert client.post(f"/api/mom/cases/{case['id']}/selection", json={'option_id': option['id']}).status_code == 200
        ids.append(option['id'])
    return case, ids


def quote_payload(ids=()):
    return intent(title='東京親子報價', valid_until=moment(4), includes='機票與住宿', excludes='未列明費用',
        adjustments=[{'currency': 'TWD', 'service_fee': '100.30', 'discount': '0.30'}],
        costs={i: '8711.77' for i in ids})


def post(client, case, suffix, payload):
    return client.post(f"/api/mom/cases/{case['id']}/{suffix}", json=payload)


def accepted(client, case, ids=()):
    response = post(client, case, 'quotes', quote_payload(ids))
    assert response.status_code == 200, response.text
    q = response.json()
    assert post(client, case, f"quotes/{q['id']}/sent", evidence()).status_code == 200
    assert post(client, case, f"quotes/{q['id']}/accept", evidence()).status_code == 200
    return q


def bundle(client, case):
    return client.get(f"/api/mom/cases/{case['id']}/operations").json()


def verified_booking(client, case, kind='flight'):
    response = post(client, case, 'bookings', evidence(kind=kind, title=kind+'正式確認', supplier='PRIVATE-BOOK-SUPPLIER',
        confirmation_number=uuid4().hex[:6], customer_details='已核對旅行日期、人數與確認內容'))
    assert response.status_code == 200, response.text
    return response.json()


def ready_document(client, case, booking, kind):
    doc = post(client, case, 'documents', intent(kind=kind, title=kind, required=True, booking_id=booking['id'])).json()
    response = client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}", json=evidence(
        expected_revision=1, status='ready', customer_text='實際文件已人工核對，請參考另附的憑證', customer_url='https://example.com/customer-voucher'))
    assert response.status_code == 200, response.text
    return response.json()


def test_end_to_end_quotes_deadlines_deposit_bookings_documents_and_delivery(client):
    case, ids = family(client)
    first = post(client, case, 'quotes', quote_payload(ids)).json()
    q = accepted(client, case, ids)
    current = bundle(client, case)
    assert [r['version'] for r in current['quotes']] == [1, 2]
    assert current['quotes'][0]['status'] == 'replaced'
    assert current['quotes'][0]['totals'] == {'TWD': '50100.30'}
    assert current['case']['status'] == 'booking'
    task = post(client, case, 'work-items', intent(kind='deposit', title='確認訂金', owner='媽媽', due_at=moment(-1), source='客人採用報價', quote_id=q['id'])).json()
    assert task['status'] == 'open'
    receipt = post(client, case, 'ledger', evidence(kind='customer_receipt', amount='10000.10', currency='TWD')).json()
    assert bundle(client, case)['balances']['TWD']['customer_balance'] == '40100.20'
    b1 = verified_booking(client, case)
    assert bundle(client, case)['case']['status'] == 'booking'
    b2 = verified_booking(client, case, 'hotel')
    assert bundle(client, case)['case']['status'] == 'confirmed'
    incomplete = post(client, case, 'pretrip', intent(title='行前摘要待核對')).json()
    assert incomplete['status'] == 'draft' and incomplete['blockers']
    assert client.get(f"/api/mom/cases/{case['id']}/pretrip/{incomplete['id']}/document").status_code == 409
    assert post(client, case, f"pretrip/{incomplete['id']}/deliver", evidence(channel='LINE')).status_code == 409
    ready_document(client, case, b1, 'e_ticket')
    ready_document(client, case, b2, 'hotel_voucher')
    pack = post(client, case, 'pretrip', intent(title='行前摘要')).json()
    assert pack['status'] == 'prepared' and pack['version'] == 2
    delivered = post(client, case, f"pretrip/{pack['id']}/deliver", evidence(channel='LINE')).json()
    assert delivered['status'] == 'delivered'
    update = client.patch(f"/api/mom/cases/{case['id']}/work-items/{task['id']}", json=intent(expected_revision=1, status='done', reason='訂金已核對'))
    assert update.status_code == 200 and update.json()['revision'] == 2
    assert receipt['status'] == 'recorded' and first['items'] == current['quotes'][0]['items']


def test_quotes_are_immutable_and_customer_exports_exclude_private_values(client):
    case, ids = family(client)
    q = accepted(client, case, ids)
    assert bundle(client, case)['quotes'][0]['expected_margin']['TWD'] == '32676.76'
    doc = client.get(f"/api/mom/cases/{case['id']}/quotes/{q['id']}/document")
    assert doc.status_code == 200
    assert '50100.30' not in doc.text or '50,100.30' in doc.text
    for secret in ['PRIVATE', '8711.77', '32676.76', 'costs', 'source_reference']:
        assert secret not in doc.text
    safe = service.public_quote(bundle(client, case)['quotes'][0])
    assert not {'costs', 'expected_margin', 'events'} & safe.keys()
    assert 'id' not in safe['items'][0]


@pytest.mark.parametrize('changes', [{'costs': {'foreign': '1'}}, {'valid_until': moment(30)},
    {'valid_until': moment(-1)}, {'adjustments': [{'currency':'JPY','service_fee':'1'}]},
    {'adjustments': [{'currency':'TWD','discount':'99999'}]}])
def test_invalid_quote_terms_do_not_create_a_version(client, changes):
    case, ids = family(client)
    response = post(client, case, 'quotes', {**quote_payload(ids), **changes})
    assert response.status_code == 409 and not bundle(client, case)['quotes']


def test_expired_or_changed_quotes_cannot_be_sent_or_accepted(client):
    case, ids = family(client)
    q = post(client, case, 'quotes', quote_payload()).json()
    assert post(client, case, f"quotes/{q['id']}/accept", evidence()).status_code == 409
    post(client, case, f"quotes/{q['id']}/sent", evidence())
    client.patch(f"/api/cases/{case['id']}", json={'adults': 3})
    assert post(client, case, f"quotes/{q['id']}/accept", evidence()).status_code == 409
    assert bundle(client, case)['quotes'][0]['status'] == 'sent'


def test_accepting_amendment_keeps_case_ledger_and_requires_reason(client):
    case, ids = family(client)
    previous = accepted(client, case)
    b = verified_booking(client, case)
    post(client, case, 'ledger', evidence(kind='customer_receipt', amount='10000', currency='TWD'))
    revised = post(client, case, 'quotes', {**quote_payload(), 'adjustments':[{'currency':'TWD','service_fee':'500'}]}).json()
    post(client, case, f"quotes/{revised['id']}/sent", evidence())
    assert post(client, case, f"quotes/{revised['id']}/accept", evidence()).status_code == 409
    response = post(client, case, f"quotes/{revised['id']}/accept", evidence(amend=True, reason='客人確認新增服務費'))
    assert response.status_code == 200
    current = bundle(client, case)
    assert current['balances']['TWD']['customer_balance'] == '40500.30'
    assert current['bookings'][0]['quote_id'] == previous['id']
    assert current['warnings']
    voided = post(client, case, f"bookings/{b['id']}/void", evidence(reason='更正確認並綁定新版報價'))
    assert voided.status_code == 200
    payload = evidence(kind=b['kind'], title=b['title'], supplier=b['supplier'], confirmation_number=b['confirmation_number'], customer_details=b['customer_details'])
    assert post(client, case, 'bookings', payload).status_code == 200


def test_atomic_idempotence_normalized_money_and_payload_conflicts(client):
    case, ids = family(client)
    accepted(client, case)
    body = evidence(kind='customer_receipt', amount='10.0', currency='TWD')
    a = post(client, case, 'ledger', body)
    b = post(client, case, 'ledger', {**body, 'amount':'10.00'})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    assert post(client, case, 'ledger', {**body, 'amount':'11.00'}).status_code == 409
    assert len(bundle(client, case)['ledger']) == 1
    failed = evidence(kind='customer_refund', amount='20', currency='TWD')
    assert post(client, case, 'ledger', failed).status_code == 409
    assert len(bundle(client, case)['ledger']) == 1
    post(client, case, 'ledger', evidence(kind='customer_receipt', amount='20', currency='TWD'))
    assert post(client, case, 'ledger', failed).status_code == 200  # Failed command was rolled back, allowing retry.


def test_concurrent_quote_versions_and_duplicate_intent_are_serialized(client):
    case, ids = family(client)
    commands = [QuoteCreate(**quote_payload()) for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda model: service.create_quote(case['id'], model, 'operator'), commands))
    assert sorted(r['version'] for r in results) == [1,2,3,4,5,6]
    same = QuoteCreate(**quote_payload())
    with ThreadPoolExecutor(max_workers=4) as pool:
        repeated = list(pool.map(lambda _: service.create_quote(case['id'], same, 'operator'), range(4)))
    assert len({q['id'] for q in repeated}) == 1 and len(bundle(client, case)['quotes']) == 7


def test_refund_void_guards_and_unmatched_currency_balance(client):
    case, ids = family(client)
    accepted(client, case)
    receipt = post(client, case, 'ledger', evidence(kind='customer_receipt', amount='100', currency='TWD')).json()
    refund = post(client, case, 'ledger', evidence(kind='customer_refund', amount='50', currency='TWD')).json()
    assert post(client, case, f"ledger/{receipt['id']}/void", evidence(reason='誤錄')).status_code == 409
    assert bundle(client, case)['ledger'][0]['status'] == 'recorded'
    assert post(client, case, f"ledger/{refund['id']}/void", evidence(reason='退款紀錄誤錄')).status_code == 200
    assert post(client, case, f"ledger/{receipt['id']}/void", evidence(reason='收款紀錄誤錄')).status_code == 200
    assert post(client, case, 'ledger', evidence(kind='supplier_refund', amount='1', currency='TWD')).status_code == 409
    post(client, case, 'ledger', evidence(kind='customer_receipt', amount='100', currency='JPY'))
    money = bundle(client, case)['balances']
    assert money['JPY']['customer_balance'] is None
    assert money['TWD']['customer_balance'] == '50100.30'
    assert money['TWD']['expected_margin'] is None


def test_all_deadlines_and_revision_conflicts_are_visible(client):
    case, ids = family(client)
    items = [post(client, case, 'work-items', intent(kind='reply', title=f'工作{i}', owner='媽媽', due_at=moment(-i), source='人工承諾')).json() for i in range(7)]
    all_items = client.get('/api/mom/work-items').json()
    assert all_items['timezone'] == 'Asia/Taipei'
    assert {i['id'] for i in items} <= {i['id'] for i in all_items['items']}
    item = items[0]
    path = f"/api/mom/cases/{case['id']}/work-items/{item['id']}"
    assert client.patch(path, json=intent(expected_revision=1, due_at=moment(2), reason='客人改回覆時間')).status_code == 200
    assert client.patch(path, json=intent(expected_revision=1, status='done', reason='已處理')).status_code == 409
    assert bundle(client, case)['work_items'][0]['status'] == 'open'


def test_stale_pretrip_is_not_deliverable_or_printable_and_private_sources_never_export(client):
    case, ids = family(client)
    accepted(client, case)
    b1, b2 = verified_booking(client, case), verified_booking(client, case, 'hotel')
    doc1 = ready_document(client, case, b1, 'e_ticket')
    ready_document(client, case, b2, 'hotel_voucher')
    pack = post(client, case, 'pretrip', intent(title='完整行前摘要')).json()
    exported = client.get(f"/api/mom/cases/{case['id']}/pretrip/{pack['id']}/document")
    assert exported.status_code == 200 and b1['confirmation_number'] in exported.text
    assert 'PRIVATE' not in exported.text
    client.patch(f"/api/mom/cases/{case['id']}/documents/{doc1['id']}", json=evidence(expected_revision=2, status='ready', customer_text='更新後的憑證內容'))
    assert bundle(client, case)['pretrip'][0]['stale']
    assert client.get(f"/api/mom/cases/{case['id']}/pretrip/{pack['id']}/document").status_code == 409
    assert post(client, case, f"pretrip/{pack['id']}/deliver", evidence(channel='Email')).status_code == 409


def test_cross_case_references_status_bypass_and_unsafe_urls_are_rejected(client):
    case, ids = family(client)
    other, other_ids = family(client)
    q = accepted(client, other)
    assert post(client, case, 'work-items', intent(kind='reply', title='錯誤關聯', owner='媽媽', due_at=moment(), source='測試', quote_id=q['id'])).status_code == 404
    for status in ['booking', 'confirmed']:
        assert client.patch(f"/api/cases/{case['id']}", json={'status':status}).status_code == 422
    accepted(client, case)
    b = verified_booking(client, case)
    doc = post(client, case, 'documents', intent(kind='e_ticket', title='機票', booking_id=b['id'])).json()
    for url in ['javascript:alert(1)', 'https://user:password@example.com/', 'http://example.com/']:
        assert client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}", json=evidence(expected_revision=1, status='ready', customer_url=url)).status_code == 422


@pytest.mark.parametrize('amount', ['NaN','Infinity','-1','0','1.001'])
def test_ledger_rejects_nonfinite_zero_negative_or_excess_precision(client, amount):
    case, ids = family(client)
    accepted(client, case)
    assert post(client, case, 'ledger', evidence(kind='customer_receipt', amount=amount, currency='TWD')).status_code == 422


def test_803_upgrade_preserves_802_case_options_and_runs_twice(client, monkeypatch, tmp_path):
    from dataclasses import replace
    import app.db as database
    case, ids = family(client)
    path = tmp_path / 'upgrade.db'
    with connect() as original:
        copied = sqlite3.connect(path)
        original.backup(copied)
        copied.close()
    with sqlite3.connect(path) as old:
        for table in ['commands','pretrip','documents','ledger','bookings','work_items','quotes']:
            old.execute(f'DROP TABLE agency_{table}')
        old.execute('DELETE FROM schema_migrations WHERE version=803')
    monkeypatch.setattr(database, 'settings', replace(database.settings, db_path=str(path)))
    init_db(); init_db()
    with connect() as upgraded:
        assert upgraded.execute('SELECT customer_name FROM trip_cases WHERE id=?',(case['id'],)).fetchone()[0] == case['customer_name']
        assert upgraded.execute('SELECT COUNT(*) FROM case_options WHERE case_id=?',(case['id'],)).fetchone()[0] == 2
        assert upgraded.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=803').fetchone()[0] == 1


def test_amend_booking_rebind_document_repair_and_customer_name(client):
    case, ids = family(client)
    first = accepted(client, case, ids)
    flights = verified_booking(client, case)
    hotel = verified_booking(client, case, 'hotel')
    ticket = ready_document(client, case, flights, 'e_ticket')
    ready_document(client, case, hotel, 'hotel_voucher')
    # Correcting a display name does not invalidate supplier travel constraints.
    assert client.patch(f"/api/cases/{case['id']}", json={'customer_name':'更正稱呼'}).status_code == 200
    assert post(client, case, 'pretrip', intent(title='姓名更正摘要')).json()['status'] == 'prepared'
    q = post(client, case, 'quotes', quote_payload(ids)).json()
    post(client, case, f"quotes/{q['id']}/sent", evidence())
    assert post(client, case, f"quotes/{q['id']}/accept", evidence(amend=True, reason='客人改採費用新版')).status_code == 200
    for b in [flights, hotel]:
        response = post(client, case, f"bookings/{b['id']}/rebind", evidence(reason='供應商確認仍適用新版',customer_details='核對日期與旅客後仍適用'))
        assert response.status_code == 200, response.text
        assert response.json()['history'][0]['before']['quote_id'] == first['id']
    assert post(client, case, 'pretrip', intent(title='改版摘要')).json()['status'] == 'draft'
    for doc in bundle(client, case)['documents']:
        assert doc['needs_recheck']
        response = client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}", json=evidence(expected_revision=doc['revision'], status='ready', customer_text='依新版訂購重新核對文件'))
        assert response.status_code == 200
    ticket['revision'] += 1
    # Mistyped record: void and replace, then rebind the required document explicitly.
    assert post(client, case, f"bookings/{flights['id']}/void", evidence(reason='確認號誤錄')).status_code == 200
    replacement = verified_booking(client, case)
    patch_url = f"/api/mom/cases/{case['id']}/documents/{ticket['id']}"
    changes = evidence(expected_revision=ticket['revision'],status='ready',customer_text='已核對',booking_id=replacement['id'])
    assert client.patch(patch_url,json=changes).status_code == 409
    changes['reason']='確認號錯誤修正後重新綁定'
    assert client.patch(patch_url,json=changes).status_code == 200
    erroneous = post(client,case,'documents',intent(kind='visa_check',title='誤加文件')).json()
    response = client.patch(f"/api/mom/cases/{case['id']}/documents/{erroneous['id']}",json=evidence(expected_revision=1,status='missing',required=False,reason='誤加非必要文件'))
    assert response.status_code == 200
    pack = post(client,case,'pretrip',intent(title='可交付')).json()
    assert pack['status'] == 'prepared'
    assert post(client,case,f"pretrip/{pack['id']}/deliver",evidence(channel='LINE')).status_code == 200
    with connect() as db:
        audit = json.loads(db.execute("SELECT payload_json FROM audit_log WHERE case_id=? AND action LIKE 'agency.%' ORDER BY id DESC LIMIT 1", (case['id'],)).fetchone()[0])
        assert 'status_before' in audit and 'status_after' in audit


def test_quote_guard_race_and_official_public_title(client, monkeypatch):
    case, ids = family(client)
    original = service.case_workflow
    def raced(case_id):
        result = original(case_id)
        client.delete(f"/api/mom/cases/{case_id}/selection/hotel")
        return result
    monkeypatch.setattr(service, 'case_workflow', raced)
    assert post(client,case,'quotes',quote_payload()).status_code == 409
    assert not bundle(client,case)['quotes']
    monkeypatch.setattr(service, 'case_workflow', original)
    client.post(f"/api/mom/cases/{case['id']}/selection",json={'option_id':ids[1]})
    def normalized_official(case_id):
        result = original(case_id)
        result['selections'][1]['source_type']='official'
        result['selections'][1]['supplier_name']='Public Hotel'
        return result
    monkeypatch.setattr(service, 'case_workflow', normalized_official)
    quote = post(client,case,'quotes',quote_payload()).json()
    assert any(item['title'].startswith('Public Hotel｜') for item in quote['items'])


def test_closed_task_timing_and_document_foreign_binding(client):
    case, ids = family(client)
    accepted(client,case,ids)
    task=post(client,case,'work-items',intent(title='已完成',kind='reply',owner='媽媽',due_at=moment(-1),source='約定')).json()
    client.patch(f"/api/mom/cases/{case['id']}/work-items/{task['id']}",json=intent(expected_revision=1,status='done',reason='已回覆'))
    assert next(i for i in client.get('/api/mom/work-items').json()['items'] if i['id']==task['id'])['timing'] is None
    other, _=family(client)
    accepted(client,other)
    foreign=verified_booking(client,other)
    doc=post(client,case,'documents',intent(title='憑證',kind='other')).json()
    assert client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}",json=evidence(expected_revision=1,status='ready',customer_text='說明',booking_id=foreign['id'],reason='錯誤關聯')).status_code == 404


def test_patch_retry_distinguishes_omitted_and_explicit_null_binding(client):
    case, ids = family(client)
    accepted(client, case, ids)
    booking = verified_booking(client, case)
    doc = ready_document(client, case, booking, 'e_ticket')
    url = f"/api/mom/cases/{case['id']}/documents/{doc['id']}"
    payload = evidence(expected_revision=2, status='ready',customer_text='更正文字',reason='人工核對文件內容')
    first = client.patch(url, json=payload)
    assert first.status_code == 200 and first.json()['booking_id'] == booking['id']
    # Missing means keep; explicit null means unbind, so cannot reuse this retry key.
    assert client.patch(url, json={**payload, 'booking_id':None}).status_code == 409
    assert client.patch(url, json=payload).json() == first.json()



def test_each_booking_needs_its_own_verified_document(client):
    case, _ = family(client)
    accepted(client, case)
    first, second, hotel = verified_booking(client, case), verified_booking(client, case), verified_booking(client, case, 'hotel')
    ready_document(client, case, first, 'e_ticket')
    ready_document(client, case, hotel, 'hotel_voucher')
    pack = post(client, case, 'pretrip', intent(title='缺第二筆機票')).json()
    assert pack['status'] == 'draft' and any(second['confirmation_number'] in b for b in pack['blockers'])
    ready_document(client, case, second, 'e_ticket')
    assert post(client, case, 'pretrip', intent(title='齊全')).json()['status'] == 'prepared'
    post(client, case, f"bookings/{second['id']}/void", evidence(reason='換訂購確認'))
    replacement = verified_booking(client, case)
    assert post(client, case, 'pretrip', intent(title='替代訂購待核对')).json()['status'] == 'draft'
    assert replacement['id'] != second['id']


def test_product_documents_require_correct_effective_binding_and_legacy_recheck(client):
    case, _ = family(client)
    accepted(client, case)
    flight, hotel = verified_booking(client, case), verified_booking(client, case, 'hotel')
    ticket = post(client, case, 'documents', intent(kind='e_ticket', title='機票')).json()
    url = f"/api/mom/cases/{case['id']}/documents/{ticket['id']}"
    assert client.patch(url, json=evidence(expected_revision=1, status='ready', customer_text='已核對')).status_code == 409
    assert client.patch(url, json=evidence(expected_revision=1, status='ready', customer_text='已核對', booking_id=hotel['id'], reason='修正訂購關聯')).status_code == 409
    response = client.patch(url, json=evidence(expected_revision=1, status='ready', customer_text='已核對', booking_id=flight['id'], reason='修正訂購關聯'))
    assert response.status_code == 200
    ready_document(client, case, hotel, 'hotel_voucher')
    # Simulate a pre-upgrade ready document and prepared pack with an unchanged hash.
    with connect() as db:
        legacy = service.record(db, 'documents', case['id'], ticket['id'])
        legacy.pop('verification')
        service.save(db, 'documents', legacy)
    pack = post(client, case, 'pretrip', intent(title='舊文件')).json()
    assert pack['status'] == 'draft'
    with connect() as db:
        pack['status'] = 'prepared'; pack['blockers'] = []
        service.save(db, 'pretrip', pack)
    assert bundle(client, case)['documents'][0]['needs_recheck']
    assert bundle(client, case)['pretrip'][0]['stale']
    assert client.get(f"/api/mom/cases/{case['id']}/pretrip/{pack['id']}/document").status_code == 409
    assert post(client, case, f"pretrip/{pack['id']}/deliver", evidence(channel='LINE')).status_code == 409
    assert client.patch(url, json=evidence(expected_revision=2, status='ready', customer_text='重新人工核對')).status_code == 200
    assert post(client, case, 'pretrip', intent(title='重新核對完成')).json()['status'] == 'prepared'


def test_trip_change_resets_status_but_display_edits_do_not_and_audit_has_actor(client):
    case, _ = family(client)
    accepted(client, case)
    flight, hotel = verified_booking(client, case), verified_booking(client, case, 'hotel')
    ready_document(client, case, flight, 'e_ticket'); ready_document(client, case, hotel, 'hotel_voucher')
    path = f"/api/cases/{case['id']}"
    assert client.patch(path, json={'depart_date':case['depart_date'], 'customer_name':'更正稱呼', 'notes':'補充'}).json()['status'] == 'confirmed'
    changed = client.patch(path, json={'adults':3, 'status':'confirmed'})
    assert changed.status_code == 200 and changed.json()['status'] == 'quoting'
    assert all(d['needs_recheck'] for d in bundle(client, case)['documents'])
    assert client.get(f"/api/mom/cases/{case['id']}").json()['next_action']['kind'] == 'case_options'
    with connect() as db:
        assert db.execute("SELECT actor FROM audit_log WHERE case_id=? AND action='case.updated' ORDER BY id DESC LIMIT 1", (case['id'],)).fetchone()[0] == 'operator'


def test_lifecycle_next_action_and_urgent_deadline_precedence(client):
    case, _ = family(client)
    def action(): return client.get(f"/api/mom/cases/{case['id']}").json()['next_action']
    assert action()['kind'] == 'quotes'
    q = post(client, case, 'quotes', quote_payload()).json()
    assert action()['kind'] == 'quotes' and '送出' in action()['label']
    post(client, case, f"quotes/{q['id']}/sent", evidence())
    assert '決定' in action()['label']
    post(client, case, f"quotes/{q['id']}/accept", evidence())
    assert action()['kind'] == 'bookings'
    flight, hotel = verified_booking(client, case), verified_booking(client, case, 'hotel')
    assert action()['kind'] == 'pretrip' and '文件' in action()['label']
    ready_document(client, case, flight, 'e_ticket'); ready_document(client, case, hotel, 'hotel_voucher')
    assert '產生' in action()['label']
    pack = post(client, case, 'pretrip', intent(title='行前資料')).json()
    assert '交付' in action()['label']
    post(client, case, f"pretrip/{pack['id']}/deliver", evidence(channel='LINE'))
    assert action()['kind'] == 'case'
    task = post(client, case, 'work-items', intent(kind='balance', title='確認尾款期限', owner='媽媽', source='客人約定', due_at=moment(-1))).json()
    assert action()['kind'] == 'tasks' and action()['record_id'] == task['id']
    home = client.get('/api/mom/home').json()
    card = next(c for c in home['priority'] if c['id'] == case['id'])
    assert card['next_action'] == action()
    client.patch(f"/api/mom/cases/{case['id']}/work-items/{task['id']}", json=intent(expected_revision=1, status='done', reason='已完成核對'))
    assert action()['kind'] == 'case'


def test_expired_optional_quote_does_not_hide_adopted_lifecycle(client):
    case, _ = family(client)
    accepted(client, case)
    verified_booking(client, case); verified_booking(client, case, 'hotel')
    pending = post(client, case, 'quotes', quote_payload()).json()
    with connect() as db:
        pending['valid_until'] = moment(-1)
        service.save(db, 'quotes', pending)
    action = client.get(f"/api/mom/cases/{case['id']}").json()['next_action']
    assert action['kind'] == 'pretrip'
    client.patch(f"/api/cases/{case['id']}", json={'status':'travelling'})
    task = post(client, case, 'work-items', intent(kind='change', title='旅途中異動', owner='媽媽', source='客人通知', due_at=moment(-1))).json()
    action = client.get(f"/api/mom/cases/{case['id']}").json()['next_action']
    assert action['kind'] == 'tasks' and action['record_id'] == task['id']


def test_non_product_document_survives_fee_only_amendment_but_not_trip_edit(client):
    case, _ = family(client)
    accepted(client, case)
    doc = post(client, case, 'documents', intent(kind='insurance', title='保險確認')).json()
    url = f"/api/mom/cases/{case['id']}/documents/{doc['id']}"
    assert client.patch(url, json=evidence(expected_revision=1, status='ready', customer_text='本次旅程保險已人工核對')).status_code == 200
    q = post(client, case, 'quotes', quote_payload()).json()
    post(client, case, f"quotes/{q['id']}/sent", evidence())
    post(client, case, f"quotes/{q['id']}/accept", evidence(amend=True, reason='服務費重新確認'))
    assert not bundle(client, case)['documents'][0]['needs_recheck']
    client.patch(f"/api/cases/{case['id']}", json={'adults':3})
    assert bundle(client, case)['documents'][0]['needs_recheck']
