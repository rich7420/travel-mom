"""Exercise private roster, binary upload recovery, reminder and handover UI on synthetic data."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

from cryptography.fernet import Fernet
import httpx
from playwright.sync_api import expect, sync_playwright

from browser_test_support import free_port, source_manifest, stop_server, wait_live


def verify_pretrip_staleness(page, base, check):
    """Seed an adopted booking over HTTP, then exercise human checks/delivery in UI."""
    def evidence(**values):
        return {'request_id': str(uuid4()), 'reference': '合成核對依據',
                'occurred_at': datetime.now(timezone.utc).isoformat(), 'checked': True, **values}

    with httpx.Client(base_url=base) as api:
        start = datetime.now(timezone.utc).date() + timedelta(days=14)
        response = api.post('/api/cases', json={'customer_name': '合成行前驗證', 'destination': '東京',
                            'adults': 1, 'depart_date': start.isoformat(), 'return_date': (start+timedelta(days=4)).isoformat()})
        assert response.status_code == 200, response.text
        c = response.json()['id']
        path = f'/api/mom/cases/{c}'

        def post(suffix, data):
            response = api.post(path + '/' + suffix, json=data)
            assert response.status_code == 200, response.text
            return response.json()

        def bundle():
            return api.get(path + '/operations').json()

        option = post('options', {'kind': 'flight', 'supplier_name': '合成供應商', 'source_reference': '人工確認',
                      'title': '合成機票', 'details': '一位大人往返', 'conditions': '人工核對退改條件',
                      'total_amount': '10000', 'currency': 'TWD', 'observed_at': datetime.now(timezone.utc).isoformat(), 'confirmed_for_case': True})
        post('selection', {'option_id': option['id']})
        quote = post('quotes', {'request_id': str(uuid4()), 'title': '合成報價',
                     'valid_until': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(), 'includes': '機票', 'excludes': '未列費用'})
        post(f"quotes/{quote['id']}/sent", evidence())
        post(f"quotes/{quote['id']}/accept", evidence())
        booking = post('bookings', evidence(kind='flight', title='合成正式訂購', supplier='合成供應商',
                       confirmation_number='E2E-'+uuid4().hex[:8], customer_details='日期與一位大人均已核對'))
        doc = post('documents', {'request_id': str(uuid4()), 'kind': 'e_ticket', 'title': '合成電子機票',
                    'required': True, 'booking_id': booking['id']})
        private = {'name': '行前合成姓名', 'category': 'adult', 'date_of_birth': '1990-01-01',
                   'passport_number': 'PRETRIP-SYNTHETIC', 'passport_expiry': '2030-01-01', 'nationality': 'TW'}
        traveller = post('travellers', {'request_id': str(uuid4()), **private})

        def open_pretrip():
            page.evaluate('(id)=>MomApp.openCase(id)', c)
            page.locator('#sheetBody [data-module=pretrip]').click()

        def verify_roster():
            page.locator('[data-action=files-open]').click()
            page.locator('[data-intent=verify]').click()
            form = page.locator('#travelFileForm')
            form.locator('[name=reference]').fill('合成整份名冊核對')
            form.locator('[name=checked]').check()
            form.locator('button[type=submit]').click()
            expect(page.locator('#sheetBody')).to_contain_text('目前名冊已核對')
            open_pretrip()

        def ready_document():
            page.locator(f'[data-intent=document][data-id="{doc["id"]}"]').click()
            form = page.locator('#operationForm')
            form.locator('[name=status]').select_option('ready')
            form.locator('[name=customer_text]').fill('請核對另附電子機票原件')
            form.locator('[name=reference]').fill('合成文件核對')
            form.locator('[name=checked]').check()
            form.locator('button[type=submit]').click()
            expect(page.locator('#operationForm')).to_have_count(0)

        def prepare():
            page.locator('[data-intent=pack]').click()
            page.locator('#operationForm button[type=submit]').click()
            expect(page.locator('#operationForm')).to_have_count(0)
            return bundle()['pretrip'][-1]

        open_pretrip()
        # A used, unverified roster prevents marking the bound ticket ready.
        page.locator(f'[data-intent=document][data-id="{doc["id"]}"]').click()
        form = page.locator('#operationForm')
        form.locator('[name=status]').select_option('ready')
        form.locator('[name=customer_text]').fill('未核對名冊時的文件')
        form.locator('[name=reference]').fill('合成核對')
        form.locator('[name=checked]').check()
        form.locator('button[type=submit]').click()
        expect(form.locator('.form-error')).to_contain_text('請先核對目前旅客名冊')
        check('unverified roster prevents document-ready mutation', bundle()['documents'][0]['status']=='missing')
        page.locator('#sheetBack').click()
        verify_roster()
        ready_document()
        prepared = prepare()
        check('verified roster and ticket produce prepared pack through UI', prepared['status']=='prepared' and not prepared['stale'])
        page.locator(f'[data-intent=deliver][data-id="{prepared["id"]}"]').click()
        form = page.locator('#operationForm')
        form.locator('[name=channel]').fill('人工 LINE')
        form.locator('[name=reference]').fill('尚未送出的交付依據')
        form.locator('[name=checked]').check()
        response = api.patch(path + '/travellers/' + traveller['id'], json={
                    'request_id': str(uuid4()), 'expected_revision': traveller['revision'], **private, 'name': '異動後合成姓名'})
        assert response.status_code==200, response.text
        form.locator('button[type=submit]').click()
        expect(form.locator('.form-error')).to_contain_text('已變更')
        expect(form.locator('[name=reference]')).to_have_value('尚未送出的交付依據')
        check('roster edit between opening and delivering rejects stale pack', bundle()['pretrip'][0]['status']=='prepared' and bundle()['pretrip'][0]['stale'])
        check('conflicted delivery retains evidence and focuses error', form.locator('.form-error').evaluate('(e)=>e===document.activeElement'))
        page.locator('#sheetBack').click()
        check('stale delivery action disappears', page.locator(f'[data-intent=deliver][data-id="{prepared["id"]}"]').count()==0)
        check('stale pack cannot be exported over HTTP', api.get(path+f'/pretrip/{prepared["id"]}/document').status_code==409)
        draft = prepare()
        check('changed roster generates blocked draft rather than ready pack', draft['status']=='draft' and any('旅客名冊' in text for text in draft['blockers']))
        verify_roster()
        check('roster recheck alone does not repair old document proof', bundle()['documents'][0]['needs_recheck'])
        ready_document()
        replacement = prepare()
        check('rechecked roster and ticket produce new prepared version', replacement['status']=='prepared' and replacement['version']==3)
        page.locator(f'[data-intent=deliver][data-id="{replacement["id"]}"]').click()
        form = page.locator('#operationForm')
        form.locator('[name=channel]').fill('人工交付')
        form.locator('[name=reference]').fill('合成實際交付紀錄')
        form.locator('[name=checked]').check()
        form.locator('button[type=submit]').click()
        expect(page.locator('#operationForm')).to_have_count(0)
        check('current replacement delivery preserves earlier versions', [pack['status'] for pack in bundle()['pretrip']]==['prepared','draft','delivered'])
        response = api.get(path+f'/pretrip/{replacement["id"]}/document')
        check('current customer export excludes private roster contents', response.status_code==200 and all(value not in response.text for value in ('PRETRIP-SYNTHETIC','異動後合成姓名')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','firefox','webkit'),default='chromium')
    parser.add_argument('--output',default='data/completion-review/features-browser')
    args=parser.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    sources=source_manifest();started_at=datetime.now(timezone.utc).isoformat()
    checks=[];errors=[]
    def check(label,condition=True):
        assert condition,label
        checks.append(label)
    with tempfile.TemporaryDirectory(prefix='mom-files-browser-') as temp:
        port=free_port()
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'TRAVEL_DESK_DB':str(Path(temp)/'test.db'),'APP_ENV':'dev','AUTH_MODE':'token','TRAVEL_DESK_ADMIN_TOKEN':'','OPENCLAW_ENABLED':'false','LINE_ENABLED':'false','TELEGRAM_ENABLED':'false','ATTACHMENTS_DIR':str(Path(temp)/'files'),'BACKUP_DIR':str(Path(temp)/'backups'),'PII_FERNET_KEY':Fernet.generate_key().decode()}
        with (out/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],env=env,stdout=log,stderr=log)
            try:
                wait_live(base)
                with httpx.Client(base_url=base) as api:
                    assert api.patch('/api/mom/preferences',json={'onboarding_complete':True}).status_code==200
                    case=api.post('/api/cases',json={'customer_name':'合成名冊案例','destination':'東京','adults':1,'depart_date':(datetime.now(timezone.utc).date()+timedelta(days=14)).isoformat(),'return_date':(datetime.now(timezone.utc).date()+timedelta(days=18)).isoformat()}).json();c=case['id'];path=f'/api/mom/cases/{c}'
                    doc=api.post(path+'/documents',json={'request_id':str(uuid4()),'kind':'other','title':'合成原始憑證','required':False}).json()
                    for index in range(2):
                        assert api.post(path+'/work-items',json={'request_id':str(uuid4()),'title':'合成交接 '+str(index),'kind':'change','owner':'媽媽','due_at':(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat(),'source':'供應商通知'}).status_code==200
                with sync_playwright() as pw:
                    browser=getattr(pw,args.browser).launch();context=browser.new_context(viewport={'width':1360,'height':900},locale='zh-TW');page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));accept=[True];page.on('dialog',lambda d:d.accept() if accept[0] else d.dismiss())
                    page.goto(base);page.wait_for_function('()=>state.cases.length===1&&state.preferences!==null')
                    page.evaluate('(id)=>MomApp.openCase(id)',c);page.locator('#sheetBody [data-module=pretrip]').click();page.locator('[data-action=files-open]').click();expect(page.locator('.private-section')).to_have_count(2);check('roster and files reuse pretrip sheet')
                    page.locator('[data-intent=traveller]').click();form=page.locator('#travelFileForm');expect(form).to_be_visible()
                    for name,value in {'name':'合成私密姓名','date_of_birth':'1990-01-01','passport_number':'SYNTHETIC-PASSPORT','passport_expiry':'2030-01-01','nationality':'TW'}.items():form.locator(f'[name={name}]').fill(value)
                    form.locator('button[type=submit]').click();expect(page.locator('[data-action=files-reveal]')).to_be_visible();check('traveller save returns masked summary','SYNTHETIC-PASSPORT' not in page.locator('#sheetBody').inner_text() and '合成私密姓名' not in page.locator('#sheetBody').inner_text())
                    page.locator('[data-action=files-reveal]').click();expect(page.locator('[data-private]')).to_contain_text('SYNTHETIC-PASSPORT');check('explicit reveal loads full private data')
                    page.locator('#sheetBack').click();expect(page.locator('[data-action=files-reveal]')).to_be_focused();check('hide removes private data and restores row focus','SYNTHETIC-PASSPORT' not in page.locator('#sheetBody').inner_text())
                    # Cancelled discard must preserve private input; accepted discard removes it.
                    page.locator('[data-intent=traveller]').first.click()
                    form=page.locator('#travelFileForm');form.locator('[name=name]').fill('未儲存私密姓名')
                    accept[0]=False;page.locator('#sheetBack').click()
                    expect(form.locator('[name=name]')).to_have_value('未儲存私密姓名')
                    check('cancelled private discard preserves input')
                    accept[0]=True;page.locator('#sheetBack').click()
                    expect(page.locator('#travelFileForm')).to_have_count(0)
                    check('accepted private discard removes sensitive input','未儲存私密姓名' not in page.locator('#sheetBody').inner_text())
                    # Two genuinely separate tabs read one revision; only the first writer wins.
                    traveller=httpx.get(base+path+'/travel-files').json()['travellers'][0]
                    selector=f'[data-intent=traveller][data-id="{traveller["id"]}"]'
                    page.locator(selector).click();form=page.locator('#travelFileForm')
                    form.locator('[name=name]').fill('第一頁尚未儲存')
                    second=context.new_page();second.on('pageerror',lambda error:errors.append(str(error)))
                    second.goto(base);second.wait_for_function('()=>state.preferences!==null')
                    second.evaluate('(id)=>MomApp.openCase(id)',c)
                    second.locator('#sheetBody [data-module=pretrip]').click();second.locator('[data-action=files-open]').click()
                    second.locator(selector).click();second.locator('#travelFileForm [name=name]').fill('第二頁已儲存')
                    second.locator('#travelFileForm button[type=submit]').click()
                    expect(second.locator(selector)).to_be_visible()
                    winning=httpx.get(base+path+'/travellers/'+traveller['id']+'/reveal').json()
                    form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_contain_text('旅客資料已更新')
                    expect(form.locator('[name=name]')).to_have_value('第一頁尚未儲存')
                    check('two-tab traveller conflict retains losing input and focuses error',form.locator('.form-error').evaluate('(e)=>e===document.activeElement'))
                    current=httpx.get(base+path+'/travellers/'+traveller['id']+'/reveal').json()
                    check('two-tab conflict cannot overwrite winner or increment revision',current==winning and current['name']=='第二頁已儲存')
                    second.close();page.locator('#sheetBack').click()
                    # Open proof against one roster, mutate through HTTP, then submit old proof.
                    page.locator('[data-intent=verify]').click();form=page.locator('#travelFileForm')
                    form.locator('[name=reference]').fill('過期核對');form.locator('[name=checked]').check()
                    assert httpx.patch(base+path+'/travellers/'+traveller['id'],json={**{k:v for k,v in current.items() if k not in ('id','revision')},'expected_revision':current['revision'],'request_id':str(uuid4()),'name':'合成更新後姓名'}).status_code==200
                    form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_contain_text('名冊或需求已變更')
                    check('stale whole-roster proof is rejected without saving',httpx.get(base+path+'/travel-files').json()['roster']['proof'] is None)
                    page.locator('#sheetBack').click()
                    page.locator('[data-intent=verify]').click();form=page.locator('#travelFileForm');form.locator('[name=reference]').fill('合成逐一核對');form.locator('[name=checked]').check();form.locator('button[type=submit]').click();expect(page.locator('#sheetBody')).to_contain_text('目前名冊已核對');check('whole roster verification uses current counts')
                    page.locator('[data-intent=upload]').click();form=page.locator('#travelFileForm');form.locator('[name=file]').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\nsynthetic browser original'})
                    # Server commits, then client loses response: recover by receipt without another upload.
                    page.evaluate("""()=>{window.originalFetch=fetch;window.uploadCalls=0;window.fetch=async(url,opts)=>{if(String(url).includes('/attachments?')){window.uploadCalls++;const result=await window.originalFetch(url,opts);if(window.uploadCalls===1)throw new TypeError('synthetic response lost');return result;}return window.originalFetch(url,opts);};}""")
                    form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_be_visible();check('lost response retains receipt without claiming success',page.evaluate('()=>uploadCalls')==1)
                    form.locator('button[type=submit]').click();expect(page.locator('[data-action=files-download]')).to_be_visible();check('retry reconciles receipt without retransmission',page.evaluate('()=>uploadCalls')==1)
                    page.evaluate('()=>window.fetch=window.originalFetch')
                    page.locator('[data-intent=upload]').click();form=page.locator('#travelFileForm')
                    form.locator('[name=file]').set_input_files({'name':'private-reload-name.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.4\nreload original'})
                    page.evaluate("""()=>{window.originalFetch=fetch;window.fetch=async(url,opts)=>{const result=await originalFetch(url,opts);if(String(url).includes('/attachments?'))throw new TypeError('synthetic reload response lost');return result;};}""")
                    form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_be_visible()
                    check('pending upload storage contains receipt only',page.evaluate("()=>{const raw=sessionStorage.getItem('travel-upload-intents:'+document.querySelector('#travelFileForm').travelOperation.c);return raw&&!raw.includes('private-reload-name')&&!raw.includes('reload original')&&JSON.parse(raw).length===1;}") )
                    requests=[];page.on('request',lambda request:requests.append(request.url) if request.method=='POST' and '/attachments?' in request.url else None)
                    page.reload();page.wait_for_function('()=>state.preferences!==null')
                    page.evaluate('(id)=>MomApp.openCase(id)',c);page.locator('#sheetBody [data-module=pretrip]').click();page.locator('[data-action=files-open]').click()
                    expect(page.locator('#sheetBody')).to_contain_text('已確認上次原件儲存成功')
                    expect(page.locator('[data-action=files-download]')).to_have_count(2)
                    check('same-tab reload reconciles saved upload without POST',not requests and len(httpx.get(base+path+'/travel-files').json()['attachments'])==2)
                    check('reload reconciliation clears pending receipt',page.evaluate('(id)=>sessionStorage.getItem("travel-upload-intents:"+id)===null',c))

                    with page.expect_download() as event:page.locator('[data-action=files-download]').first.click()
                    download=event.value;check('authenticated blob download succeeds',download.failure() is None)
                    page.locator('[data-intent=upload]').click();form=page.locator('#travelFileForm');form.locator('[name=file]').set_input_files({'name':'wrong.pdf','mimeType':'application/pdf','buffer':b'<html>invalid</html>'});form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_be_visible();check('file magic validation rejects and focuses error',form.locator('.form-error').evaluate('(e)=>e===document.activeElement'))
                    page.locator('#sheetBack').click();expect(page.locator('.private-section')).to_have_count(2)
                    for width in (390,768,1360):
                        page.set_viewport_size({'width':width,'height':900});page.evaluate("()=>document.documentElement.dataset.font='xlarge'")
                        check(f'private roster no overflow at {width}',page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth&&document.querySelector("#sheetBody").scrollWidth<=document.querySelector("#sheetBody").clientWidth'))
                        check(f'file buttons minimum44px at {width}',page.locator('#sheetBody button').evaluate_all('(buttons)=>buttons.every(b=>b.getBoundingClientRect().height>=44)'))
                        page.screenshot(path=str(out/f'files-{width}.png'))
                    page.locator('[data-intent=attachment-archive]').first.click();form=page.locator('#travelFileForm');form.locator('[name=reason]').fill('合成錯誤檔案');form.locator('[name=reference]').fill('核對原件');form.locator('[name=checked]').check();form.locator('button[type=submit]').click();expect(page.locator('.file-row').first).to_contain_text('已封存');check('archive keeps downloadable history')
                    page.locator('[data-action=files-reveal]').click();page.evaluate("()=>dispatchEvent(new Event('travel-auth-expired'))");check('privacy event handler removes sensitive DOM','SYNTHETIC-PASSPORT' not in page.locator('#sheetBody').inner_text())
                    page.locator('#sheetBack').click();page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('(id)=>MomApp.openCase(id)',c);page.locator('#sheetBody [data-module=tasks]').click();page.locator('#sheetBody [data-intent=acknowledge]').first.click();form=page.locator('#operationForm');form.locator('[name=reference]').fill('合成收到');form.locator('[name=checked]').check();form.locator('button[type=submit]').click();expect(page.locator('#sheetBody')).to_contain_text('已確認看到，不代表已完成');check('acknowledgement is separate from completion')
                    def fill_handover():
                        page.locator('#sheetBody [data-intent=handover]').click();form=page.locator('#operationForm');expect(form.locator('[name^=item_]')).to_have_count(2)
                        for node in form.locator('[name^=item_]').all():node.check()
                        form.locator('[name=owner]').fill('合成同事');form.locator('[name=reason]').fill('交班');form.locator('[name=reference]').fill('合成交接依據');form.locator('[name=checked]').check();return form
                    form=fill_handover();item=httpx.get(base+path+'/operations').json()['work_items'][0]
                    assert httpx.patch(base+path+'/work-items/'+item['id'],json={'request_id':str(uuid4()),'expected_revision':item['revision'],'notes':'另一個工作頁更新','reason':'合成更新'}).status_code==200
                    form.locator('button[type=submit]').click();expect(form.locator('.form-error')).to_contain_text('全部交接未儲存');expect(form.locator('[name=owner]')).to_have_value('合成同事')
                    check('stale handover keeps selections and focuses conflict',form.locator('[name^=item_]').evaluate_all('(items)=>items.every(i=>i.checked)') and form.locator('.form-error').evaluate('(e)=>e===document.activeElement'))
                    check('stale handover transfers none',all(t['owner']=='媽媽' for t in httpx.get(base+path+'/operations').json()['work_items']))
                    page.locator('#sheetBack').click();expect(page.locator('#sheetBody [data-intent=handover]')).to_be_visible();form=fill_handover()
                    form.locator('button[type=submit]').click();expect(page.locator('#sheetBody')).to_contain_text('合成同事');check('batch handover updates owner and clears acknowledgement',all('acknowledgement' not in t for t in httpx.get(base+path+'/operations').json()['work_items']))
                    page.locator('#sheet [data-action=close-sheet]').click();page.evaluate("()=>MomApp.setView('tasks')");expect(page.locator('.task-summary')).to_have_count(4);check('Taipei deadline buckets render grouped owners')
                    tasks=httpx.get(base+path+'/operations').json()['work_items']
                    for t in tasks:
                        assert httpx.patch(base+path+'/work-items/'+t['id'],json={'request_id':str(uuid4()),'expected_revision':t['revision'],'status':'done','reason':'合成完成'}).status_code==200
                    state=httpx.get(base+path+'/operations').json()['lifecycle']['expected_state']
                    assert httpx.post(base+path+'/lifecycle/close',json={'request_id':str(uuid4()),'expected_state':state,'outcome':'withdrawn','reason':'合成停止詢問','reference':'客人通知','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True}).status_code==200
                    page.evaluate('(id)=>MomApp.openCase(id)',c);page.locator('#sheetBody [data-module=pretrip]').click();page.locator('#sheetBody [data-action=files-open]').click();expect(page.locator('.private-section')).to_have_count(2)
                    check('closed private workspace has reads without mutations',page.locator('#sheetBody [data-action=files-form]').count()==0 and page.locator('#sheetBody [data-action=files-reveal]').count()==1 and page.locator('#sheetBody [data-action=files-download]').count()==2)
                    verify_pretrip_staleness(page,base,check)
                    page.goto(base+'/admin');page.get_by_role('button',name='備份狀態',exact=True).click();expect(page.locator('#modalBody')).to_contain_text('尚無紀錄');check('admin backup status shows observed result')
                    check('no JavaScript errors',not errors);browser.close()
            finally:
                stop_server(server)
    assert source_manifest()==sources,'Application or runner changed during verification'
    (out/'results.json').write_text(json.dumps({'browser':args.browser,'checks':checks,'javascript_errors':errors,'started_at':started_at,'source_sha256':sources},ensure_ascii=False,indent=2));print(f'{len(checks)} feature browser checks passed')


if __name__=='__main__':main()
