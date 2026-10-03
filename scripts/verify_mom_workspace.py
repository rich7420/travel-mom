"""Browser regression on a disposable SQLite desk; never uses the live preview.

Run: .venv/bin/python scripts/verify_mom_workspace.py --chrome /path/to/chrome
Requires Playwright (pip install playwright; playwright install chromium firefox webkit).
Use --browser firefox or --browser webkit for the other engines.
Screenshots and results contain synthetic data only.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','firefox','webkit'),default='chromium')
    parser.add_argument('--chrome')
    parser.add_argument('--output', default='data/hardening-review/browser')
    args = parser.parse_args()
    if args.chrome and args.browser!='chromium':parser.error('--chrome is only valid with --browser chromium')
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    checks, errors = [], []
    def check(name, condition=True):
        assert condition, name
        checks.append(name)
    with tempfile.TemporaryDirectory(prefix='mom-workspace-') as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'TRAVEL_DESK_DB':str(Path(temp)/'desk.db'), 'APP_ENV':'dev',
               'AUTH_MODE':'token', 'OPENCLAW_ENABLED':'false', 'TRAVEL_DESK_ADMIN_TOKEN':''}
        with (out/'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host','127.0.0.1','--port',str(port)], env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        if httpx.get(base+'/livez', timeout=.5).status_code == 200:break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
                else:raise RuntimeError('Disposable server failed to start')
                with httpx.Client(base_url=base) as api:
                    assert api.patch('/api/mom/preferences',json={'onboarding_complete':True}).status_code == 200
                    case = api.post('/api/cases',json={'customer_name':'合成測試客人','destination':'東京','notes':'原始備註'}).json()
                    other = api.post('/api/cases',json={'customer_name':'另一位合成客人','destination':'大阪'}).json()
                with sync_playwright() as pw:
                    browser = getattr(pw,args.browser).launch(headless=True,**({'executable_path':args.chrome} if args.chrome else {}))
                    context = browser.new_context(viewport={'width':1360,'height':900}, locale='zh-TW')
                    page = context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                    dialogs = []; accept = [False]
                    def dialog(d):
                        dialogs.append(d.message)
                        if accept[0]:d.accept()
                        else:d.dismiss()
                    page.on('dialog',dialog)
                    page.goto(base);page.wait_for_function('()=>state.cases.length===2 && state.preferences!==null')
                    page.screenshot(path=str(out/'home-desktop.png'))
                    check('deadlines precede shortcuts',page.locator('#deadlineHomeTitle').bounding_box()['y'] < page.locator('#quickTitle').bounding_box()['y'])
                    page.evaluate('(id)=>openEditCase(id)',case['id'])
                    notes = page.locator('#caseEditForm [name=notes]');expect(notes).to_be_visible();notes.fill('尚未儲存測試')
                    page.locator('#sheet [data-action=close-sheet]').click();expect(notes).to_have_value('尚未儲存測試')
                    check('close cancel retains dirty edits',len(dialogs)==1)
                    page.keyboard.press('Escape');expect(notes).to_have_value('尚未儲存測試')
                    check('Escape has one prompt',len(dialogs)==2)
                    page.locator('#sheetBack').click();expect(notes).to_have_value('尚未儲存測試')
                    check('back cancel retains dirty edits',len(dialogs)==3)
                    page.evaluate('(id)=>openCustomerReply(id)',case['id']);expect(notes).to_have_value('尚未儲存測試')
                    check('sheet replacement cancel retains edits',len(dialogs)==4)
                    accept[0]=True;page.locator('#sheetBack').click();expect(page.locator('#caseEditForm')).to_have_count(0)
                    check('accepted back prompts once',len(dialogs)==5)
                    # Immediate reopen must survive a queued close event.
                    page.evaluate('(id)=>{closeSheet();return openEditCase(id);}',case['id']);expect(notes).to_have_value('原始備註')
                    check('discard is explicit and immediate reopen succeeds')
                    notes.fill('儲存中的修改')
                    page.evaluate("""()=>{window.realFetch=window.fetch;window.fetch=(url,opts)=>url.startsWith('/api/cases/')&&opts?.method==='PATCH'?new Promise(resolve=>window.finishSave=()=>resolve(new Response(JSON.stringify({id:'synthetic'}),{status:200}))):window.realFetch(url,opts);} """)
                    page.locator('#caseEditForm button[type=submit]').click();page.wait_for_function('()=>typeof window.finishSave==="function"')
                    before=len(dialogs);page.locator('#sheet [data-action=close-sheet]').click();expect(notes).to_be_visible()
                    check('save blocks leaving without discard prompt',len(dialogs)==before)
                    check('saving form is inert',page.locator('#caseEditForm').evaluate('(el)=>el.inert'))
                    page.evaluate('()=>{window.fetch=window.realFetch;window.finishSave();}');expect(page.locator('#caseEditForm')).to_have_count(0)
                    check('committed save transitions without discard prompt',len(dialogs)==before)
                    page.evaluate('(id)=>openCustomerReply(id)',case['id'])
                    page.locator('#replyForm textarea').fill('請整理需求');page.locator('#replyForm button[type=submit]').click()
                    reply=page.locator('#replyDraft');expect(reply).to_be_visible();expect(reply).to_be_focused();check('generated draft receives keyboard focus');reply.fill('修改後的回客內容')
                    accept[0]=False;page.keyboard.press('Escape');expect(reply).to_have_value('修改後的回客內容')
                    check('edited reply survives cancelled Escape')
                    accept[0]=True;page.locator('#sheet [data-action=close-sheet]').click()
                    # A clean case selector switch should not prompt; dirty switch restores its association.
                    page.evaluate('(id)=>openHotelSearch(id)',case['id']);expect(page.locator('#hotelForm')).to_be_visible()
                    before=len(dialogs);page.locator('#hotelForm [name=case_id]').select_option(other['id'])
                    expect(page.locator('#hotelForm [name=case_id]')).to_have_value(other['id'])
                    check('clean case selector does not prompt',len(dialogs)==before)
                    page.locator('#hotelForm [name=hotel_name]').fill('手動飯店')
                    accept[0]=False;page.locator('#hotelForm [name=case_id]').select_option(case['id'])
                    expect(page.locator('#hotelForm [name=case_id]')).to_have_value(other['id'])
                    expect(page.locator('#hotelForm [name=hotel_name]')).to_have_value('手動飯店')
                    check('dirty selector keeps original association on cancel',len(dialogs)==before+1)
                    accept[0]=True;page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('(id)=>MomApp.openCase(id)',case['id']);expect(page.locator('.sales-actions')).to_be_visible()
                    check('secondary work collapsed',not page.locator('.sales-actions').evaluate('(el)=>el.open'))
                    check('primary work remains visible',page.locator('.operation-tiles').is_visible())
                    page.locator('.sales-actions summary').focus();page.keyboard.press('Space')
                    check('sales summary expands with keyboard',page.locator('.sales-actions').evaluate('(el)=>el.open'))
                    page.keyboard.press('Space')
                    check('sales summary collapses with keyboard',not page.locator('.sales-actions').evaluate('(el)=>el.open'))
                    page.locator('#sheet [data-kind=edit_case]').click();expect(page.locator('#caseEditForm')).to_be_visible()
                    check('missing-date primary action opens editor directly')
                    page.locator('#sheetBack').click();expect(page.locator('.operation-tiles')).to_be_visible()
                    page.locator('[data-module=tasks]').click();page.locator('[data-intent=create]').click()
                    expect(page.locator('#operationForm')).to_be_visible()
                    page.locator('[name=task_template]').select_option('ticketing')
                    expect(page.locator('[name=kind]')).to_have_value('ticketing')
                    expect(page.locator('[name=title]')).to_have_value('確認開票期限')
                    check('deadline template leaves real deadline blank and required',page.locator('[name=due_at]').input_value()=='' and page.locator('[name=due_at]').get_attribute('required') is not None)
                    page.locator('#sheet [data-action=close-sheet]').click()
                    for width in [390,768,1360]:
                        page.set_viewport_size({'width':width,'height':900});page.evaluate("()=>applyFontScale('xlarge')")
                        page.evaluate('(id)=>openCase(id)',case['id']);expect(page.locator('.sales-actions')).to_be_visible()
                        check(f'{width}px large text no overflow',not page.evaluate('()=>document.documentElement.scrollWidth>innerWidth') and not page.locator('#sheet').evaluate('(el)=>el.scrollWidth>el.clientWidth'))
                        check(f'{width}px summary target at least44px',page.locator('.sales-actions summary').bounding_box()['height']>=44)
                        page.screenshot(path=str(out/f'case-{width}.png'))
                        page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('()=>openHotelSearch()');expect(page.locator('#hotelForm')).to_be_visible()
                    page.locator('#hotelForm [name=hotel_name]').fill('未綁案件的手動飯店')
                    before=len(dialogs);page.locator('#hotelForm [data-action=add-manual]').click()
                    expect(page.locator('#hotelForm [name=hotel_name]')).to_have_value('未綁案件的手動飯店')
                    check('missing-case manual entry keeps form without discard prompt',len(dialogs)==before)
                    check('missing-case manual entry focuses association',page.locator('#hotelForm [name=case_id]').evaluate('(el)=>el===document.activeElement'))
                    page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('(id)=>openHotelSearch(id)',case['id']);expect(page.locator('#hotelForm')).to_be_visible()
                    page.locator('#hotelForm [name=hotel_name]').fill('失敗時保留飯店')
                    failing=f"**/api/mom/cases/{other['id']}"
                    page.route(failing,lambda r:r.fulfill(status=503,json={'detail':'synthetic case failure'}))
                    page.locator('#hotelForm [name=case_id]').select_option(other['id'])
                    expect(page.locator('#toast')).to_contain_text('synthetic case failure')
                    expect(page.locator('#hotelForm [name=case_id]')).to_have_value(case['id'])
                    expect(page.locator('#hotelForm [name=hotel_name]')).to_have_value('失敗時保留飯店')
                    check('failed case switch keeps original values and dirty state',page.locator('#hotelForm').get_attribute('data-dirty')=='true')
                    page.unroute(failing);page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('(id)=>openEditCase(id)',case['id']);expect(notes).to_be_visible();notes.fill('慢速換畫面')
                    page.evaluate("""()=>{window.realFetch=window.fetch;window.fetch=(url,opts)=>url.startsWith('/api/mom/cases/')&&!url.endsWith('/operations')?new Promise(resolve=>window.finishTransition=()=>resolve(new Response(JSON.stringify({case:{id:'synthetic'},next_action:{},selections:[]}),{status:200}))):window.realFetch(url,opts);} """)
                    before=len(dialogs);page.evaluate('(id)=>{window.slowTransition=openCase(id);}',other['id'])
                    page.wait_for_function('()=>typeof window.finishTransition==="function"')
                    check('pending transition prompts once',len(dialogs)==before+1)
                    page.locator('#sheet [data-action=close-sheet]').click();expect(page.locator('#sheet')).not_to_be_visible()
                    check('already-authorized pending discard does not prompt again',len(dialogs)==before+1)
                    page.evaluate('()=>{window.fetch=window.realFetch;window.finishTransition();}');page.evaluate('()=>window.slowTransition')
                    expect(page.locator('#sheet')).not_to_be_visible();check('stale transition cannot reopen closed sheet')
                    # Built-in lifecycle delegation and back must surface async errors.
                    page.route('**/operations',lambda r:r.fulfill(status=503,json={'detail':'synthetic operation failure'}))
                    page.evaluate('(id)=>actionFromDataset({dataset:{action:"next-action",kind:"tasks",caseId:id}})',case['id'])
                    expect(page.locator('#toast')).to_contain_text('synthetic operation failure')
                    check('lifecycle action failure gives visible feedback')
                    page.unroute('**/operations')
                    page.evaluate('(id)=>actionFromDataset({dataset:{action:"ops-open",module:"tasks",caseId:id}})',case['id'])
                    page.locator('[data-intent=create]').click()
                    expect(page.locator('#operationForm')).to_be_visible();page.locator('#operationForm [name=title]').fill('未存待辦')
                    page.route('**/operations',lambda r:r.fulfill(status=503,json={'detail':'synthetic back failure'}))
                    page.locator('#sheetBack').click();expect(page.locator('#toast')).to_contain_text('synthetic back failure')
                    expect(page.locator('#operationForm [name=title]')).to_have_value('未存待辦')
                    check('operation back failure keeps form and gives feedback')
                    page.unroute('**/operations');page.locator('#sheet [data-action=close-sheet]').click()
                    from datetime import datetime, timedelta, timezone
                    from uuid import uuid4
                    task=httpx.post(base+f"/api/mom/cases/{case['id']}/work-items",json={'request_id':str(uuid4()),'kind':'document','title':'合成急件','owner':'測試','source':'人工約定','due_at':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()}).json()
                    httpx.post(base+f"/api/mom/cases/{case['id']}/work-items",json={'request_id':str(uuid4()),'kind':'reply','title':'第二筆合成待辦','owner':'測試','source':'人工約定','due_at':(datetime.now(timezone.utc)+timedelta(hours=3)).isoformat()})
                    page.evaluate("()=>setView('tasks')")
                    expect(page.locator('#allDeadlines [data-intent=edit]')).to_have_count(2)
                    check('every open task retains its edit action')
                    page.evaluate("()=>setView('today')")
                    page.evaluate('()=>loadHome()');page.locator('#primaryTodayAction').click()
                    expect(page.locator(f'#sheetBody [data-id="{task["id"]}"][data-intent=edit]')).to_be_focused()
                    check('urgent next action focuses correct record')
                    page.locator('#sheet [data-action=close-sheet]').click()
                    page.evaluate('(id)=>openEditCase(id)',case['id']);expect(notes).to_be_visible();notes.fill('真實儲存後畫面更新失敗測試')
                    writes=[]
                    page.on('request',lambda r:writes.append(r.url) if r.method=='PATCH' and '/api/cases/' in r.url else None)
                    failing=f"**/api/mom/cases/{case['id']}"
                    page.route(failing,lambda r:r.fulfill(status=503,json={'detail':'synthetic saved refresh failure'}))
                    page.locator('#caseEditForm button[type=submit]').click();expect(notes).to_be_disabled()
                    expect(page.locator('#caseEditForm .form-error')).to_contain_text('已保存')
                    check('committed form stays read-only after follow-up failure')
                    check('mutation really saved despite refresh failure',httpx.get(base+f"/api/cases/{case['id']}").json()['notes']=='真實儲存後畫面更新失敗測試')
                    page.unroute(failing);page.locator('#caseEditForm [data-action=open-case]').click()
                    expect(page.locator('#caseEditForm')).to_have_count(0)
                    check('committed retry refresh never repeats mutation',len(writes)==1)
                    page.locator('#sheet [data-action=close-sheet]').click()
                    accept[0]=False
                    future=(datetime.now(timezone.utc).date()+timedelta(days=14)).isoformat()
                    httpx.patch(base+f"/api/cases/{other['id']}",json={'depart_date':future,'return_date':future})
                    plan=httpx.post(base+'/api/browser/flight-search',json={'case_id':other['id'],'origin':'TPE','destination':'KIX','depart_date':future,'return_date':future,'adults':1,'airline_codes':['CI']}).json()
                    assert 'run' in plan,plan
                    offer=httpx.post(base+f"/api/mom/cases/{other['id']}/options",json={'kind':'flight','supplier_name':'合成供應商','source_reference':'合成查價','title':'合成機票方案','details':'已核對日期人數','conditions':'人工條件','total_amount':'12000','currency':'TWD','observed_at':datetime.now(timezone.utc).isoformat(),'confirmed_for_case':True}).json()
                    assert 'id' in offer,offer
                    assert httpx.post(base+f"/api/mom/cases/{other['id']}/selection",json={'option_id':offer['id']}).status_code==200

                    # Dedicated lifecycle actions and evidence; no live customer data.
                    page.evaluate('(id)=>openCase(id)',other['id'])
                    page.locator('#sheetBody [data-module=lifecycle]').click()
                    expect(page.locator('#sheetBody')).to_contain_text('尚未記錄客人採用的報價')
                    expect(page.locator('[data-intent=completed]')).to_be_disabled()
                    page.locator('[data-intent=withdrawn]').click()
                    lifecycle_form=page.locator('#operationForm')
                    lifecycle_form.locator('[name=reason]').fill('客人尚無訂購且取消詢問')
                    lifecycle_form.locator('[name=reference]').fill('合成對話依據')
                    lifecycle_form.locator('[name=checked]').check()
                    page.locator('#sheet [data-action=close-sheet]').click()
                    expect(lifecycle_form).to_be_visible()
                    check('lifecycle dirty close can be cancelled')
                    # Reuse UUID when the server commits but the response is lost.
                    close_path=f"**/api/mom/cases/{other['id']}/lifecycle/close"
                    attempts=[]
                    def lost_response(route):
                        attempts.append(route.request.post_data_json['request_id'])
                        if len(attempts)==1:
                            assert route.fetch().status==200
                            route.fulfill(status=503,json={'detail':'synthetic response lost after commit'})
                        else:route.continue_()
                    page.route(close_path,lost_response)
                    lifecycle_form.locator('button[type=submit]').click()
                    expect(lifecycle_form.locator('.form-error')).to_be_visible()
                    lifecycle_form.locator('button[type=submit]').click()
                    expect(page.locator('#sheetBody')).to_contain_text('此案件為未成交結案')
                    check('uncertain close retry reuses one intent',len(attempts)==2 and len(set(attempts))==1)
                    page.unroute(close_path)
                    record=httpx.get(base+f"/api/mom/cases/{other['id']}/operations").json()
                    check('uncertain retry writes one immutable event',len(record['case_events'])==1)
                    page.locator('#sheetBack').click()
                    expect(page.locator('#sheetBody [data-action=edit-case]')).to_have_count(0)
                    expect(page.locator('#sheetBody .sales-actions')).to_have_count(0)
                    check('closed case removes sales editing')
                    page.evaluate('(id)=>{state.openclawEnabled=true;return openSearchProgress("flight",id);}',plan['run']['id'])
                    expect(page.locator('#sheetBody [data-action=start-search],#sheetBody [data-action=case-options],#sheetBody [data-action=select-option],#sheetBody [data-action=clear-selection]')).to_have_count(0)
                    check('closed search history has no start or selection controls')
                    page.evaluate('(id)=>openCaseOptions(id)',other['id'])
                    expect(page.locator('#sheetBody [data-action=add-manual],#sheetBody [data-action=customer-reply],#sheetBody [data-action=select-option],#sheetBody [data-action=clear-selection]')).to_have_count(0)
                    check('closed option history has no sales mutations',page.locator('#sheetBody .option-card').count()>0)
                    page.evaluate('(id)=>openManualOption(id)',other['id'])
                    expect(page.locator('#manualOptionForm')).to_have_count(0)
                    check('direct manual entry refuses closed case')
                    page.evaluate('(id)=>openCustomerReply(id)',other['id'])
                    expect(page.locator('#replyForm')).to_have_count(0)
                    check('direct reply entry refuses closed case')
                    page.evaluate('(id)=>openFlightSearch(id)',other['id'])
                    expect(page.locator('#flightForm')).to_have_count(0)
                    check('direct flight search refuses closed case')
                    page.evaluate('(id)=>openHotelSearch(id)',other['id'])
                    expect(page.locator('#hotelForm')).to_have_count(0)
                    check('direct hotel search refuses closed case')

                    page.evaluate('(id)=>openCase(id)',other['id'])

                    page.locator('#sheetBody [data-module=quotes]').click()
                    expect(page.locator('#sheetBody [data-action=ops-form]')).to_have_count(0)
                    check('closed business modules retain history only')
                    page.locator('#sheetBack').click()
                    page.locator('#sheetBody [data-module=lifecycle]').click()
                    page.locator('[data-intent=reopen]').focus();page.keyboard.press('Enter')
                    expect(page.locator('#operationForm')).to_be_visible()
                    page.locator('#operationForm [name=reason]').fill('客人重新詢問')
                    page.locator('#operationForm [name=reference]').fill('新的合成對話')
                    page.locator('#operationForm [name=checked]').check()
                    page.locator('#operationForm button[type=submit]').click()
                    expect(page.locator('[data-intent=withdrawn]')).to_be_visible()
                    check('keyboard reopen derives quoting and preserves history',httpx.get(base+f"/api/cases/{other['id']}").json()['status']=='quoting')
                    page.locator('[data-intent=withdrawn]').click()
                    page.locator('#operationForm [name=reason]').fill('測試過期畫面')
                    page.locator('#operationForm [name=reference]').fill('合成核對')
                    page.locator('#operationForm [name=checked]').check()
                    httpx.patch(base+f"/api/cases/{other['id']}",json={'notes':'另一個工作頁更新'})
                    page.locator('#operationForm button[type=submit]').click()
                    expect(page.locator('#operationForm .form-error')).to_contain_text('已變更')
                    check('stale lifecycle evidence fails without closing',httpx.get(base+f"/api/cases/{other['id']}").json()['status']=='quoting')
                    accept[0]=True;page.locator('#sheetBack').click();accept[0]=False
                    for width in (390,768,1360):
                        page.set_viewport_size({'width':width,'height':900})
                        page.evaluate("()=>document.documentElement.dataset.font='xlarge'")
                        check(f'lifecycle no overflow at {width}',page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth && document.querySelector("#sheetBody").scrollWidth<=document.querySelector("#sheetBody").clientWidth'))
                        page.screenshot(path=str(out/f'lifecycle-{width}.png'))
                    page.locator('#sheet [data-action=close-sheet]').click()
                    def api_evidence(**values):
                        return {'request_id':str(uuid4()),'reference':'合成核對依據','occurred_at':datetime.now(timezone.utc).isoformat(),'checked':True,**values}
                    def external_lifecycle(action,**values):
                        state=httpx.get(base+f"/api/mom/cases/{other['id']}/operations").json()['lifecycle']['expected_state']
                        response=httpx.post(base+f"/api/mom/cases/{other['id']}/lifecycle/{action}",json=api_evidence(expected_state=state,reason='另一工作頁核對',**values))
                        assert response.status_code==200,response.text
                    page.evaluate('(id)=>openCaseOptions(id)',other['id'])
                    expect(page.locator('#sheetBody [data-action=clear-selection]')).to_be_visible()
                    external_lifecycle('close',outcome='withdrawn')
                    page.locator('#sheetBody [data-action=clear-selection]').click()
                    expect(page.locator('#sheetBody')).to_contain_text('案件已結案，以下方案僅供查看')
                    expect(page.locator('#sheetBody [data-action=select-option],#sheetBody [data-action=clear-selection]')).to_have_count(0)
                    check('cross-tab close refreshes stale option controls read-only')
                    external_lifecycle('reopen')
                    q=httpx.post(base+f"/api/mom/cases/{other['id']}/quotes",json={'request_id':str(uuid4()),'title':'採用後撤回合成報價','valid_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),'includes':'合成機票','excludes':'未列明項目'}).json()
                    assert 'id' in q,q
                    for action in ('sent','accept'):
                        assert httpx.post(base+f"/api/mom/cases/{other['id']}/quotes/{q['id']}/{action}",json=api_evidence()).status_code==200
                    page.evaluate('(id)=>openCase(id)',other['id'])
                    page.locator('#sheetBody [data-module=lifecycle]').click();page.locator('[data-intent=withdrawn]').click()
                    expect(page.locator('#operationForm')).to_contain_text('此次未成交結案將明確撤回採用')
                    checkbox=page.locator('#operationForm [name=withdraw_adoption_checked]')
                    check('adoption withdrawal is disclosed and required',checkbox.get_attribute('required') is not None and not checkbox.is_checked())
                    page.locator('#operationForm [name=reason]').fill('核對客人決定撤回')
                    page.locator('#operationForm [name=reference]').fill('合成客人對話')
                    page.locator('#operationForm [name=checked]').check();checkbox.check()
                    page.locator('#operationForm button[type=submit]').click()
                    expect(page.locator('[data-intent=reopen]')).to_be_visible()
                    records=httpx.get(base+f"/api/mom/cases/{other['id']}/operations").json()
                    check('explicit withdrawal preserves adopted quote history',records['accepted_quote_id'] is None and records['quotes'][0]['status']=='withdrawn' and records['case_events'][-1]['withdraw_adoption_checked'] is True)
                    page.locator('#sheet [data-action=close-sheet]').click()
                    degraded=context.new_page();degraded.on('pageerror',lambda e:errors.append(str(e)))
                    degraded.route('**/api/airlines',lambda r:r.fulfill(status=503,json={'detail':'synthetic'}))
                    degraded.route('**/api/mom/preferences',lambda r:r.fulfill(status=503,json={'detail':'synthetic'}))
                    degraded.goto(base);degraded.wait_for_function('()=>state.cases.length===2 && state.home!==null')
                    expect(degraded.locator('#component-airlines')).to_be_visible()
                    expect(degraded.locator('#component-preferences')).to_be_visible()
                    check('failed catalogues and preferences do not block manual workspace')
                    degraded.unroute('**/api/airlines');degraded.locator('[data-component=airlines]').click()
                    expect(degraded.locator('#component-airlines')).to_have_count(0)
                    check('catalogue retry recovers')
                    auth=context.new_page();auth.on('pageerror',lambda e:errors.append(str(e)))
                    auth.route('**/api/airlines',lambda r:r.fulfill(status=401,json={'auth_mode':'cloudflare','detail':'login session expired'}))
                    auth.goto(base);expect(auth.locator('#loginDialog')).to_be_visible()
                    check('optional catalogue auth expiry opens login')
                    check('no JavaScript errors',not errors)
                    browser.close()
            finally:
                server.terminate()
                try:server.wait(timeout=5)
                except subprocess.TimeoutExpired:server.kill();server.wait()
    (out/'results.json').write_text(json.dumps({'browser':args.browser,'passed':checks,'javascript_errors':errors},ensure_ascii=False,indent=2))
    print(f'{len(checks)} browser checks passed; no JavaScript errors')


if __name__=='__main__':main()
