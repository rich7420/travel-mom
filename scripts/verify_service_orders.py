"""Repeatable four-flow browser checks against a disposable synthetic service desk."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet
from playwright.sync_api import expect, sync_playwright

from browser_test_support import free_port, source_manifest, stop_server, wait_live


def moment(hours=0):
    return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat()


def evidence(**values):
    return {'request_id':str(uuid4()),'reference':'合成核對依據','occurred_at':moment(),'checked':True,**values}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser',choices=('chromium','firefox','webkit'),default='chromium')
    parser.add_argument('--output',default='data/service-order-review/browser')
    args=parser.parse_args();out=Path(args.output)/args.browser;out.mkdir(parents=True,exist_ok=True)
    sources=source_manifest();checks=[];errors=[]
    def check(label,condition=True):
        assert condition,label
        checks.append(label)
    with tempfile.TemporaryDirectory(prefix='mom-service-browser-') as temp:
        base=f'http://127.0.0.1:{free_port()}'
        env={**os.environ,'TRAVEL_DESK_DB':str(Path(temp)/'test.db'),'APP_ENV':'dev','AUTH_MODE':'token','TRAVEL_DESK_ADMIN_TOKEN':'','OPENCLAW_ENABLED':'false','LINE_ENABLED':'false','TELEGRAM_ENABLED':'false','PII_FERNET_KEY':Fernet.generate_key().decode(),'ATTACHMENTS_DIR':str(Path(temp)/'files'),'BACKUP_DIR':str(Path(temp)/'backups')}
        with (out/'server.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',base.rsplit(':',1)[1]],env=env,stdout=log,stderr=log)
            try:
                wait_live(base)
                with httpx.Client(base_url=base,trust_env=False) as api, sync_playwright() as pw:
                    def post(c,suffix,payload):
                        r=api.post(f'/api/mom/cases/{c}/{suffix}',json=payload);assert r.status_code==200,r.text;return r.json()
                    def bundle(c):return api.get(f'/api/mom/cases/{c}/operations').json()
                    def seed(name,quoted=True):
                        start=datetime.now(timezone.utc).date()+timedelta(days=14)
                        r=api.post('/api/cases',json={'customer_name':name,'destination':'東京','adults':1,'depart_date':start.isoformat(),'return_date':(start+timedelta(days=4)).isoformat()});assert r.status_code==200,r.text;c=r.json()['id']
                        if not quoted:return c,None
                        opt=post(c,'options',{'kind':'flight','supplier_name':'合成航空','source_reference':'人工確認','title':'合成機票','details':'一人往返','conditions':'合約與票規另核','total_amount':'10000','currency':'TWD','observed_at':moment(),'confirmed_for_case':True})
                        post(c,'selection',{'option_id':opt['id']})
                        q=post(c,'quotes',{'request_id':str(uuid4()),'title':'合成報價','valid_until':moment(1),'includes':'機票','excludes':'其他費用'})
                        post(c,f"quotes/{q['id']}/sent",evidence());post(c,f"quotes/{q['id']}/accept",evidence())
                        book=post(c,'bookings',evidence(kind='flight',title='合成正式訂購',supplier='合成航空',confirmation_number=uuid4().hex[:8],customer_details='日期旅客已核對'))
                        return c,book
                    api.patch('/api/mom/preferences',json={'onboarding_complete':True,'font_scale':'large'})
                    cancel,cb=seed('取消合成');refund,rb=seed('退款合成');change,chb=seed('改期合成');incident,_=seed('旅中合成',False)
                    post(cancel,'ledger',evidence(kind='customer_receipt',amount='10000',currency='TWD'))
                    post(refund,'ledger',evidence(kind='customer_receipt',amount='1000',currency='TWD'))
                    browser=getattr(pw,args.browser).launch();context=browser.new_context(viewport={'width':1360,'height':900},locale='zh-TW');page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)));page.on('dialog',lambda d:d.accept());page.goto(base);page.wait_for_function('()=>state.preferences!==null')
                    def orders(c):
                        page.evaluate('(c)=>MomApp.openCase(c)',c);page.locator('#sheetBody [data-module=tasks]').click();page.locator('[data-action=service-open]').click();expect(page.locator('#sheetBody')).to_contain_text('改退與旅中工作單')
                    def form(intent):
                        target=page.locator(f'#sheetBody [data-action=service-form][data-intent="{intent}"]');target.wait_for(state='attached');target.evaluate('(el)=>{if(el.closest("details"))el.closest("details").open=true;}')
                        if page.viewport_size['width']==390:page.screenshot(path=str(out/'mobile-before-form.png'))
                        page.locator(f'#sheetBody [data-action=service-form][data-intent="{intent}"]').click();expect(page.locator('#serviceOrderForm')).to_be_visible();return page.locator('#serviceOrderForm')
                    def submit(f):
                        f.locator('[name=reference]').fill('合成實際核對');f.locator('[name=checked]').check();f.locator('button[type=submit]').click()
                    def saved():
                        try:
                            expect(page.locator('#serviceOrderForm')).to_have_count(0)
                            expect(page.locator('#sheetBody > h3')).to_be_visible()
                        except AssertionError:
                            print(page.locator('#sheetBody').inner_text(),flush=True);page.screenshot(path=str(out/'failure.png'));raise
                    def create(c,kind,book=None):
                        orders(c);f=form('create');f.locator('[name=kind]').select_option(kind);f.locator('[name=title]').fill('合成'+kind);f.locator('[name=request_details]').fill('客人實際服務需求');f.locator('[name=contact]').fill('未公開合成聯絡窗口')
                        if book:f.locator(f'[name=booking_ids][value="{book["id"]}"]').check()
                        submit(f);saved();return bundle(c)['service_orders'][-1]
                    def assess(c,amounts=None):
                        f=form('assess')
                        for n,v in {'supplier_reply':'供應商正式條件','proposal':'完整服務方案','terms_reference':'適用合約與供應商通知','reason':'本次核對'}.items():f.locator(f'[name={n}]').fill(v)
                        if amounts:
                            if f.locator('[data-money-row]').count()==0:f.locator('[data-action=service-add-currency]').click();f.locator('[name=currency_0]').fill('TWD')
                            for n,v in amounts.items():f.locator(f'[name={n}_0]').fill(v)
                        submit(f);saved()
                    def begin():
                        f=form('decide');f.locator('[name=customer_reply]').fill('客人同意此方案');submit(f);saved();f=form('start');submit(f);saved()
                    def result():
                        f=form('supplier_result');f.locator('[name=details]').fill('供應商正式完成通知');submit(f);saved()
                    def settle(amount,kind='customer_refund',currency='TWD'):
                        f=form('settle');f.locator('[name=kind]').select_option(kind);f.locator('[name=currency]').select_option(currency);f.locator('[name=amount]').fill(amount);submit(f);saved()
                    def resolve(end=False):
                        f=form('resolve');f.locator('[name=summary]').fill('已完成並通知客人');f.locator('[name=customer_notified_checked]').check()
                        if end:f.locator('[name=end_trip]').check()
                        submit(f);saved()
                    orders(incident);check('empty state and guide use existing sheet',page.locator('.empty-state').count()>0 and page.locator('#sheetHelp').get_attribute('href').endswith('#deadlines'))
                    co=create(cancel,'cancellation',cb);assess(cancel,{'customer_refund':'8500','supplier_fee':'1000','agency_fee':'500','final_customer_due':'1500'});begin();result()
                    check('supplier cancellation voids original booking with explicit fact',bundle(cancel)['bookings'][0]['void_kind']=='supplier_cancelled')
                    check('completion disabled while cash remains',page.locator('[data-intent=resolve]').is_disabled())
                    settle('4000');check('partial refund keeps remaining visible','4500.00' in page.locator('#sheetBody').inner_text());settle('4500');resolve(True)
                    check('cancellation retained fee and actual refunds balance',bundle(cancel)['balances']['TWD']['customer_balance']=='0.00')
                    page.locator('#sheetBack').click();expect(page.locator(f'[data-action=service-detail][data-id="{co["id"]}"]')).to_be_focused();check('return restores work order row focus')
                    page.locator('#sheetBack').click();page.locator('[data-module=lifecycle]').click();page.locator('[data-intent=cancelled]').click();f=page.locator('#operationForm');f.locator('[name=reason]').fill('取消與保留費用已核對');f.locator('[name=reference]').fill('合成結算');f.locator('[name=checked]').check();f.locator('[name=supplier_settlement_checked]').check();f.locator('[name=withdraw_adoption_checked]').check();f.locator('button[type=submit]').click();expect(page.locator('#operationForm')).to_have_count(0)
                    orders(cancel);page.locator('#sheetBody [data-action=service-detail]').click();check('closed case preserves history and removes mutations',page.locator('[data-action=service-form]').count()==0 and bundle(cancel)['case']['status']=='closed')
                    ro=create(refund,'refund');assess(refund,{'customer_refund':'900','final_customer_due':'9100'});begin();result()
                    f=form('settle');f.locator('[name=kind]').select_option('customer_refund');f.locator('[name=amount]').fill('901');submit(f);expect(f.locator('.form-error')).to_contain_text('超過');expect(f.locator('[name=amount]')).to_have_value('901');check('over-refund error preserves input and focuses alert',f.locator('.form-error').evaluate('(e)=>e===document.activeElement'))
                    # Conflict refresh deliberately requires the user's explicit review.
                    f.locator('[name=review_latest]').check();f.locator('[name=amount]').fill('400')
                    cash_id=str(uuid4());receipt_reads=[0]
                    page.evaluate('([c,id,order])=>sessionStorage.setItem("travel-service-intents:"+c,JSON.stringify([{request_id:id,order_id:order,intent:"settle",actor:"operator"}]))',[refund,cash_id,ro['id']])
                    def cash_commits_after_receipt(route):
                        response=route.fetch();receipt_reads[0]+=1
                        if receipt_reads[0]==1:
                            assert response.json()=={'committed':False}
                            current=bundle(refund)['service_orders'][0]
                            post(refund,f"service-orders/{ro['id']}/settlement",evidence(request_id=cash_id,expected_revision=current['revision'],kind='customer_refund',amount='400',currency='TWD',reference='另一頁原始收付憑據'))
                        route.fulfill(response=response)
                    page.route('**/service-order-receipts/'+cash_id,cash_commits_after_receipt)
                    submit(f);saved();page.unroute('**/service-order-receipts/'+cash_id)
                    check('settlement fingerprint race reconciles original receipt with one cash record',receipt_reads[0]>=2 and len([e for e in bundle(refund)['ledger'] if e.get('service_order_id')])==1)

                    f=form('settle');f.locator('[name=kind]').select_option('customer_refund');f.locator('[name=amount]').fill('500');f.locator('[name=reference]').fill('合成遺失回應');f.locator('[name=checked]').check()
                    page.evaluate("""()=>{window.originalFetch=fetch;window.cashCalls=0;window.fetch=async(url,opts)=>{if(String(url).endsWith('/settlement')){cashCalls++;const r=await originalFetch(url,opts);if(cashCalls===1)throw new TypeError('synthetic response lost');return r;}return originalFetch(url,opts);};}""")
                    f.locator('button[type=submit]').click();expect(f.locator('.form-error')).to_be_visible()
                    check('lost cash response stores metadata only',page.evaluate("()=>{const s=sessionStorage.getItem('travel-service-intents:'+document.querySelector('#serviceOrderForm').serviceOperation.c);return s&&!s.includes('合成遺失回應')&&!s.includes('500')&&JSON.parse(s).length===1;}"))
                    f.locator('[data-action=service-reconcile]').click();saved();check('cash retry uses receipt without second transfer record',page.evaluate('()=>cashCalls')==1 and len([e for e in bundle(refund)['ledger'] if e.get('service_order_id')])==2);page.evaluate('()=>window.fetch=originalFetch');resolve();check('refund workflow completes',bundle(refund)['service_orders'][0]['status']=='completed')
                    io=create(incident,'incident');f=form('safety_assistance');f.locator('[name=message]').fill('已協助醫療與緊急聯絡');submit(f);saved();resolve();check('incident immediate assistance needs no approval or quote',bundle(incident)['service_orders'][0]['status']=='completed' and not bundle(incident)['quotes'])
                    f=form('reopen');f.locator('[name=reason]').fill('後續費用');submit(f);saved();assess(incident,{'customer_receipt':'300','supplier_payment':'200','final_customer_due':'300'});begin();result();settle('300','customer_receipt');settle('200','supplier_payment');resolve();check('quote-free incident settles four-direction cash',bundle(incident)['balances']['TWD']['customer_balance']=='0.00')
                    cho=create(change,'change',chb);assess(change);begin()
                    # Actual booking modification uses the existing confirmation UI.
                    page.evaluate('(c)=>MomApp.openCase(c)',change);page.locator('#sheetBody [data-module=bookings]').click()
                    post(change,f"bookings/{chb['id']}/rebind",evidence(reason='完成改期核對',customer_details='異動後正式內容'))
                    orders(change);page.locator('#sheetBody [data-action=service-detail]').click();f=form('supplier_result');f.locator('[name=details]').fill('供應商正式異動通知');f.locator(f'[name=result_booking_ids][value="{chb["id"]}"]').check()
                    before=bundle(change)['service_orders'][0]
                    post(change,f"bookings/{chb['id']}/rebind",evidence(reason='另一頁更正異動內容',customer_details='尚未在本頁核對的新內容'))
                    submit(f);expect(f.locator('.form-error')).to_contain_text('訂購已更新');expect(f.locator('[name=details]')).to_have_value('供應商正式異動通知')
                    check('stale initial result locks form and preserves evidence without committing',f.locator('[name=review_latest]').count()==0 and f.locator('[data-action=service-detail]').count()==1 and bundle(change)['service_orders'][0]['revision']==before['revision'])
                    f.locator('[data-action=service-detail]').click();f=form('supplier_result');f.locator('[name=details]').fill('新內容已重新核對');f.locator(f'[name=result_booking_ids][value="{chb["id"]}"]').check();submit(f);saved()
                    permanent=bundle(change)['service_orders'][0]['supplier_result']
                    post(change,f"bookings/{chb['id']}/void",evidence(reason='已換成新正式訂購'))
                    replacement=post(change,'bookings',evidence(kind='flight',title='合成替換訂購',supplier='合成航空',confirmation_number=uuid4().hex[:8],customer_details='替換訂購已核對'))
                    orders(change);page.locator('#sheetBody [data-action=service-detail]').click();f=form('rebind_result');f.locator('[name=details]').fill('替換訂購核對依據');f.locator(f'[name=result_booking_ids][value="{replacement["id"]}"]').check()
                    before=bundle(change)['service_orders'][0]
                    replacement=post(change,f"bookings/{replacement['id']}/rebind",evidence(reason='另一頁更正替換訂購',customer_details='替換訂購最新內容'))
                    submit(f);expect(f.locator('.form-error')).to_contain_text('訂購已更新');expect(f.locator('[name=details]')).to_have_value('替換訂購核對依據')
                    check('selected replacement change locks rebinding even when original targets unchanged',f.locator('[name=review_latest]').count()==0 and bundle(change)['service_orders'][0]['revision']==before['revision'])
                    f.locator('[data-action=service-detail]').click();f=form('rebind_result');f.locator('[name=details]').fill('替換訂購最新內容已核對');f.locator(f'[name=result_booking_ids][value="{replacement["id"]}"]').check();submit(f);saved()
                    check('fresh rebinding succeeds and preserves immutable supplier result',bundle(change)['service_orders'][0]['supplier_result']==permanent and bundle(change)['service_orders'][0]['result_bindings']=={replacement['id']:replacement['revision']})
                    check('change cannot complete before current travel document proof',page.locator('[data-intent=resolve]').is_disabled())
                    doc=post(change,'documents',{'request_id':str(uuid4()),'kind':'e_ticket','title':'新版機票','required':True,'booking_id':replacement['id']})
                    r=api.patch(f'/api/mom/cases/{change}/documents/{doc["id"]}',json=evidence(expected_revision=1,status='ready',customer_text='新版正式機票已核對'));assert r.status_code==200,r.text
                    orders(change);page.locator('#sheetBody [data-action=service-detail]').click();resolve();check('change result completed against current booking and document',bundle(change)['service_orders'][0]['status']=='completed')
                    refused,refused_book=seed('供應商拒絕異動合成');create(refused,'change',refused_book);assess(refused);begin();f=form('supplier_result');f.locator('[name=outcome]').select_option('declined');f.locator('[name=details]').fill('供應商正式拒絕改期');submit(f);saved();expect(page.locator('#sheetBody .service-next [data-intent=assess]')).to_be_visible();assess(refused);begin();expect(page.locator('#sheetBody .service-next [data-intent=resolve]')).to_be_visible();resolve();check('supplier refusal routes corrective consent then completion without cancelling booking',bundle(refused)['service_orders'][0]['status']=='supplier_declined' and bundle(refused)['bookings'][0]['status']=='confirmed')
                    # Local planning conflict retains data, refreshes revision, requires explicit check.
                    orders(refund);page.locator('#sheetBody [data-action=service-detail]').click();f=form('reopen');f.locator('[name=reason]').fill('二次核對');submit(f);saved();f=form('edit');f.locator('[name=owner]').fill('尚未儲存負責人')
                    current=bundle(refund)['service_orders'][0]
                    r=api.patch(f'/api/mom/cases/{refund}/service-orders/{ro["id"]}',json=evidence(expected_revision=current['revision'],owner='另一頁已更新',due_at=moment(3),urgency='normal',contact='',reason='另一頁核對'));assert r.status_code==200,r.text
                    f.locator('[name=reason]').fill('本頁調整');submit(f);expect(f.locator('.form-error')).to_contain_text('已更新');expect(f.locator('[name=owner]')).to_have_value('尚未儲存負責人');expect(f.locator('#serviceConflict')).to_contain_text('另一頁已更新');check('planning 409 retains fields and displays latest revision')
                    f.locator('[name=review_latest]').check();submit(f);saved();check('explicit review retries planning against latest revision',bundle(refund)['service_orders'][0]['owner']=='尚未儲存負責人')
                    # Session loss only removes the dedicated unsaved contact field.
                    f=form('edit');f.locator('[name=contact]').fill('尚未存聯絡資料');f.locator('[name=reason]').fill('保留的處理原因');f.locator('[name=reference]').fill('保留的核對依據');page.evaluate("()=>window.dispatchEvent(new Event('travel-auth-expired'))");expect(f.locator('[name=contact]')).to_have_value('');expect(f.locator('[name=reason]')).to_have_value('保留的處理原因');expect(f.locator('[name=reference]')).to_have_value('保留的核對依據');check('auth expiry clears contact and retains noncontact draft')
                    f.locator('[name=contact]').fill('已送出等待核對窗口')
                    page.evaluate("""()=>{window.originalFetch=fetch;window.editCalls=0;window.fetch=async(url,opts)=>{const r=await originalFetch(url,opts);if(opts?.method==='PATCH'&&String(url).includes('/service-orders/')){editCalls++;throw new TypeError('synthetic committed edit response lost');}return r;};}""")
                    submit(f);expect(f.locator('[data-action=service-reconcile]')).to_be_visible()
                    page.evaluate("()=>window.dispatchEvent(new Event('travel-auth-expired'))")
                    check('expiry redacts visible contact without changing sent frozen snapshot',f.locator('[name=contact]').input_value()=='' and f.evaluate('(el)=>el.serviceOperation.frozenPayload.contact')=='已送出等待核對窗口')
                    f.locator('[data-action=service-reconcile]').click();saved()
                    check('redacted contact request reconciles saved original without second mutation',page.evaluate('()=>editCalls')==1 and bundle(refund)['service_orders'][0]['contact']=='已送出等待核對窗口');page.evaluate('()=>window.fetch=originalFetch')

                    # Lost response + reload recovery for note, no payload retained in storage.
                    f=form('note');f.locator('[name=message]').fill('合成重載紀錄');f.locator('[name=reference]').fill('合成重載依據');f.locator('[name=checked]').check()
                    page.evaluate("""()=>{window.originalFetch=fetch;window.fetch=async(url,opts)=>{const r=await originalFetch(url,opts);if(String(url).endsWith('/progress'))throw new TypeError('synthetic reload lost');return r;};}""");f.locator('button[type=submit]').click();expect(f.locator('.form-error')).to_be_visible();before=len(bundle(refund)['service_orders'][0]['history']);page.reload();page.wait_for_function('()=>state.preferences!==null');orders(refund);check('reload reconciles pending receipt without duplicate history',len(bundle(refund)['service_orders'][0]['history'])==before and page.evaluate(f"()=>sessionStorage.getItem('travel-service-intents:{refund}')") is None)
                    # Independent work-order read failure leaves a way back to existing tasks.
                    page.evaluate("""()=>{window.originalFetch=fetch;window.failNext=true;window.fetch=(url,opts)=>{if(failNext&&String(url).endsWith('/operations')){failNext=false;return Promise.resolve(new Response(JSON.stringify({detail:'合成讀取失敗'}),{status:503}));}return originalFetch(url,opts);};}""")
                    page.locator('#sheetBody [data-action=service-detail]').click();expect(page.locator('#sheetBody [role=alert]')).to_contain_text('合成讀取失敗');check('read error offers retry and regular-task fallback',page.locator('[data-action=ops-open][data-module=tasks]').count()==1);page.locator('#sheetBody [data-action=service-detail]').click();expect(page.locator('#sheetBody [data-intent=edit]')).to_have_count(1);page.evaluate('()=>window.fetch=originalFetch');check('retry restores current service order')
                    # Separate two-currency order exercises consent, expiry, deadline routing and busy guards.
                    multi,_=seed('多幣別與失效合成',False);mo=create(multi,'incident');f=form('assess')
                    for n,v in {'supplier_reply':'正式雙幣回覆','proposal':'雙幣別完整方案','terms_reference':'供應商雙幣條件','reason':'核對雙幣'}.items():f.locator(f'[name={n}]').fill(v)
                    f.locator('[data-action=service-add-currency]').click()
                    for n,v in {'currency_0':'TWD','customer_receipt_0':'300','final_customer_due_0':'300'}.items():f.locator(f'[name={n}]').fill(v)
                    f.locator('[data-action=service-add-currency]').click()
                    f.locator('[data-action=service-add-currency]').click();f.locator('[data-money-row]').last.locator('[data-action=service-remove-currency]').click();check('extra currency row can be removed without changing other currency names',f.locator('[data-money-row]').count()==2 and f.locator('[name=currency_1]').count()==1)
                    for n,v in {'currency_1':'JPY','customer_receipt_1':'100','customer_refund_1':'50','final_customer_due_1':'50'}.items():f.locator(f'[name={n}]').fill(v)
                    submit(f);saved();check('multiple currencies remain separate decimal plans',len(bundle(multi)['service_orders'][0]['assessment']['amounts'])==2)
                    f=form('decide');expect(f).to_contain_text('正式雙幣回覆');expect(f).to_contain_text('供應商雙幣條件');expect(f).to_contain_text('有效至');check('consent shows complete supplier terms and expiry')
                    f.locator('[name=customer_reply]').fill('只同意原方案');current=bundle(multi)['service_orders'][0]
                    newplan=evidence(expected_revision=current['revision'],supplier_reply='新供應商條件',proposal='不同的新方案',terms_reference='新条件',valid_until=moment(1),reason='另一頁改條件',amounts=current['assessment']['amounts'])
                    post(multi,f"service-orders/{mo['id']}/assessment",newplan);submit(f);expect(f.locator('.form-error')).to_be_visible();expect(f.locator('[name=customer_reply]')).to_have_value('只同意原方案');check('changed assessment locks consequential retry instead of approving new proposal',f.locator('[name=review_latest]').count()==0 and f.locator('[data-action=service-detail]').count()==1 and bundle(multi)['service_orders'][0]['decision'] is None)
                    page.locator('#sheetBack').click();current=bundle(multi)['service_orders'][0]
                    post(multi,f"service-orders/{mo['id']}/assessment",{**newplan,'request_id':str(uuid4()),'expected_revision':current['revision'],'valid_until':moment(.0002)})
                    page.wait_for_timeout(1000);orders(multi);page.locator('#sheetBody [data-action=service-detail]').click();expect(page.locator('#sheetBody')).to_contain_text('條件已過期');check('expired terms hide decision and start',page.locator('#sheetBody [data-intent=decide]').count()==0 and page.locator('#sheetBody [data-intent=start]').count()==0)
                    current=bundle(multi)['service_orders'][0];post(multi,f"service-orders/{mo['id']}/assessment",{**newplan,'request_id':str(uuid4()),'expected_revision':current['revision']});orders(multi);page.locator('#sheetBody [data-action=service-detail]').click();begin();result();settle('300','customer_receipt');settle('100','customer_receipt','JPY');settle('50','customer_refund','JPY');resolve();check('multi-currency incident reconciles separately',all(v['customer_balance']=='0.00' for v in bundle(multi)['balances'].values()))
                    f=form('reopen');f.locator('[name=reason]').fill('後續聯絡核對');submit(f);saved();page.locator('[data-action=close-sheet]').click();page.locator('.nav-item[data-nav=tasks]').click();deadline=page.locator(f'#allDeadlines [data-action=service-detail][data-id="{mo["id"]}"]');deadline.wait_for(state='attached');deadline.evaluate('(el)=>{const group=el.closest("details.task-summary");if(group)group.open=true;}');deadline.click();expect(page.locator('#sheetBody')).to_contain_text('合成incident');check('deadline entry opens dedicated order without regular-task mutation')
                    f=form('note');f.locator('[name=message]').fill('合成雙按一次');f.locator('[name=reference]').fill('合成雙按依據');f.locator('[name=checked]').check();before=len(bundle(multi)['service_orders'][0]['history'])
                    page.evaluate("""()=>{window.originalFetch=fetch;window.progressCalls=0;window.fetch=(url,opts)=>{if(String(url).endsWith('/progress')&&opts?.method==='POST')progressCalls++;return originalFetch(url,opts);};const f=document.querySelector('#serviceOrderForm');f.requestSubmit();f.requestSubmit();}""");saved();check('double submit performs one write',page.evaluate('()=>progressCalls')==1 and len(bundle(multi)['service_orders'][0]['history'])==before+1);page.evaluate('()=>window.fetch=originalFetch')
                    f=form('note');f.locator('[name=message]').fill('登入後仍需保存的聯絡紀錄');f.locator('[name=reference]').fill('登入前核對依據');f.locator('[name=checked]').check()
                    page.evaluate("""()=>{window.originalFetch=fetch;window.rejectAuth=true;window.fetch=(url,opts)=>{if(rejectAuth&&String(url).endsWith('/progress')){rejectAuth=false;return Promise.resolve(new Response(JSON.stringify({auth_mode:'cloudflare',detail:'synthetic expired session'}),{status:401}));}return originalFetch(url,opts);};}""");f.locator('button[type=submit]').click();expect(page.locator('#loginDialog')).to_be_visible();expect(f.locator('[name=message]')).to_have_value('登入後仍需保存的聯絡紀錄');check('HTTP 401 uses shared login dialog and preserves order draft');page.locator('#loginDialog [data-action=login]').click();expect(page.locator('#loginDialog')).not_to_be_visible();f.locator('[data-action=service-reconcile]').click();saved();page.evaluate('()=>window.fetch=originalFetch');check('login continuation reconciles before saving once')
                    page.set_viewport_size({'width':768,'height':1024});page.screenshot(path=str(out/'tablet.png'));check('768px detail has no horizontal overflow',page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth&&document.querySelector("#sheetBody").scrollWidth<=document.querySelector("#sheetBody").clientWidth'));page.set_viewport_size({'width':1360,'height':900})
                    page.screenshot(path=str(out/'desktop.png'))
                    api.patch('/api/mom/preferences',json={'font_scale':'xlarge'});page.reload();page.wait_for_function('()=>state.preferences!==null');page.set_viewport_size({'width':390,'height':844});orders(refund);page.locator('#sheetBody [data-action=service-detail]').click();f=form('assess');page.screenshot(path=str(out/'mobile-form.png'))
                    check('390px extra-large form has no horizontal overflow',page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth&&document.querySelector("#sheetBody").scrollWidth<=document.querySelector("#sheetBody").clientWidth'))
                    check('visible buttons have 44px targets',page.locator('#sheetBody button:visible').evaluate_all('(els)=>els.every(e=>e.getBoundingClientRect().height>=44)'))
                    check('no browser page errors',not errors)
                    browser.close()
            finally:stop_server(server)
    report={'browser':args.browser,'checks':checks,'check_count':len(checks),'page_errors':errors,'sources':sources,'source_unchanged':sources==source_manifest(),'passed':True}
    assert report['source_unchanged'],'Sources changed during verification'
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'browser':args.browser,'checks':len(checks),'passed':True}))


if __name__=='__main__':main()
