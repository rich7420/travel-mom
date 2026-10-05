"""Service facts, approvals and actual cash must survive retries and correction."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest

from test_case_operations import (client, family, accepted, verified_booking, ready_document,
                                  post, intent, evidence, moment, bundle)
from test_case_lifecycle import decision
from app.db import connect, init_db
from app.service_order_models import ServiceSettlement
from app.services import service_orders


@pytest.fixture(autouse=True)
def isolate_service_case_priority(client):
    # The legacy suite shares one DB. Do not leave our synthetic due-today orders
    # competing with later tests' four-card priority assertions.
    with connect() as db:
        before={r[0] for r in db.execute('SELECT id FROM trip_cases')}
    yield
    with connect() as db:
        new=[r[0] for r in db.execute('SELECT id FROM trip_cases') if r[0] not in before]
        db.executemany("UPDATE trip_cases SET status='closed' WHERE id=?",[(cid,) for cid in new])


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def create(client, case, kind='incident', bookings=()):
    return ok(post(client, case, 'service-orders', evidence(kind=kind, title='合成服務工作單',
        request_details='客人實際需求', owner='媽媽', due_at=moment(2), booking_ids=[b['id'] for b in bookings])))


def action(client, case, order, suffix, **fields):
    return post(client, case, f"service-orders/{order['id']}/{suffix}", evidence(expected_revision=order['revision'], **fields))


def assessed(client, case, order, amounts=(), **extra):
    return ok(action(client, case, order, 'assessment', supplier_reply='已與供應商核對', proposal='已列完整方案',
        terms_reference='本訂購適用合約與供應商通知', valid_until=moment(2), reason='人工核對', amounts=list(amounts), **extra))


def start(client, case, order):
    order=ok(action(client, case, order, 'decision', assessment_revision=order['assessment']['revision'], decision='approved', customer_reply='客人確認採用'))
    return ok(action(client, case, order, 'progress', stage='start'))


def result(client, case, order, **fields):
    if order['kind'] == 'change' and 'booking_revisions' not in fields:
        current = {b['id']: b['revision'] for b in bundle(client, case)['bookings']}
        fields['booking_revisions'] = {bid: current[bid] for bid in fields.get('result_booking_ids', [])}
    return ok(action(client, case, order, 'progress', stage='supplier_result', outcome='confirmed', details='供應商實際完成通知', **fields))


def resolve(client, case, order, **fields):
    return action(client, case, order, 'resolve', summary='已處理並回覆客人', customer_notified_checked=True, **fields)


def test_cancel_retained_fee_split_refunds_and_business_close(client):
    case,_=family(client);accepted(client,case)
    bookings=[verified_booking(client,case),verified_booking(client,case,'hotel')]
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='10000',currency='TWD')))
    ok(post(client,case,'ledger',evidence(kind='supplier_payment',amount='8000',currency='TWD')))
    order=create(client,case,'cancellation',bookings)
    order=start(client,case,assessed(client,case,order,[{'currency':'TWD','customer_refund':'8500','supplier_refund':'7000','supplier_fee':'1000','agency_fee':'500','final_customer_due':'1500'}]))
    # A single bad target revision must roll back every supplier cancellation.
    bad=action(client,case,order,'progress',stage='supplier_result',outcome='confirmed',details='確認取消',booking_revisions={b['id']:99 if i else b['revision'] for i,b in enumerate(bookings)})
    assert bad.status_code==409 and all(b['status']=='confirmed' for b in bundle(client,case)['bookings'])
    order=result(client,case,order,booking_revisions={b['id']:b['revision'] for b in bookings})
    assert all(b['status']=='voided' and b['void_kind']=='supplier_cancelled' for b in bundle(client,case)['bookings'])
    assert post(client,case,'ledger',evidence(kind='customer_refund',amount='100',currency='TWD')).status_code==409
    assert resolve(client,case,order,end_trip=True).status_code==409
    for kind,amount in [('supplier_refund','7000'),('customer_refund','4000'),('customer_refund','4500')]:
        order=ok(action(client,case,order,'settlement',kind=kind,amount=amount,currency='TWD'))
    order=ok(resolve(client,case,order,end_trip=True))
    b=bundle(client,case)
    assert b['balances']['TWD']['quote_total']=='50100.30'
    assert b['balances']['TWD']['expected_customer_total']=='1500.00' and b['balances']['TWD']['customer_balance']=='0.00'
    assert not b['lifecycle']['cancelled_blockers'] and b['lifecycle']['withdrawn_blockers']
    assert ok(post(client,case,'lifecycle/close',decision(client,case,outcome='cancelled',supplier_settlement_checked=True,withdraw_adoption_checked=True)))['status']=='closed'
    assert action(client,case,order,'reopen',reason='再處理').status_code==409
    assert ok(post(client,case,'lifecycle/reopen',decision(client,case)))['status']=='intake'
    assert bundle(client,case)['service_orders'][0]['supplier_result']==order['supplier_result']


def test_incident_immediate_assistance_and_quote_free_cash(client):
    case=ok(client.post('/api/cases',json={'customer_name':'旅中合成事件','adults':1}))
    order=create(client,case)
    assert resolve(client,case,order).status_code==409
    order=ok(action(client,case,order,'progress',stage='safety_assistance',message='已協助聯絡醫療與緊急窗口'))
    order=ok(resolve(client,case,order))
    assert not bundle(client,case)['lifecycle']['completed_blockers']
    order=ok(action(client,case,order,'reopen',reason='需處理後續支出'))
    order=start(client,case,assessed(client,case,order,[{'currency':'JPY','customer_receipt':'300','supplier_payment':'200','final_customer_due':'300'}]))
    order=result(client,case,order)
    for kind,amount in [('customer_receipt','300'),('supplier_payment','200')]:
        order=ok(action(client,case,order,'settlement',kind=kind,amount=amount,currency='JPY'))
    order=ok(resolve(client,case,order))
    assert bundle(client,case)['ledger'][0]['quote_id'] is None
    assert not bundle(client,case)['lifecycle']['completed_blockers']
    assert post(client,case,'lifecycle/close',decision(client,case,outcome='completed',supplier_settlement_checked=True)).status_code==200


def test_refund_caps_uuid_race_void_and_irreversible_reassessment(client):
    case,_=family(client);accepted(client,case)
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='100',currency='TWD')))
    order=start(client,case,assessed(client,case,create(client,case,'refund'),[{'currency':'TWD','customer_refund':'90','final_customer_due':'10'}]))
    order=result(client,case,order)
    assert action(client,case,order,'settlement',kind='customer_refund',amount='91',currency='TWD').status_code==409
    payload=evidence(expected_revision=order['revision'],kind='customer_refund',amount='90',currency='TWD')
    model=ServiceSettlement(**payload)
    with ThreadPoolExecutor(max_workers=4) as pool:
        values=list(pool.map(lambda _:service_orders.settle(case['id'],order['id'],model,'operator'),range(4)))
    assert len({v['revision'] for v in values})==1
    order=values[0];order=ok(resolve(client,case,order,end_trip=True))
    linked=next(e for e in bundle(client,case)['ledger'] if e.get('service_order_id'))
    ok(post(client,case,f"ledger/{linked['id']}/void",evidence(reason='金額誤植')))
    b=bundle(client,case);order=b['service_orders'][0]
    assert not order['cash']['current'] and order['revision']==values[0]['revision']+2
    assert b['lifecycle']['cancelled_blockers']
    order=ok(action(client,case,order,'reopen',reason='更正實際款項'))
    permanent=order['supplier_result']
    order=assessed(client,case,order,[{'currency':'TWD','customer_refund':'80','final_customer_due':'20'}])
    assert order['supplier_result']==permanent
    order=start(client,case,order)
    order=ok(action(client,case,order,'settlement',kind='customer_refund',amount='80',currency='TWD'))
    assert ok(resolve(client,case,order,end_trip=True))['supplier_result']==permanent
    receipt=client.get(f"/api/mom/cases/{case['id']}/service-order-receipts/{payload['request_id']}")
    assert receipt.json()=={'committed':True,'order_id':order['id']}


def test_stale_expired_cross_case_decline_withdraw_and_deadlines(client):
    case,_=family(client);accepted(client,case);book=verified_booking(client,case)
    order=create(client,case,'change',[book])
    deadlines=client.get('/api/mom/work-items').json()['items']
    assert any(t.get('service_order_id')==order['id'] and t['source']=='service_order' for t in deadlines)
    other,_=family(client);accepted(client,other)
    assert post(client,other,'service-orders',evidence(kind='change',title='錯誤關聯',request_details='不屬於本案',owner='媽媽',due_at=moment(1),booking_ids=[book['id']])).status_code==404
    order=assessed(client,case,order)
    ok(client.patch('/api/cases/'+case['id'],json={'depart_date':'2027-10-01','return_date':'2027-10-05'}))
    assert action(client,case,order,'decision',assessment_revision=order['assessment']['revision'],decision='approved',customer_reply='過期採用').status_code==409
    order=assessed(client,case,order)
    with connect() as db:
        value=json.loads(db.execute('SELECT payload_json FROM agency_service_orders WHERE id=?',(order['id'],)).fetchone()[0]);value['assessment']['valid_until']=moment(-1)
        db.execute('UPDATE agency_service_orders SET payload_json=? WHERE id=?',(json.dumps(value),order['id']))
    assert action(client,case,order,'decision',assessment_revision=order['assessment']['revision'],decision='approved',customer_reply='過期採用').status_code==409
    order=assessed(client,case,order)
    order=ok(action(client,case,order,'decision',assessment_revision=order['assessment']['revision'],decision='declined',customer_reply='暫不採用'))
    assert order['status']=='declined'
    order=ok(action(client,case,order,'reopen',reason='改詢其他日期'))
    order=ok(action(client,case,order,'progress',stage='withdraw',reason='客人撤回'))
    assert order['status']=='withdrawn'


def test_supplier_refusal_can_close_after_corrective_plan_without_undo(client):
    case,_=family(client);accepted(client,case);book=verified_booking(client,case)
    order=start(client,case,assessed(client,case,create(client,case,'cancellation',[book]),[{'currency':'TWD','customer_refund':'100','final_customer_due':'50000.30'}]))
    order=ok(action(client,case,order,'progress',stage='supplier_result',outcome='declined',details='供應商拒絕取消'))
    assert resolve(client,case,order).status_code==409
    order=assessed(client,case,order,[{'currency':'TWD','final_customer_due':'50100.30'}]);order=start(client,case,order)
    order=ok(resolve(client,case,order))
    assert order['status']=='supplier_declined' and bundle(client,case)['bookings'][0]['status']=='confirmed'


def test_change_requires_updated_delivery_and_805_hash_survives_migration(client):
    case,_=family(client);accepted(client,case)
    books=[verified_booking(client,case),verified_booking(client,case,'hotel')]
    for b,k in zip(books,['e_ticket','hotel_voucher']):ready_document(client,case,b,k)
    pack=ok(post(client,case,'pretrip',intent(title='原行前資料')))
    ok(post(client,case,f"pretrip/{pack['id']}/deliver",evidence(channel='LINE')))
    # Actual 805 state has no service table or migration marker. Upgrade is additive.
    with connect() as db:
        db.execute('DROP TABLE agency_service_orders');db.execute('DELETE FROM schema_migrations WHERE version=806')
    init_db();init_db()
    assert not bundle(client,case)['pretrip'][0]['stale']
    order=create(client,case,'change',[books[0]])
    assert bundle(client,case)['pretrip'][0]['stale']
    assert client.get(f"/api/mom/cases/{case['id']}/pretrip/{pack['id']}/document").status_code==409
    order=start(client,case,assessed(client,case,order))
    updated=ok(post(client,case,f"bookings/{books[0]['id']}/rebind",evidence(reason='供應商完成異動',customer_details='核對異動後機票')))
    order=result(client,case,order,result_booking_ids=[updated['id']])
    assert resolve(client,case,order).status_code==409
    # Recheck all document proof after the real booking revision changed.
    for doc in bundle(client,case)['documents']:
        ok(client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}",json=evidence(expected_revision=doc['revision'],status='ready',customer_text='已核對新版文件')))
    new=ok(post(client,case,'pretrip',intent(title='新版行前資料')))
    assert new['status']=='prepared'
    assert resolve(client,case,order).status_code==409
    ok(post(client,case,f"pretrip/{new['id']}/deliver",evidence(channel='LINE')))
    assert ok(resolve(client,case,order))['status']=='completed'


def test_open_cancellation_is_next_action_even_before_deadline_and_preserves_prior_void(client):
    case,_=family(client);accepted(client,case);book=verified_booking(client,case)
    order=create(client,case,'cancellation',[book])
    order=start(client,case,assessed(client,case,order,[{'currency':'TWD','final_customer_due':'0'}]))
    order=ok(client.patch(f"/api/mom/cases/{case['id']}/service-orders/{order['id']}",json=evidence(expected_revision=order['revision'],owner='媽媽',due_at=moment(120),urgency='normal',reason='追蹤供應商')))
    original=ok(post(client,case,f"bookings/{book['id']}/void",evidence(reason='原確認填错，人工作廢')))
    order=result(client,case,order,booking_revisions={book['id']:original['revision']})
    current=bundle(client,case)['bookings'][0]
    assert current['void_reason']==original['void_reason'] and current['revision']==original['revision']
    next_action=client.get(f"/api/mom/cases/{case['id']}").json()['next_action']
    assert next_action['kind']=='service_orders' and next_action['record_id']==order['id']


def test_change_binding_correction_appends_without_replacing_supplier_result(client):
    case,_=family(client);accepted(client,case);book=verified_booking(client,case)
    order=start(client,case,assessed(client,case,create(client,case,'change',[book])))
    updated=ok(post(client,case,f"bookings/{book['id']}/rebind",evidence(reason='異動確認',customer_details='新內容')))
    order=result(client,case,order,result_booking_ids=[updated['id']]);permanent=order['supplier_result']
    later=ok(post(client,case,f"bookings/{book['id']}/rebind",evidence(reason='訂購姓名更正核對',customer_details='新內容已更正')))
    assert any('實際訂購結果已變更' in text for text in bundle(client,case)['service_orders'][0]['resolution_blockers'])
    order=ok(action(client,case,order,'progress',stage='rebind_result',details='供應商已重新核對姓名更正',result_booking_ids=[later['id']],booking_revisions={later['id']:later['revision']}))
    assert order['supplier_result']==permanent and order['result_bindings']=={later['id']:later['revision']}
    assert order['history'][-1]['action']=='rebind_result'
    assert not any('實際訂購結果已變更' in text for text in bundle(client,case)['service_orders'][0]['resolution_blockers'])


def test_partial_cancellation_quote_amendment_and_stale_financial_binding(client):
    from test_case_operations import quote_payload
    case,_=family(client);accepted(client,case)
    flight=verified_booking(client,case);hotel=verified_booking(client,case,'hotel')
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='10000',currency='TWD')))
    order=create(client,case,'cancellation',[hotel])
    assert client.delete(f"/api/mom/cases/{case['id']}/selection/hotel").status_code==200
    payload=quote_payload()
    q=ok(post(client,case,'quotes',payload));ok(post(client,case,f"quotes/{q['id']}/sent",evidence()));ok(post(client,case,f"quotes/{q['id']}/accept",evidence(amend=True,reason='已說明取消影響')))
    ok(post(client,case,f"bookings/{flight['id']}/rebind",evidence(reason='保留機票核對',customer_details='核對目前僅機票方案')))
    order=start(client,case,assessed(client,case,order,[{'currency':'TWD','customer_refund':'2000','final_customer_due':'30600.10','agency_fee':'500'}]))
    order=result(client,case,order,booking_revisions={hotel['id']:hotel['revision']})
    order=ok(action(client,case,order,'settlement',kind='customer_refund',amount='2000',currency='TWD'))
    order=ok(resolve(client,case,order))
    assert not order['end_trip'] and bundle(client,case)['balances']['TWD']['expected_customer_total']=='30600.10'
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='22600.10',currency='TWD')))
    ready_document(client,case,flight,'e_ticket')
    pack=ok(post(client,case,'pretrip',intent(title='保留機票新版行前')));ok(post(client,case,f"pretrip/{pack['id']}/deliver",evidence(channel='LINE')))
    assert not bundle(client,case)['lifecycle']['completed_blockers']
    # A later adopted quote cannot silently inherit the previous order's final due.
    payload=quote_payload()
    newer=ok(post(client,case,'quotes',payload));ok(post(client,case,f"quotes/{newer['id']}/sent",evidence()));ok(post(client,case,f"quotes/{newer['id']}/accept",evidence(amend=True,reason='新條件已確認')))
    assert not bundle(client,case)['service_orders'][0]['financial_current']
    assert any('重新開單核對' in text for text in bundle(client,case)['lifecycle']['completed_blockers'])


def test_immediate_incident_does_not_complete_unfinished_sales_case(client):
    case,_=family(client)
    order=create(client,case);order=ok(action(client,case,order,'progress',stage='safety_assistance',message='已提供協助'));ok(resolve(client,case,order))
    assert bundle(client,case)['lifecycle']['completed_blockers']


def test_full_refund_withdraw_reopen_close_preserves_finished_order(client):
    case,_=family(client);accepted(client,case)
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='100',currency='TWD')))
    order=start(client,case,assessed(client,case,create(client,case,'refund'),[{'currency':'TWD','customer_refund':'100','final_customer_due':'0'}]))
    order=result(client,case,order);order=ok(action(client,case,order,'settlement',kind='customer_refund',amount='100',currency='TWD'));order=ok(resolve(client,case,order))
    ok(post(client,case,'lifecycle/close',decision(client,case,outcome='withdrawn',withdraw_adoption_checked=True)))
    assert not any(t.get('service_order_id')==order['id'] for t in client.get('/api/mom/work-items').json()['items'])
    ok(post(client,case,'lifecycle/reopen',decision(client,case)))
    assert not bundle(client,case)['lifecycle']['withdrawn_blockers']
    assert bundle(client,case)['service_orders'][0]['revision']==order['revision']
    ok(post(client,case,'lifecycle/close',decision(client,case,outcome='withdrawn')))


def test_sequential_changes_only_latest_final_due_needs_current_quote(client):
    from test_case_operations import quote_payload
    case,_=family(client);accepted(client,case)
    flight=verified_booking(client,case);hotel=verified_booking(client,case,'hotel')
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='50100.30',currency='TWD')))
    first=None
    for sequence in range(2):
        order=create(client,case,'change',[flight])
        q=ok(post(client,case,'quotes',quote_payload()));ok(post(client,case,f"quotes/{q['id']}/sent",evidence()));ok(post(client,case,f"quotes/{q['id']}/accept",evidence(amend=True,reason='客人確認本次異動新版')))
        hotel=ok(post(client,case,f"bookings/{hotel['id']}/rebind",evidence(reason='保留飯店核對本版',customer_details='正式飯店內容')))
        order=start(client,case,assessed(client,case,order,[{'currency':'TWD','final_customer_due':'50100.30'}]))
        flight=ok(post(client,case,f"bookings/{flight['id']}/rebind",evidence(reason='機票異動核對本版',customer_details='正式異動內容')))
        order=result(client,case,order,result_booking_ids=[flight['id']])
        if sequence==0:
            ready_document(client,case,flight,'e_ticket');ready_document(client,case,hotel,'hotel_voucher')
        else:
            for doc in bundle(client,case)['documents']:
                ok(client.patch(f"/api/mom/cases/{case['id']}/documents/{doc['id']}",json=evidence(expected_revision=doc['revision'],status='ready',customer_text='本版文件已核對')))
        pack=ok(post(client,case,'pretrip',intent(title='目前行前資料')));ok(post(client,case,f"pretrip/{pack['id']}/deliver",evidence(channel='LINE')))
        order=ok(resolve(client,case,order))
        if first is None:first=order
    b=bundle(client,case)
    assert all(o['financial_current'] for o in b['service_orders'])
    assert next(o for o in b['service_orders'] if o['id']==first['id'])['revision']==first['revision']
    assert not b['lifecycle']['completed_blockers']
    ok(post(client,case,'lifecycle/close',decision(client,case,outcome='completed',supplier_settlement_checked=True)))


def test_money_supersession_is_per_currency_and_keeps_stale_deadlines(client):
    from test_case_operations import quote_payload
    case,_=family(client);accepted(client,case)
    first=start(client,case,assessed(client,case,create(client,case,'refund'),[
        {'currency':'TWD','final_customer_due':'40000'}, {'currency':'JPY','final_customer_due':'0'}]))
    first=ok(resolve(client,case,result(client,case,first)))
    quote=ok(post(client,case,'quotes',quote_payload()))
    ok(post(client,case,f"quotes/{quote['id']}/sent",evidence()))
    ok(post(client,case,f"quotes/{quote['id']}/accept",evidence(amend=True,reason='客人確認新版條件')))
    for currency in ['JPY','TWD']:
        order=start(client,case,assessed(client,case,create(client,case),[
            {'currency':currency,'final_customer_due':'0' if currency=='JPY' else '45000'}]))
        ok(resolve(client,case,result(client,case,order)))
        current=bundle(client,case)
        historical=next(o for o in current['service_orders'] if o['id']==first['id'])
        assert historical['financial_current'] is (currency=='TWD')
        assert historical['revision']==first['revision']
        tasks=client.get('/api/mom/work-items').json()['items']
        assert any(t.get('service_order_id')==first['id'] for t in tasks) is (currency=='JPY')
        if currency=='JPY':
            assert current['balances']['TWD']['expected_customer_total']=='50100.30'
            assert any('重新開單核對' in text for text in current['lifecycle']['completed_blockers'])
        else:
            assert current['balances']['TWD']['expected_customer_total']=='45000.00'
            assert not any('重新開單核對' in text for text in current['lifecycle']['completed_blockers'])


def test_voided_latest_money_does_not_restore_old_final_due(client):
    case,_=family(client);quote=accepted(client,case)
    old=start(client,case,assessed(client,case,create(client,case),[{'currency':'TWD','final_customer_due':'40000'}]))
    old=ok(resolve(client,case,result(client,case,old)))
    newer=start(client,case,assessed(client,case,create(client,case),[{'currency':'TWD','customer_receipt':'100','final_customer_due':'45000'}]))
    newer=result(client,case,newer)
    newer=ok(action(client,case,newer,'settlement',kind='customer_receipt',amount='100',currency='TWD'))
    newer=ok(resolve(client,case,newer))
    linked=next(e for e in bundle(client,case)['ledger'] if e.get('service_order_id')==newer['id'])
    ok(post(client,case,f"ledger/{linked['id']}/void",evidence(reason='原金額誤植')))
    current=bundle(client,case)
    assert current['balances']['TWD']['expected_customer_total']==quote['totals']['TWD']
    assert not next(o for o in current['service_orders'] if o['id']==newer['id'])['financial_current']
    assert any('重新開單核對' in text for text in current['lifecycle']['completed_blockers'])


def test_cancelled_case_reopen_retains_latest_refund_final_due(client):
    case,_=family(client);accepted(client,case)
    ok(post(client,case,'ledger',evidence(kind='customer_receipt',amount='100',currency='TWD')))
    cancel=start(client,case,assessed(client,case,create(client,case,'refund'),[{'currency':'TWD','final_customer_due':'100'}]))
    ok(resolve(client,case,result(client,case,cancel),end_trip=True))
    refund=start(client,case,assessed(client,case,create(client,case,'refund'),[{'currency':'TWD','customer_refund':'20','final_customer_due':'80'}]))
    refund=result(client,case,refund)
    refund=ok(action(client,case,refund,'settlement',kind='customer_refund',amount='20',currency='TWD'))
    ok(resolve(client,case,refund))
    ok(post(client,case,'lifecycle/close',decision(client,case,outcome='cancelled',supplier_settlement_checked=True,withdraw_adoption_checked=True)))
    ok(post(client,case,'lifecycle/reopen',decision(client,case)))
    current=bundle(client,case)
    assert current['balances']['TWD']['expected_customer_total']=='80.00'
    assert current['balances']['TWD']['customer_balance']=='0.00'
    assert not current['lifecycle']['cancelled_blockers']
    ok(post(client,case,'lifecycle/close',decision(client,case,outcome='cancelled',supplier_settlement_checked=True)))


def test_change_result_and_rebind_require_reviewed_booking_revisions(client):
    case,_=family(client);accepted(client,case);book=verified_booking(client,case)
    order=start(client,case,assessed(client,case,create(client,case,'change',[book])))
    reviewed=ok(post(client,case,f"bookings/{book['id']}/rebind",evidence(reason='完成異動核對',customer_details='已核對 A')))
    payload=evidence(expected_revision=order['revision'],stage='supplier_result',outcome='confirmed',details='已核對 A',
                     result_booking_ids=[book['id']],booking_revisions={book['id']:reviewed['revision']})
    later=ok(post(client,case,f"bookings/{book['id']}/rebind",evidence(reason='另一頁更正',customer_details='尚未核對 B')))
    endpoint=f"service-orders/{order['id']}/progress"
    for revisions in [{}, {book['id']:reviewed['revision']}, {book['id']:later['revision'],'foreign':1}]:
        assert post(client,case,endpoint,{**payload,'request_id':intent()['request_id'],'booking_revisions':revisions}).status_code==409
        current=bundle(client,case)['service_orders'][0]
        assert current['revision']==order['revision'] and current['history']==order['history']
        assert current['supplier_result'] is None
    for invalid in [True, -1, 1.5]:
        assert post(client,case,endpoint,{**payload,'request_id':intent()['request_id'],'booking_revisions':{book['id']:invalid}}).status_code==422
    order=ok(post(client,case,endpoint,{**payload,'booking_revisions':{book['id']:later['revision']}}))
    permanent=order['supplier_result']
    another=ok(post(client,case,f"bookings/{book['id']}/rebind",evidence(reason='再次核對更正',customer_details='新版 C')))
    rebinding=dict(stage='rebind_result',details='已核對 B',result_booking_ids=[book['id']])
    assert action(client,case,order,'progress',**rebinding).status_code==422
    assert action(client,case,order,'progress',**rebinding,booking_revisions={book['id']:later['revision']}).status_code==409
    current=bundle(client,case)['service_orders'][0]
    assert current['revision']==order['revision'] and current['history']==order['history']
    order=ok(action(client,case,order,'progress',**rebinding,booking_revisions={book['id']:another['revision']}))
    assert order['supplier_result']==permanent
    assert order['result_bindings']=={book['id']:another['revision']}


@pytest.mark.parametrize('manual_status,expected', [('confirmed','booking'),('travelling','travelling'),('intake','intake')])
@pytest.mark.parametrize('full', [False,True])
def test_supplier_cancellation_updates_booking_status_preserving_manual_progress(client,manual_status,expected,full):
    case,_=family(client);accepted(client,case)
    books=[verified_booking(client,case),verified_booking(client,case,'hotel')]
    assert client.patch(f"/api/cases/{case['id']}",json={'status':manual_status}).status_code==200
    targets=books if full else books[1:]
    order=start(client,case,assessed(client,case,create(client,case,'cancellation',targets)))
    result(client,case,order,booking_revisions={b['id']:b['revision'] for b in targets})
    current=bundle(client,case)
    assert current['case']['status']==expected
    assert sum(b['status']=='confirmed' for b in current['bookings'])==(0 if full else 1)
    next_action=client.get(f"/api/mom/cases/{case['id']}").json()['next_action']
    assert next_action['kind']=='service_orders' and next_action['record_id']==order['id']
