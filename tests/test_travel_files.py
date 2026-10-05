import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.db import connect
from test_case_operations import family, accepted, intent, evidence, moment, post, bundle, verified_booking, ready_document


@pytest.fixture
def crypto_settings(monkeypatch, tmp_path):
    import app.operations_repository as repository
    import app.services.travel_files as files
    import scripts.backup_bundle as backup
    configured=replace(files.settings, pii_fernet_key=Fernet.generate_key().decode(), attachments_dir=str(tmp_path/'files'), backup_dir=str(tmp_path/'backups'))
    for module in (repository,files,backup):monkeypatch.setattr(module,'settings',configured)
    return configured


@pytest.fixture
def client(crypto_settings):
    with TestClient(app) as value:yield value


def traveller(category='adult', **changes):
    return intent(name='PRIVATE-TRAVELLER-張大明', category=category, date_of_birth='1990-02-01',
        passport_number='PRIVATE-PASSPORT-12345', passport_expiry='2030-01-01', nationality='TW', **changes)


def document(client, case):
    return post(client,case,'documents',intent(kind='other',title='證件核對',required=False)).json()


def upload(client,case,doc,payload=b'%PDF-1.4\nsynthetic original',name='PRIVATE-張大明.pdf',revision=None,request_id=None,media='application/pdf'):
    return client.post(f"/api/mom/cases/{case['id']}/documents/{doc['id']}/attachments",params={'request_id':request_id or str(uuid4()),'expected_revision':revision or doc['revision']},content=payload,
                       headers={'content-type':media,'x-file-name':base64.b64encode(name.encode()).decode()})


def test_private_payloads_do_not_reach_summary_commands_audit_or_exports(client):
    case,_=family(client);payload=traveller()
    first=post(client,case,'travellers',payload);assert first.status_code==200,first.text
    assert first.json()==post(client,case,'travellers',payload).json()
    view=client.get(f"/api/mom/cases/{case['id']}/travel-files")
    assert 'PRIVATE-' not in view.text
    assert 'encrypted' not in client.get(f"/api/mom/cases/{case['id']}/operations").text
    with connect() as db:
        for table in ('agency_travellers','agency_commands','audit_log'):
            assert 'PRIVATE-PASSPORT' not in str(db.execute(f'SELECT * FROM {table} WHERE case_id=?',(case['id'],)).fetchall())
        token=json.loads(db.execute('SELECT payload_json FROM agency_travellers WHERE case_id=?',(case['id'],)).fetchone()[0])['encrypted']
        assert payload['passport_number'].encode() not in token.encode()
    revealed=client.get(f"/api/mom/cases/{case['id']}/travellers/{first.json()['id']}/reveal")
    assert revealed.json()['passport_number']==payload['passport_number']
    assert revealed.headers['cache-control']=='no-store'
    with connect() as db:assert db.execute("SELECT COUNT(*) FROM audit_log WHERE case_id=? AND action='agency.traveller.reveal'",(case['id'],)).fetchone()[0]==1


def test_roster_counts_edit_trip_and_closed_guards(client):
    case,_=family(client)
    records=[post(client,case,'travellers',traveller(kind)).json() for kind in ('adult','adult','child','infant')]
    def state():return client.get(f"/api/mom/cases/{case['id']}/travel-files").json()['roster']
    initial=state();assert initial['counts_match'] and not initial['current']
    assert post(client,case,'roster/verify',evidence(expected_state=initial['expected_state'])).status_code==200
    assert state()['current']
    data=traveller();data['name']='PRIVATE-CHANGE';data['expected_revision']=1
    response=client.patch(f"/api/mom/cases/{case['id']}/travellers/{records[0]['id']}",json=data)
    assert response.status_code==200 and not state()['current']
    assert post(client,case,'roster/verify',evidence(expected_state=initial['expected_state'])).status_code==409
    assert post(client,case,'roster/verify',evidence(expected_state=state()['expected_state'])).status_code==200
    assert client.patch('/api/cases/'+case['id'],json={'destination':'大阪'}).status_code==200
    assert not state()['current']
    assert post(client,case,f"travellers/{records[-1]['id']}/archive",evidence(expected_revision=1,reason='移出此次名冊')).status_code==200
    assert not state()['counts_match']
    with connect() as db:db.execute("UPDATE trip_cases SET status='closed' WHERE id=?",(case['id'],))
    assert post(client,case,'travellers',traveller()).status_code==409
    assert post(client,case,'roster/verify',evidence(expected_state=state()['expected_state'])).status_code==409
    assert client.get(f"/api/mom/cases/{case['id']}/travellers/{records[0]['id']}/reveal").status_code==200


def test_original_upload_retry_races_download_integrity_archive_and_cross_case(client,crypto_settings):
    case,_=family(client);doc=document(client,case);request_id=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:upload(client,case,doc,request_id=request_id),range(2)))
    assert [r.status_code for r in results]==[200,200]
    assert results[0].json()==results[1].json()
    attachment=results[0].json();files=list(Path(crypto_settings.attachments_dir).glob('*.fernet'));assert len(files)==1
    assert files[0].stat().st_mode & 0o777==0o600 and b'synthetic original' not in files[0].read_bytes()
    receipt=client.get(f"/api/mom/cases/{case['id']}/attachment-receipts/{request_id}").json();assert receipt['committed']
    assert upload(client,case,doc,payload=b'%PDF-1.4 different',request_id=request_id).status_code==409
    download=f"/api/mom/cases/{case['id']}/attachments/{attachment['id']}/download"
    response=client.get(download);assert b'synthetic original' in response.content
    assert response.headers['content-security-policy']=='sandbox' and 'PRIVATE' not in response.headers['content-disposition']
    other,_=family(client);assert client.get(download.replace(case['id'],other['id'])).status_code==404
    assert upload(client,other,doc).status_code==404
    assert post(client,case,f"attachments/{attachment['id']}/archive",evidence(expected_revision=1,reason='上傳錯誤')).status_code==200
    assert client.get(download).status_code==200 # archived history remains available
    with connect() as db:db.execute("UPDATE trip_cases SET status='closed' WHERE id=?",(case['id'],))
    assert upload(client,case,doc,revision=3).status_code==409
    token=bytearray(files[0].read_bytes());token[-10]^=1;files[0].write_bytes(token)
    assert client.get(download).status_code==400


@pytest.mark.parametrize('content,name,media',[(b'<script>bad</script>','bad.pdf','application/pdf'),(b'%PDF-1.4','bad.html','application/pdf'),(b'%PDF-1.4','../bad.pdf','application/pdf'),(b'','zero.pdf','application/pdf'),(b'%PDF-1.4','bad.pdf','text/html')])
def test_invalid_files_leave_no_rows_or_files(client,crypto_settings,content,name,media):
    case,_=family(client);doc=document(client,case)
    assert upload(client,case,doc,content,name,media=media).status_code==400
    assert not list(Path(crypto_settings.attachments_dir).glob('*'))
    assert not client.get(f"/api/mom/cases/{case['id']}/travel-files").json()['attachments']


def test_actual_upload_limit_and_other_route_limit(client):
    case,_=family(client);doc=document(client,case)
    assert upload(client,case,doc,b'%PDF-'+b'x'*(10*1024*1024)).status_code==413
    assert client.post('/api/cases',content=b'x'*1_100_000).status_code==413
    assert upload(client,case,doc,b'%PDF-'+b'x'*1_100_000).status_code==200


def test_upload_quotas_and_wrong_key_fail_closed(client,crypto_settings,monkeypatch):
    import app.services.travel_files as files
    case,_=family(client);doc=document(client,case)
    monkeypatch.setattr(files,'CASE_FILE_LIMIT',0)
    assert upload(client,case,doc).status_code==409
    monkeypatch.setattr(files,'CASE_FILE_LIMIT',100)
    monkeypatch.setattr(files,'settings',replace(crypto_settings,pii_fernet_key=''))
    assert upload(client,case,doc).status_code==400
    assert post(client,case,'travellers',traveller()).status_code==400


def test_roster_and_attachment_changes_invalidate_pretrip(client):
    case,ids=family(client);accepted(client,case,ids)
    f=verified_booking(client,case);h=verified_booking(client,case,'hotel')
    fd=ready_document(client,case,f,'e_ticket');ready_document(client,case,h,'hotel_voucher')
    first=post(client,case,'pretrip',intent(title='initial')).json();assert first['status']=='prepared'
    assert upload(client,case,fd).status_code==200
    assert bundle(client,case)['pretrip'][0]['stale']
    assert post(client,case,f"pretrip/{first['id']}/deliver",evidence(channel='LINE')).status_code==409
    for kind in ('adult','adult','child','infant'):assert post(client,case,'travellers',traveller(kind)).status_code==200
    assert '旅客名冊' in ' '.join(bundle(client,case)['warnings'])
    state=client.get(f"/api/mom/cases/{case['id']}/travel-files").json()['roster']
    assert post(client,case,'roster/verify',evidence(expected_state=state['expected_state'])).status_code==200
    assert any(d['needs_recheck'] for d in bundle(client,case)['documents'])
    assert 'PRIVATE-PASSPORT' not in json.dumps(post(client,case,'pretrip',intent(title='draft')).json())


def test_atomic_handover_ack_staleness_history_and_closed_case(client):
    case,_=family(client)
    tasks=[post(client,case,'work-items',intent(kind='change',title='改期'+str(i),owner='媽媽',due_at=moment(4),source='供應商')).json() for i in range(2)]
    ack=post(client,case,f"work-items/{tasks[0]['id']}/acknowledge",evidence(expected_revision=1));assert ack.status_code==200
    failed=post(client,case,'work-handover',evidence(items={t['id']:1 for t in tasks},owner='同事',reason='交班'));assert failed.status_code==409
    assert all(t['owner']=='媽媽' for t in bundle(client,case)['work_items'])
    payload=evidence(items={tasks[0]['id']:2,tasks[1]['id']:1},owner=' 同事  小李 ',reason='交班')
    response=post(client,case,'work-handover',payload);assert response.status_code==200
    assert response.json()==post(client,case,'work-handover',payload).json()
    assert all(t['owner']=='同事 小李' and 'acknowledgement' not in t for t in bundle(client,case)['work_items'])
    with connect() as db:db.execute("UPDATE trip_cases SET status='closed' WHERE id=?",(case['id'],))
    assert post(client,case,'work-handover',evidence(items={tasks[0]['id']:3},owner='test',reason='test')).status_code==409


def test_upload_io_does_not_block_health_event_loop(client,monkeypatch):
    import threading
    import app.services.travel_files as files
    case,_=family(client);doc=document(client,case);started=threading.Event();release=threading.Event();real=files.upload
    def blocked(*args):
        started.set();release.wait(timeout=3);return real(*args)
    monkeypatch.setattr(files,'upload',blocked)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(upload,client,case,doc)
        assert started.wait(timeout=2)
        try:
            assert client.get('/livez').status_code==200
            assert not future.done(), 'health waited until upload I/O completed'
        finally:release.set()
        assert future.result().status_code==200


def test_new_routes_cloudflare_roles_origin_and_cross_case(crypto_settings,access_client,signing_keys):
    from test_access_auth import headers
    private=signing_keys[0];mom=headers(private);admin=headers(private,email='admin@example.com')
    case=access_client.post('/api/cases',headers=mom,json={'customer_name':'signed synthetic','adults':1}).json();c=case['id'];path=f'/api/mom/cases/{c}'
    t=access_client.post(path+'/travellers',headers=mom,json=traveller());assert t.status_code==200
    assert access_client.get(path+'/travel-files',headers=mom).status_code==200
    assert access_client.get(path+f"/travellers/{t.json()['id']}/reveal",headers=mom).status_code==200
    wrong={**mom,'Origin':'https://evil.example.com'}
    assert access_client.post(path+'/travellers',headers=wrong,json=traveller()).status_code==403
    assert access_client.get('/api/system/backup-status',headers=mom).status_code==403
    assert access_client.get('/api/system/backup-status',headers=admin).status_code==200
    assert access_client.get(path+'/travel-files').status_code==401
    assert access_client.post(path+'/work-handover/',headers=mom,json={}).status_code==403


from test_access_auth import access_client, signing_keys


@pytest.mark.asyncio
async def test_upload_limit_is_exact_route_and_actual_chunked_bytes():
    from app.request_limits import RequestBodyLimitMiddleware
    dispatched=[]
    async def endpoint(scope,receive,send):dispatched.append(True);await receive()
    async def run(path,method,chunk_sizes):
        sent=[]
        messages=iter([{'type':'http.request','body':b'x'*size,'more_body':index<len(chunk_sizes)-1} for index,size in enumerate(chunk_sizes)])
        async def receive():return next(messages)
        async def send(message):sent.append(message)
        await RequestBodyLimitMiddleware(endpoint,limit=lambda:5,upload_limit=10)({'type':'http','headers':[],'method':method,'path':path},receive,send)
        return sent
    assert not await run('/api/mom/cases/c/documents/d/attachments','POST',[4,6]) and dispatched
    dispatched.clear()
    assert (await run('/api/mom/cases/c/documents/d/attachments','POST',[6,5]))[0]['status']==413 and not dispatched
    assert (await run('/api/mom/cases/c/documents/d/attachments/','POST',[6]))[0]['status']==413
    assert (await run('/api/mom/cases/c/documents/d/attachments','PATCH',[6]))[0]['status']==413
