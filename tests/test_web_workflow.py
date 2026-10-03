from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AgentReply


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def create_case(client, **changes):
    payload = dict(customer_name=f'測試客人-{uuid4().hex[:8]}',destination='東京',origin='TPE',
                   depart_date='2026-10-18',return_date='2026-10-22',adults=2,children=0)
    response = client.post('/api/cases',json={**payload, **changes})
    assert response.status_code == 200, response.text
    return response.json()


def manual_payload(**changes):
    return {
        'kind':'flight','supplier_name':'測試供應商','title':'測試來回機票',
        'total_amount':'30000.10','currency':'TWD','details':'全案兩位成人來回機票，含托運行李。',
        'conditions':'改退需另確認，尚未訂購。','source_reference':'合成測試報價',
        'observed_at':datetime.now(timezone.utc).isoformat(),'confirmed_for_case':True,**changes,
    }


def add_option(client,case,**changes):
    response = client.post(f"/api/mom/cases/{case['id']}/options",json=manual_payload(**changes))
    assert response.status_code == 200, response.text
    return response.json()


def select(client,case,option):
    return client.post(f"/api/mom/cases/{case['id']}/selection",json={'option_id':option['id']})


def draft(client,case):
    response=client.post('/api/customer-reply',json={'case_id':case['id'],'incoming_text':'請提供機票與飯店方案'})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('patch',[
    {'adults':-1},{'status':'bogus'},{'return_date':'2026-10-01'}, {'adults':None},
    {'customer_name':'  '}, {'children':1,'children_ages':[]}, {'infants':3}, {'unknown_field':1},
])
def test_invalid_patch_is_rejected_without_corrupting_record(client,patch):
    case=create_case(client)
    response=client.patch(f"/api/cases/{case['id']}",json=patch)
    assert response.status_code == 422, response.text
    assert client.get(f"/api/cases/{case['id']}").json()==case
    assert client.get('/api/cases').status_code == 200
    assert client.get('/api/mom/home').status_code == 200


def test_patch_can_clear_nullable_fields_and_save_family(client):
    case=create_case(client)
    response=client.patch(f"/api/cases/{case['id']}",json={'children':1,'children_ages':[7],'infants':1,'budget_twd':None,'notes':'靠近車站'})
    assert response.status_code == 200
    saved=client.get(f"/api/cases/{case['id']}").json()
    assert (saved['children'],saved['children_ages'],saved['infants'])==(1,[7],1)
    assert saved['budget_twd'] is None


def test_guided_start_after_completion_creates_three_distinct_cases(client):
    session='web-'+uuid4().hex
    ids=[]
    for name in ['測試一','測試二','測試三']:
        started=client.post(f'/api/guided/{session}/start').json()
        assert not started['done'] and started['next_field']=='customer_name'
        for text in [name,'東京','2026-10-18','2026-10-22','2大1小1嬰兒','10萬內']:
            done=client.post(f'/api/guided/{session}/reply',json={'text':text})
            assert done.status_code==200
        assert done.json()['done']
        ids.append(done.json()['case_id'])
        assert client.get(f'/api/guided/{session}/resume').json()['case_id']==ids[-1]
        # Replayed final answer does not create another case.
        assert client.post(f'/api/guided/{session}/reply',json={'text':'10萬內'}).json()['case_id']==ids[-1]
    assert len(set(ids))==3
    for case_id in ids:
        assert client.get(f'/api/cases/{case_id}').json()['infants']==1


def test_intake_unknown_group_size_and_bad_budget_stay_on_question(client):
    session='invalid-'+uuid4().hex
    client.post(f'/api/guided/{session}/start')
    for text in ['測試','東京','2026-10-18','2026-10-22']:
        client.post(f'/api/guided/{session}/reply',json={'text':text})
    for text in ['團體','0大1小','999大','不知道']:
        assert client.post(f'/api/guided/{session}/reply',json={'text':text}).json()['next_field']=='travelers'
    client.post(f'/api/guided/{session}/reply',json={'text':'2大1小'})
    assert client.post(f'/api/guided/{session}/reply',json={'text':'-5'}).json()['next_field']=='budget_twd'


def test_manual_options_selection_and_local_reply_persist_without_openclaw(client):
    case=create_case(client)
    flight=add_option(client,case)
    hotel=add_option(client,case,kind='hotel',title='測試雙床房',total_amount='20000.20',details='一間房四晚，含早餐。')
    assert select(client,case,flight).status_code==200
    assert select(client,case,hotel).status_code==200
    # New application lifespan simulates reopening the desk; selections live in SQLite.
    with TestClient(app) as reopened:
        workflow=reopened.get(f"/api/mom/cases/{case['id']}/options").json()
        assert workflow['can_draft_offer'] and len(workflow['selections'])==2
        reply=draft(reopened,case)
    assert reply['source']=='template' and not reply['degraded']
    assert 'TWD 50,000.30' in reply['text']
    assert '合成測試報價' not in reply['text'] and '台北時間' in reply['text']
    assert '人工查核的供應商報價' in reply['text']
    assert '尚未保留或完成訂購' in reply['text']
    assert 'OpenClaw' not in reply['text']
    detail=client.get(f"/api/mom/cases/{case['id']}").json()
    assert detail['next_action']['kind']=='customer_reply'


def test_case_changes_invalidate_selected_prices_and_cannot_reselect(client):
    case=create_case(client)
    option=add_option(client,case)
    assert select(client,case,option).status_code==200
    assert client.patch(f"/api/cases/{case['id']}",json={'adults':3}).status_code==200
    workflow=client.get(f"/api/mom/cases/{case['id']}/options").json()
    assert not workflow['can_draft_offer'] and not workflow['selections'][0]['usable']
    assert select(client,case,option).status_code==409
    assert '30,000.10' not in draft(client,case)['text']
    replacement=add_option(client,case,total_amount='40000')
    assert select(client,case,replacement).status_code==200
    assert '40,000.00' in draft(client,case)['text']


def test_mixed_currencies_are_never_added(client):
    case=create_case(client)
    select(client,case,add_option(client,case))
    select(client,case,add_option(client,case,kind='hotel',currency='JPY',total_amount='50000'))
    text=draft(client,case)['text']
    assert '幣別不同' in text and '未換算合計' in text
    assert '80,000' not in text


def test_expired_and_foreign_case_options_cannot_be_selected(client):
    case=create_case(client)
    expired=add_option(client,case,observed_at=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),valid_until=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat())
    assert select(client,case,expired).status_code==409
    other=create_case(client)
    option=add_option(client,case)
    assert select(client,other,option).status_code==404
    assert client.get(f"/api/mom/cases/{other['id']}/options").json()['selections']==[]


@pytest.mark.parametrize('changes',[
    {'total_amount':'NaN'}, {'total_amount':'-1'}, {'source_url':'javascript:alert(1)'},
    {'source_url':'https://user:password@example.com/'}, {'source_reference':'   '},
    {'confirmed_for_case':False}, {'observed_at':'2026-10-03T10:00:00'},
])
def test_manual_option_rejects_incomplete_or_unsafe_evidence(client,changes):
    case=create_case(client)
    response=client.post(f"/api/mom/cases/{case['id']}/options",json=manual_payload(**changes))
    assert response.status_code==422
    assert client.get(f"/api/mom/cases/{case['id']}/options").json()['options']==[]


def test_family_hotel_search_does_not_drop_children_or_infants(client):
    case=create_case(client,children=1,children_ages=[7],infants=1)
    payload={'case_id':case['id'],'hotel_name':'Hilton Tokyo','official_url':'https://www.hilton.com/',
             'checkin_date':'2026-10-18','checkout_date':'2026-10-22','adults':2}
    for ages in [[],[7],[7,5],[6,1]]:
        assert client.post('/api/browser/hotel-search',json={**payload,'children_ages':ages}).status_code==422
    valid=client.post('/api/browser/hotel-search',json={**payload,'children_ages':[7,1]})
    assert valid.status_code==200
    assert valid.json()['run']['request']['children_ages']==[7,1]
    flight=client.post('/api/browser/flight-search',json={'case_id':case['id'],'origin':'TPE','destination':'NRT','depart_date':'2026-10-18','return_date':'2026-10-22','adults':2,'children':1,'infants':0})
    assert flight.status_code==422


def test_manual_family_option_requires_known_child_ages(client):
    case=create_case(client,children=1)
    response=client.post(f"/api/mom/cases/{case['id']}/options",json=manual_payload())
    assert response.status_code==422 and '年齡' in response.text


def test_optional_ai_failure_returns_customer_template(client,monkeypatch):
    from types import SimpleNamespace
    import app.services.replies as replies
    monkeypatch.setattr(replies,'settings',SimpleNamespace(openclaw_enabled=True))
    async def failure(*args,**kwargs):
        return AgentReply(text='ConnectionError internal service',source='fallback',degraded=True)
    monkeypatch.setattr(replies.openclaw_client,'ask',failure)
    reply=draft(client,create_case(client))
    assert reply['source']=='template' and 'ConnectionError' not in reply['text']


@pytest.mark.parametrize('destination',['NRT','日本'])
def test_official_results_in_mom_view_selection_and_demo_blocking(client,monkeypatch,destination):
    from app.services.openclaw import openclaw_client
    case=create_case(client,destination=destination)
    request={'case_id':case['id'],'origin':'TPE','destination':'NRT','depart_date':'2026-10-18','return_date':'2026-10-22','adults':2,'airline_codes':['CI'],'case_context':{'destination':'spoof'}}
    created=client.post('/api/browser/flight-search',json=request).json()
    assert created['run']['request']['case_context']['destination']==destination
    task=created['tasks'][0]
    payload={'schema_version':'flight-search-v1','airline_code':'CI','airline_name':'China Airlines','source_url':task['source_url'],'status':'ok','observed_at':datetime.now(timezone.utc).isoformat(),'currency':'TWD','options':[{
        'option_id':'test-live','total_amount':42000,'currency':'TWD','segments':[
            {'flight_number':'CI100','origin':'TPE','destination':'NRT','departure_local':'2026-10-18T08:00+08:00','arrival_local':'2026-10-18T12:00+09:00'},
            {'flight_number':'CI101','origin':'NRT','destination':'TPE','departure_local':'2026-10-22T14:00+09:00','arrival_local':'2026-10-22T17:00+08:00'}
        ],'checked_baggage':'23kg','change_rule_summary':'待確認','refund_rule_summary':'待確認'}]}
    # Offline ingest must remain visibly synthetic, even for a valid contract.
    ingested=client.post(f"/api/browser/tasks/{task['id']}/ingest",json={'raw_text':json.dumps(payload)})
    assert ingested.status_code==200 and ingested.json()['review_state']=='auto_validated'
    demo=client.get(f"/api/mom/cases/{case['id']}/options").json()['options'][0]
    assert demo['is_demo'] and select(client,case,demo).status_code==409
    # Stub a successful gateway response to exercise the actual browser-run adapter.
    async def answer(*args,**kwargs):
        return AgentReply(text=json.dumps(payload),source='openclaw')
    monkeypatch.setattr(openclaw_client,'ask',answer)
    assert client.post(f"/api/browser/tasks/{task['id']}/run").status_code==200
    live=client.get(f"/api/mom/cases/{case['id']}/options").json()['options'][0]
    assert not live['is_demo'] and live['usable']
    assert select(client,case,live).status_code==200
    run=client.get(f"/api/browser/runs/{created['run']['id']}").json()['run']
    assert run['selected_option_id']=='test-live'
    assert '42,000.00' in draft(client,case)['text']
    # A changed result must require explicit reselection; a previously selected price is not silently replaced.
    payload['options'][0]['total_amount']=43000
    client.post(f"/api/browser/tasks/{task['id']}/run")
    assert not client.get(f"/api/mom/cases/{case['id']}/options").json()['can_draft_offer']
    assert '43,000.00' not in draft(client,case)['text']
    latest=client.get(f"/api/mom/cases/{case['id']}/options").json()['options'][0]
    assert select(client,case,latest).status_code==200
    # The exact result attempt controls provenance: a later lab result replaces live evidence.
    client.post(f"/api/browser/tasks/{task['id']}/ingest",json={'raw_text':json.dumps(payload)})
    lab = client.get(f"/api/mom/cases/{case['id']}/options").json()['options'][0]
    assert lab['is_demo'] and not lab['usable']
    client.post(f"/api/browser/tasks/{task['id']}/run")
    assert not client.get(f"/api/mom/cases/{case['id']}/options").json()['options'][0]['is_demo']
    client.patch(f"/api/cases/{case['id']}",json={'destination':'歐洲'})
    assert not client.get(f"/api/mom/cases/{case['id']}/options").json()['can_draft_offer']
    assert select(client,case,latest).status_code==409


def test_older_urgent_case_is_not_lost_among_recent_cases(client):
    from app.db import connect
    from datetime import date
    urgent=create_case(client,depart_date=(date.today()+timedelta(days=1)).isoformat(),return_date=(date.today()+timedelta(days=5)).isoformat())
    with connect() as db:
        db.execute("UPDATE trip_cases SET updated_at='2020-01-01T00:00:00Z' WHERE id=?",(urgent['id'],))
    for _ in range(22):
        create_case(client,depart_date=(date.today()+timedelta(days=40)).isoformat(),return_date=(date.today()+timedelta(days=45)).isoformat())
    assert any(card['id']==urgent['id'] for card in client.get('/api/mom/home').json()['priority'])


def test_template_feedback_is_not_attributed_to_an_openclaw_skill(client):
    response=client.post('/api/mom/skill-feedback',json={'skill_key':'customer-reply','feedback_type':'accepted','source':'web_template','draft_text':'已收到需求。'})
    assert response.status_code==200 and response.json()['skill_hash'] is None


def test_legacy_inverted_dates_remain_readable_and_can_be_repaired(client):
    from app.db import connect
    case = create_case(client)
    with connect() as db:
        db.execute("UPDATE trip_cases SET return_date='2026-10-01' WHERE id=?", (case['id'],))
    assert client.get('/api/cases').status_code == 200
    assert client.get('/api/mom/home').status_code == 200
    assert client.patch(f"/api/cases/{case['id']}", json={}).status_code == 200
    assert client.patch(f"/api/cases/{case['id']}", json={'return_date':'2026-10-22'}).status_code == 200


def test_manual_freshness_defaults_to_quote_window_and_respects_explicit_expiry(client):
    case = create_case(client)
    old = (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
    expired = add_option(client,case,observed_at=old)
    assert not expired['usable'] and select(client,case,expired).status_code == 409
    valid = add_option(client,case,observed_at=old,valid_until=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
    assert valid['usable'] and select(client,case,valid).status_code == 200


def test_internal_manual_supplier_and_url_do_not_leak_into_customer_draft(client):
    case = create_case(client)
    option = add_option(client,case,supplier_name='內部批發商機密',source_url='https://supplier.example.com/private-pricing')
    select(client,case,option)
    text = draft(client,case)['text']
    assert '測試來回機票' in text
    assert '內部批發商機密' not in text and 'supplier.example.com' not in text


def test_official_quote_window_is_separate_from_checkout_and_attempt_provenance():
    from app.models import TripCase, TripCaseCreate, new_id, now_iso
    from app.services.case_workflow import option_state, trip_snapshot
    case = TripCase(**TripCaseCreate(customer_name='時效測試').model_dump(),id=new_id('case'),created_at=now_iso(),updated_at=now_iso())
    option = {'case_snapshot':trip_snapshot(case),'source_type':'official','observed_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}
    assert option_state(option,case)['usable']
    assert not option_state({**option,'result_unavailable':True},case)['usable']
