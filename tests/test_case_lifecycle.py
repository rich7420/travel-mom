import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from test_case_operations import (client, family, accepted, verified_booking, ready_document,
                                  post, intent, evidence, moment, bundle)
from app.db import connect
from app.operations_models import CaseClose
from app.services import case_operations as service


def decision(client, case, **fields):
    return evidence(expected_state=bundle(client, case)['lifecycle']['expected_state'], reason='人工核對業務進度', **fields)


def completed(client, case):
    accepted(client, case)
    flight, hotel = verified_booking(client, case), verified_booking(client, case, 'hotel')
    ready_document(client, case, flight, 'e_ticket'); ready_document(client, case, hotel, 'hotel_voucher')
    pack = post(client, case, 'pretrip', intent(title='可交付資料')).json()
    assert post(client, case, f"pretrip/{pack['id']}/deliver", evidence(channel='LINE')).status_code == 200
    assert post(client, case, 'ledger', evidence(kind='customer_receipt', amount='50100.30', currency='TWD')).status_code == 200


def test_completed_close_reopen_is_atomic_immutable_and_idempotent(client):
    case, _ = family(client)
    completed(client, case)
    assert bundle(client, case)['lifecycle']['completed_blockers'] == []
    payload = decision(client, case, outcome='completed', supplier_settlement_checked=True)
    first = post(client, case, 'lifecycle/close', payload)
    assert first.status_code == 200, first.text
    assert first.json()['status'] == 'closed'
    assert post(client, case, 'lifecycle/close', payload).json() == first.json()
    assert len(bundle(client, case)['case_events']) == 1
    assert client.get(f"/api/mom/cases/{case['id']}").json()['next_action']['kind'] == 'lifecycle'
    assert post(client, case, 'lifecycle/reopen', decision(client, case)).json()['status'] == 'confirmed'
    assert len(bundle(client, case)['case_events']) == 2
    with connect() as db:
        for sql in ('UPDATE agency_case_events SET created_at=created_at WHERE case_id=?', 'DELETE FROM agency_case_events WHERE case_id=?'):
            with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                db.execute(sql, (case['id'],))
        audit = db.execute("SELECT actor,payload_json FROM audit_log WHERE case_id=? AND action='agency.case.close'", (case['id'],)).fetchall()
        assert len(audit) == 1 and audit[0][0] == 'operator'
        assert json.loads(audit[0][1])['status_after'] == 'closed'


def test_close_guards_money_work_delivery_and_attestations(client):
    case, _ = family(client)
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='completed')).status_code == 422
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='completed', supplier_settlement_checked=True)).status_code == 409
    task = post(client, case, 'work-items', intent(kind='reply', title='待回覆', owner='媽媽', due_at=moment(), source='約定')).json()
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn')).status_code == 409
    client.patch(f"/api/mom/cases/{case['id']}/work-items/{task['id']}", json=intent(expected_revision=1, status='done', reason='已回覆'))
    q = accepted(client, case)
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn')).status_code == 409
    receipt = post(client, case, 'ledger', evidence(kind='customer_receipt', amount='100', currency='JPY')).json()
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn', withdraw_adoption_checked=True)).status_code == 409
    post(client, case, 'ledger', evidence(kind='customer_refund', amount='100', currency='JPY'))
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn', withdraw_adoption_checked=True)).status_code == 200
    records = bundle(client, case)
    assert records['quotes'][0]['status'] == 'withdrawn' and records['accepted_quote_id'] is None
    assert records['case_events'][0]['withdraw_adoption_checked'] is True
    assert post(client, case, 'lifecycle/reopen', decision(client, case)).json()['status'] == 'quoting'
    assert bundle(client, case)['accepted_quote_id'] is None
    # Withdrawing the business decision never erases quote acceptance history.
    assert [e['action'] for e in bundle(client, case)['quotes'][0]['events']] == ['sent','accept','withdrawn']


def test_closed_case_blocks_generic_and_business_writes_but_preserves_reads(client):
    case, ids = family(client)
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn')).status_code == 200
    for payload in ({'notes':'旁路修改'}, {'status':'intake'}, {'status':'closed'}):
        assert client.patch(f"/api/cases/{case['id']}", json=payload).status_code == 422
    assert post(client, case, 'work-items', intent(kind='reply', title='旁路新增', owner='媽媽', due_at=moment(), source='約定')).status_code == 409
    assert client.post(f"/api/mom/cases/{case['id']}/selection",json={'option_id':ids[0]}).status_code == 409
    assert client.delete(f"/api/mom/cases/{case['id']}/selection/flight").status_code == 409
    assert client.get(f"/api/mom/cases/{case['id']}/options").status_code == 200
    assert not bundle(client, case)['work_items']
    home = client.get('/api/mom/home').json()
    cards = home['recent_cases'] + home['priority']
    assert next(c for c in cards if c['id']==case['id'])['status']=='未成交結案'
    assert post(client, case, 'lifecycle/reopen', decision(client, case)).json()['status'] == 'quoting'


def test_fingerprint_guards_sales_and_business_changes_and_concurrent_close(client):
    case, _ = family(client)
    stale = decision(client, case, outcome='withdrawn')
    client.delete(f"/api/mom/cases/{case['id']}/selection/hotel")
    assert post(client, case, 'lifecycle/close', stale).status_code == 409
    valid = CaseClose(**decision(client, case, outcome='withdrawn'))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.close_case(case['id'], valid, 'operator'), range(4)))
    assert len({r['event']['id'] for r in results}) == 1
    assert len(bundle(client, case)['case_events']) == 1
    # Retry is bound to identity, not just a UUID.
    with pytest.raises(service.OperationConflict):
        service.close_case(case['id'], valid, 'different-operator')


def test_legacy_closed_reopen_derives_current_state_without_fake_completion(client):
    case, _ = family(client)
    with connect() as db:
        db.execute("UPDATE trip_cases SET status='closed' WHERE id=?", (case['id'],))
    assert bundle(client, case)['lifecycle']['reopen_status'] == 'quoting'
    assert post(client, case, 'lifecycle/reopen', decision(client, case)).json()['status'] == 'quoting'
    assert post(client, case, 'lifecycle/reopen', decision(client, case)).status_code == 409


def test_upgrade_803_and_active_search_close_guard(client, monkeypatch, tmp_path):
    from dataclasses import replace
    import app.db as database
    from app.models import FlightSearchRequest
    from app.repositories import flight_search_run_repo
    case, _ = family(client)
    run = flight_search_run_repo.create(FlightSearchRequest(case_id=case['id'], origin='TPE', destination='NRT', depart_date=case['depart_date'], return_date=case['return_date'], adults=2))
    planned = decision(client, case, outcome='withdrawn')
    assert not bundle(client, case)['lifecycle']['withdrawn_blockers']
    flight_search_run_repo.set_status(run.id, 'running')
    assert post(client, case, 'lifecycle/close', planned).status_code == 409
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn')).status_code == 409
    evidence_payload=evidence(reason='程序已停止，查價任務卡住',worker_stopped_checked=True,expected_updated_at=flight_search_run_repo.get(run.id).updated_at)
    abandoned=client.post(f'/api/browser/runs/{run.id}/abandon',json=evidence_payload)
    assert abandoned.status_code==200,abandoned.text
    assert client.post(f'/api/browser/runs/{run.id}/abandon',json=evidence_payload).json()==abandoned.json()
    assert post(client, case, 'lifecycle/close', decision(client, case, outcome='withdrawn')).status_code == 200
    with pytest.raises(ValueError, match='結案'):
        flight_search_run_repo.set_status(run.id, 'running')
    assert client.post(f'/api/mom/flight-search/{run.id}/start').status_code==409
    path = tmp_path/'upgrade.db'
    with connect() as db:
        with sqlite3.connect(path) as dest:
            db.backup(dest)
    with sqlite3.connect(path) as old:
        old.execute('DROP TABLE agency_case_events')
        old.execute('DELETE FROM schema_migrations WHERE version=804')
    monkeypatch.setattr(database,'settings',replace(database.settings,db_path=str(path)))
    database.init_db(); database.init_db()
    with connect() as upgraded:
        assert upgraded.execute('SELECT COUNT(*) FROM schema_migrations WHERE version=804').fetchone()[0] == 1
        assert upgraded.execute('SELECT status FROM trip_cases WHERE id=?',(case['id'],)).fetchone()[0] == 'closed'
        assert upgraded.execute('SELECT COUNT(*) FROM case_options WHERE case_id=?',(case['id'],)).fetchone()[0] == 2


@pytest.mark.parametrize('kind',['flight','hotel'])
def test_planned_search_can_close_and_all_closed_search_entrypoints_reject(client, kind, monkeypatch):
    from app.models import FlightSearchRequest, HotelSearchRequest, BrowserTaskCreate
    from app.repositories import flight_search_run_repo, hotel_search_run_repo, browser_task_repo
    import app.main as main
    from dataclasses import replace
    case, _ = family(client)
    if kind=='flight':
        run=flight_search_run_repo.create(FlightSearchRequest(case_id=case['id'],origin='TPE',destination='NRT',depart_date=case['depart_date'],return_date=case['return_date'],adults=2))
        repo=flight_search_run_repo; route='runs'; url='https://www.emirates.com/tw/chinese/book/'
    else:
        run=hotel_search_run_repo.create(HotelSearchRequest(case_id=case['id'],hotel_name='Synthetic',official_url='https://www.hyatt.com/',checkin_date=case['depart_date'],checkout_date=case['return_date'],adults=2))
        repo=hotel_search_run_repo; route='hotel-runs'; url='https://www.hyatt.com/'
    task=browser_task_repo.create(BrowserTaskCreate(case_id=case['id'],search_run_id=run.id,kind=kind+'_search',source_url=url,instructions='合成任務'))
    if kind=='flight':repo.finalize_plan(run.id,[task.id],[],[])
    else:repo.finalize_plan(run.id,[task.id])
    assert post(client,case,'lifecycle/close',decision(client,case,outcome='withdrawn')).status_code==200
    monkeypatch.setattr(main,'settings',replace(main.settings,openclaw_enabled=True))
    assert client.post(f'/api/mom/{kind}-search/{run.id}/start').status_code==409
    assert client.post(f'/api/browser/{route}/{run.id}/run').status_code==409
    assert client.post(f'/api/browser/tasks/{task.id}/run').status_code==400
    with pytest.raises(ValueError,match='結案'):browser_task_repo.update(task.id,'running')
    with pytest.raises(ValueError,match='結案'):repo.select_option(run.id,task.id,'option')
    assert client.post(f'/api/browser/{route}/{run.id}/select',json={'task_id':task.id,'option_id':'synthetic'}).status_code==400
    assert client.post('/api/browser/'+('revalidate' if kind=='flight' else 'hotel-revalidate'),json={'search_task_id':task.id,'option_id':'synthetic'}).status_code==400
    import app.services.browser_tasks as task_service
    monkeypatch.setattr(task_service,'settings',replace(task_service.settings,browser_lab_ingest_enabled=True,app_env='dev'))
    ingest=client.post(f'/api/browser/tasks/{task.id}/ingest',json={'raw_text':'{}'})
    assert ingest.status_code==400 and '結案' in ingest.json()['detail']
    assert not browser_task_repo.get(task.id).result_json
    assert browser_task_repo.get(task.id).status=='queued'
    assert len(bundle(client,case)['case_events'])==1


@pytest.mark.parametrize('standalone',[False,True])
def test_crashed_revalidation_or_standalone_task_can_be_abandoned(client,standalone):
    from app.models import BrowserTaskCreate,FlightSearchRequest
    from app.repositories import browser_task_repo,flight_search_run_repo
    case,_=family(client)
    if standalone:
        run=None
    else:
        run=flight_search_run_repo.create(FlightSearchRequest(case_id=case['id'],origin='TPE',destination='NRT',depart_date=case['depart_date'],return_date=case['return_date']))
        flight_search_run_repo.set_status(run.id,'completed')
    task=browser_task_repo.create(BrowserTaskCreate(case_id=case['id'],search_run_id=run.id if run else None,kind='revalidate_price',source_url='https://www.emirates.com/tw/chinese/book/',instructions='合成重新驗價'))
    browser_task_repo.update(task.id,'running')
    assert post(client,case,'lifecycle/close',decision(client,case,outcome='withdrawn')).status_code==409
    record=browser_task_repo.get(task.id) if standalone else flight_search_run_repo.get(run.id)
    route=f'/api/browser/tasks/{task.id}/abandon' if standalone else f'/api/browser/runs/{run.id}/abandon'
    payload=evidence(reason='程序已重啟，核對卡住任務',worker_stopped_checked=True,expected_updated_at=record.updated_at)
    assert client.post(route,json={**payload,'expected_updated_at':'stale'}).status_code==409
    assert client.post(route,json={k:v for k,v in payload.items() if k!='worker_stopped_checked'}).status_code==422
    result=client.post(route,json=payload)
    assert result.status_code==200,result.text
    assert client.post(route,json=payload).json()==result.json()
    assert browser_task_repo.get(task.id).status=='failed'
    assert post(client,case,'lifecycle/close',decision(client,case,outcome='withdrawn')).status_code==200
