'use strict';
// Agency records are internal bookkeeping. Every supplier transaction and delivery is manual.
(() => {
  const A=window.MomApp, E=A.escapeHtml, $=s=>document.querySelector(s);
  const labels={quotes:'報價版本',tasks:'期限待辦',bookings:'訂購確認',ledger:'收付款',pretrip:'行前交付',lifecycle:'結案與重新開案'};
  const statusLabels={draft:'草稿／待補齊',sent:'已人工送出',accepted:'客人已採用',rejected:'客人未採用',replaced:'已被新版取代',withdrawn:'已撤回採用／未成交',open:'待處理',done:'已完成',cancelled:'已取消待辦',confirmed:'已核對',recorded:'已記錄',voided:'紀錄已作廢',unverified:'已上傳待核對',missing:'待補',ready:'文件已備妥',stale:'資料已變更',prepared:'摘要已備妥',delivered:'已人工交付'};
  const kinds={reply:'回覆客人',quote_followup:'追蹤報價',deposit:'訂金',balance:'尾款',ticketing:'開票期限',cancellation:'取消期限',document:'文件補件',pretrip:'行前交付',change:'改期／異動',refund:'退款',other:'其他／突發事件'};
  const docKinds={e_ticket:'電子機票',hotel_voucher:'住宿憑證',itinerary:'行程',visa_check:'簽證檢查',insurance:'保險',other:'其他'};
  const moneyKinds={customer_receipt:'客人收款',customer_refund:'退還客人',supplier_payment:'付供應商',supplier_refund:'供應商退款'};
  let tasksGeneration=0, homeGeneration=0;
  const path=c=>`/api/mom/cases/${encodeURIComponent(c)}`;
  const date=v=>new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date(v));
  // Amounts remain decimal strings; totals and balances are calculated by the server.
  const money=(currency,value)=>`${E(currency)} ${value==null?'待核對':E(value)}`;
  const btn=(text,action,c,extra='',primary=false,disabled=false)=>`<button type="button" class="${primary?'primary':'secondary'}-button" data-action="${action}" data-case-id="${E(c)}" ${extra} ${disabled?'disabled':''}>${E(text)}</button>`;
  const select=(label,name,choices,value='',required=true)=>`<label><span>${E(label)}</span><select name="${E(name)}" ${required?'required':''}>${Object.entries(choices).map(([k,v])=>`<option value="${E(k)}" ${k===value?'selected':''}>${E(v)}</option>`).join('')}</select></label>`;
  const text=(label,name,value='',required=true,max=4000)=>`<label><span>${E(label)}</span><textarea name="${E(name)}" rows="3" maxlength="${max}" ${required?'required':''}>${E(value)}</textarea></label>`;
  const input=(label,name,value='',attrs='required')=>A.field(label,name,value,attrs);
  const check=(name,label,checked=false,required=true)=>`<label class="checkbox-pill"><input name="${name}" type="checkbox" ${checked?'checked':''} ${required?'required':''}>${E(label)}</label>`;
  const record=(title,body,actions='',status='')=>`<article class="operation-record"><div class="card-top"><h3>${E(title)}</h3>${status?`<span class="case-status">${E(statusLabels[status]||status)}</span>`:''}</div>${body}<div class="operation-actions">${actions}</div></article>`;
  const note=t=>`<p class="muted preserve-lines">${E(t)}</p>`;
  const notice=t=>`<div class="notice-card warn">${E(t)}</div>`;
  const accepted=b=>b.quotes.find(q=>q.id===b.accepted_quote_id);
  const refs=(label,name,items,value='')=>select(label,name,{'':'不綁定',...Object.fromEntries(items.map(i=>[i.id,i.title]))},value||'',false);
  function evidence(label) {
    return input('內部核對依據（對話日期、收據或供應商通知編號）','reference','','required maxlength="500"')+
      input('實際完成時間（此欄使用裝置時區）','occurred_at',A.localDateTime(),'type="datetime-local" required')+check('checked',label);
  }
  function bookingSelector(b,selected='',kind='e_ticket') {
    const needed={e_ticket:'flight',hotel_voucher:'hotel'}[kind];
    const options=b.bookings.filter(v=>v.status==='confirmed'&&v.binding_current||v.id===selected);
    return `<label><span>關聯訂購（電子機票／住宿憑證備妥時必填）</span><select name="booking_id"><option value="">不綁定</option>${options.map(v=>`<option value="${E(v.id)}" data-kind="${v.kind}" ${v.id===selected?'selected':''} ${needed&&needed!==v.kind?'disabled':''}>${E(v.title)} · ${v.kind==='flight'?'機票':'飯店'} · ${v.status==='confirmed'&&v.binding_current?'目前有效':'歷史關聯，請改選'} · ${E(v.confirmation_number)}</option>`).join('')}</select></label>`;
  }
  function formHTML(body,submit) {return `<form id="operationForm" class="form-grid">${body}<button type="submit" class="primary-button full">${E(submit)}</button></form>`;}
  function focusAfter(selector){requestAnimationFrame(()=>$('#sheetBody')?.querySelector(selector)?.focus({preventScroll:true}));}
  async function openModule(c,module,focus='') {
    const generation=A.beginSheetRequest();
    if(generation===null)return;
    const b=await A.api(`${path(c)}/operations`);
    if(!A.sheetRequestCurrent(generation))return;
    if(!A.openSheet(`${b.case.customer_name} · ${labels[module]}`,renderModule(c,module,b),true,module==='tasks'?'deadlines':module==='bookings'?'confirmations':module==='ledger'?'payments':module,c,generation))return;
    A.setSheetBack(async()=>{await A.openCase(c);focusAfter(`[data-module="${module}"]`);});
    if(focus)focusAfter(focus);
  }
  function newButton(c,module,label,disabled=false) {return btn(label,'ops-form',c,`data-module="${module}" data-intent="create"`,true,disabled);}
  function editButton(c,module,id,intent,label) {return btn(label,'ops-form',c,`data-module="${module}" data-id="${E(id)}" data-intent="${intent}"`);}
  function publicButton(c,module,id,disabled=false) {return btn('開啟對客文件／列印','ops-document',c,`data-module="${module}" data-id="${E(id)}"`,false,disabled);}
  function renderTask(t,readonly=false) {
    const timing={overdue:'已逾期',today:'今天到期',upcoming:'之後到期'};
    const history=t.history?.length?`<details><summary>處理歷史</summary>${t.history.map(v=>note(`${date(v.at)}（台北） · ${v.actor}\n${v.reason}\n${v.reference||''}${v.changes?.owner?'\n負責人：'+v.changes.owner:''}`)).join('')}</details>`:'';
    return record(t.title,note(`${t.customer_name||''} · ${t.owner} · ${kinds[t.kind]}\n期限：${date(t.due_at)}（台北）${t.status==='open'?` · ${timing[t.timing]}`:''}\n來源：${t.source}\n${t.notes||''}${t.acknowledgement?'\n已確認看到，不代表已完成。':''}`)+history,btn('打開案件','open-case',t.case_id)+(readonly||t.case_closed?'':editButton(t.case_id,'tasks',t.id,'edit','更新期限／完成待辦')+(t.status==='open'?editButton(t.case_id,'tasks',t.id,'acknowledge','確認已看到'):'')),t.status);
  }
  function renderModule(c,module,b) {
    if(module==='lifecycle')return renderLifecycle(c,b);
    const html=renderWorkingModule(c,module,b);
    if(b.case.status!=='closed')return html;
    const fragment=new DOMParser().parseFromString(html,'text/html');
    fragment.querySelectorAll('[data-action="ops-form"]').forEach(node=>node.remove());
    return notice('案件已結案，以下保留歷史紀錄。需要修改時，請先記錄重新開案。')+fragment.body.innerHTML;
  }
  function renderLifecycle(c,b) {
    const state=b.lifecycle, closed=b.case.status==='closed';
    const history=b.case_events.length?b.case_events.slice().reverse().map(v=>record(v.action==='reopen'?'重新開案':v.outcome==='withdrawn'?'未成交結案':'完成業務結案',note(`${date(v.occurred_at)}（台北） · ${v.actor}\n原因：${v.reason}\n核對依據：${v.reference}${v.supplier_settlement_checked?'\n已人工核對供應商結算與後續服務':''}${v.withdraw_adoption_checked?'\n已明確核對撤回客人採用報價':''}`))).join(''):'<div class="empty-state">尚無結案／重新開案紀錄。舊案件可能只有進度標示，請先核對實際狀況。</div>';
    const section=(label,intent,blockers)=>`<article class="operation-record lifecycle-decision"><h3>${label}</h3>${blockers.length?blockers.map(notice).join(''):note('本站紀錄已符合條件；送出前仍須人工核對。')}${btn(label,'ops-form',c,`data-module="lifecycle" data-intent="${intent}"`,false,Boolean(blockers.length))}</article>`;
    return note('結案是本站的業務整理。供應商取消、退款、轉帳與客人聯絡仍須依旅行社原流程辦理。')+(closed?notice(state.last_outcome==='withdrawn'?'此案件為未成交結案。重新開案不會自動恢復已撤回的採用報價。':'此案件已結案，歷史紀錄僅供查看。')+btn('記錄重新開案','ops-form',c,'data-module="lifecycle" data-intent="reopen"',true):section('完成業務結案','completed',state.completed_blockers)+section('未成交結案','withdrawn',state.withdrawn_blockers))+'<h3>處理紀錄</h3>'+history;
  }
  function renderWorkingModule(c,module,b) {
    if(module==='quotes')return note('每版報價保留當時需求、所選價格、費用與退改條件。下載或複製後，請自行用 LINE／Email 送出；內部成本與核對依據不會放進對客文件。')+newButton(c,module,'建立報價新版')+(b.quotes.length?b.quotes.slice().reverse().map(q=>record(`第 ${q.version} 版 · ${q.title}`,note(`有效至 ${date(q.valid_until)}（台北）`)+Object.entries(q.totals).map(([k,v])=>`<p><b>${money(k,v)}</b> · 預估毛利：${money(k,q.expected_margin[k])}</p>`).join('')+(q.events.length?`<details><summary>版本處理紀錄</summary>${q.events.map(v=>note(`${{sent:'已人工送出',accept:'客人採用',reject:'客人未採用',replaced:'已被新版取代',withdrawn:'已核對撤回採用'}[v.action]||v.action} · ${date(v.at)}\n${v.reference||v.reason||''}`)).join('')}</details>`:''),publicButton(c,module,q.id)+(q.status==='draft'?editButton(c,module,q.id,'sent','記錄已人工送出'):'')+(q.status==='sent'?editButton(c,module,q.id,'accept','記錄客人採用')+editButton(c,module,q.id,'reject','記錄客人未採用'):''),q.status)).join(''):'<div class="empty-state">尚無正式報價。先到「比較與選方案」選取有效方案，再建立第一版。</div>');
    if(module==='tasks')return btn('記錄待辦交接','ops-form',c,'data-module="tasks" data-intent="handover"')+note('把訂金、尾款、開票、取消、補件與回覆期限放在這裡。期限以台北時間顯示，系統不會自動通知或替您開票。')+newButton(c,module,'新增案件待辦')+(b.work_items.length?b.work_items.map(t=>renderTask(t,b.case.status==='closed')).join(''):'<div class="empty-state">尚無待辦。可先記錄下一次回覆與供應商期限。</div>');
    if(module==='bookings')return b.warnings.filter(w=>w.includes('確認號也登錄')).map(notice).join('')+note('請先在旅行社或供應商系統完成訂購，再填已核對的確認號。作廢只修正本站紀錄，取消訂購仍須聯絡供應商。')+(!accepted(b)?notice('尚未記錄客人採用報價，請先完成報價流程。'):'')+newButton(c,module,'新增訂購確認',!accepted(b))+(b.bookings.length?b.bookings.map(v=>record(v.title,note(`${v.kind==='flight'?'機票':'飯店'} · ${v.supplier}\n確認號：${v.confirmation_number}\n${v.customer_details}\n核對依據：${v.reference}`)+(v.quote_id!==b.accepted_quote_id?notice('這筆屬於舊版報價，請核對異動後重新登錄；原紀錄保留。'):''),v.status!=='voided'?(!v.binding_current?editButton(c,module,v.id,'rebind','重新核對／沿用至本版'):'')+editButton(c,module,v.id,'void','作廢錯誤紀錄'):'',v.status)).join(''):'<div class="empty-state">尚無訂購確認。需記錄機票／飯店各項供應商的正式確認。</div>');
    if(module==='ledger')return note('這是人工對帳紀錄，不會轉帳。按幣別分開；現金收付差額不是毛利。未知成本／不同幣別不會自動換算。')+Object.entries(b.balances).map(([k,v])=>record(`${k} 對帳`,[['報價總額',v.quote_total],['客人淨收款',v.net_received],['客人尚欠（負數為溢收）',v.customer_balance],['供應商淨付款',v.net_paid],['收付差額',v.net_cash],['預估毛利（成本完整才計算）',v.expected_margin]].map(([label,value])=>`<div class="money-row"><span>${E(label)}</span><b>${money(k,value)}</b></div>`).join(''))).join('')+(!accepted(b)?notice('尚未記錄客人採用報價，無法新增收付款。'):'')+newButton(c,module,'新增實際收付款',!accepted(b))+(b.ledger.length?b.ledger.slice().reverse().map(v=>record(moneyKinds[v.kind],note(`${v.currency} ${v.amount} · ${date(v.occurred_at)}（台北）\n核對依據：${v.reference}\n${v.memo}`),v.status!=='voided'?editButton(c,module,v.id,'void','作廢錯誤紀錄'):'',v.status)).join(''):'<div class="empty-state">尚未記錄實際收付款。</div>');
    return btn('旅客名冊與原始文件','files-open',c,'',true)+note('先逐項核對文件，再產生行前摘要。摘要提供對客說明與連結；電子機票／住宿憑證原檔仍須您另外交付。訂購或文件變更後，請產生新版摘要。')+b.warnings.map(notice).join('')+newButton(c,module,'新增文件清單項目')+b.documents.map(v=>record(v.title,note(`${docKinds[v.kind]} · ${v.required?'必備':'選用'}${v.needs_recheck?' · 需求或訂購已變更，須重新核對':''}\n${v.customer_text||'尚未填對客說明'}${v.customer_url?`\n${v.customer_url}`:''}`),editButton(c,module,v.id,'document','核對文件／補件'),v.needs_recheck?'stale':v.status==='missing'&&v.attachment_state?.active?'unverified':v.status)).join('')+btn('產生行前摘要新版','ops-form',c,`data-module="pretrip" data-intent="pack"`,true,!accepted(b))+(!accepted(b)?notice('尚未記錄客人採用報價，無法產生行前摘要。'):'')+(b.pretrip.length?b.pretrip.slice().reverse().map(p=>record(`第 ${p.version} 版 · ${p.title}`,p.stale?notice('資料已變更，此版本已失效。請重新產生摘要。'):p.blockers.map(notice).join('')+(p.status==='draft'?notice('草稿不可複製、列印或交付。補齊後請產生新版。'):'')+(p.delivery?note(`已交付：${p.delivery.channel} · ${date(p.delivery.occurred_at)}（台北）\n依據：${p.delivery.reference}`):''),publicButton(c,module,p.id,p.stale||!['prepared','delivered'].includes(p.status))+(p.status==='prepared'&&!p.stale?editButton(c,module,p.id,'deliver','記錄已人工交付'):''),p.stale?'stale':p.status)).join(''):'<div class="empty-state">尚無行前摘要；缺件時可先產生草稿，補齊後再產生可交付版本。</div>');
  }
  async function openForm(c,module,intent,id,trigger) {
    const generation=A.beginSheetRequest();
    if(generation===null)return;
    const b=await A.api(`${path(c)}/operations`);
    if(b.case.status==='closed'&&!(module==='lifecycle'&&intent==='reopen'))throw new Error('案件已結案，請先記錄重新開案。');
    let workflow=null;
    if(module==='quotes'&&intent==='create')workflow=await A.api(`${path(c)}/options`);
    if(!A.sheetRequestCurrent(generation))return;
    let body='',payload,endpoint,method='POST',title='',submit='儲存紀錄';
    const q=accepted(b), item=id?(b[{quotes:'quotes',tasks:'work_items',bookings:'bookings',ledger:'ledger',pretrip:intent==='document'?'documents':'pretrip'}[module]]||[]).find(v=>v.id===id):null;
    if(id&&!item)throw new Error('紀錄已不存在，請重新開啟案件。');
    const values=form=>Object.fromEntries(new FormData(form));
    const proof=v=>({reference:v.reference,occurred_at:new Date(v.occurred_at).toISOString(),checked:v.checked==='on'});
    if(module==='lifecycle') {
      const reopen=intent==='reopen', completed=intent==='completed';
      title=reopen?'記錄重新開案':completed?'完成業務結案':'未成交結案';
      const blockers=reopen?[]:b.lifecycle[`${intent}_blockers`];
      if(blockers.length)throw new Error(blockers.join('；'));
      body=notice(reopen?'重新開案後會依目前有效報價與訂購推算進度。已撤回的採用不會恢復，原收付款、文件與歷史均保留。':completed?'請核對交付、客人款項、供應商結算及後續服務。結案後案件僅供查看。':'請先依原流程處理取消與退款。本站會保留所有歷史，結案後案件僅供查看。')+text(reopen?'重新開案原因':'結案原因','reason','',true,500)+evidence(reopen?'我已核對重新開案原因與現有業務紀錄。':'我已核對結案原因、待辦與收付款。');
      if(completed)body+=check('supplier_settlement_checked','我已人工核對供應商款項與後續服務均已處理。');
      if(!reopen&&!completed&&q)body+=notice('客人曾採用此報價；此次未成交結案將明確撤回採用，並保留原採用歷史。')+check('withdraw_adoption_checked','我已核對客人決定，確認撤回原採用報價。');
      endpoint=`lifecycle/${reopen?'reopen':'close'}`;
      payload=v=>({...proof(v),reason:v.reason,expected_state:b.lifecycle.expected_state,...(reopen?{}:{outcome:intent,...(completed?{supplier_settlement_checked:v.supplier_settlement_checked==='on'}:q?{withdraw_adoption_checked:v.withdraw_adoption_checked==='on'}:{})})});
      submit=title;
    } else if(intent==='rebind') {
      title='重新核對訂購並沿用至本版';body=note(`${item.title} · ${item.confirmation_number}`)+notice('請在供應商核對這個確認號仍符合目前採用報價、日期與旅客。保留原確認號及歷史，不會作廢實際訂單。')+text('重新核對後的對客內容','customer_details',item.customer_details)+input('重新核對／異動原因','reason','','required maxlength="500"')+evidence('我已在供應商正式系統重新核對此確認號，確認符合目前採用版本。');
      endpoint=`bookings/${id}/rebind`;payload=v=>({...proof(v),reason:v.reason,customer_details:v.customer_details});submit='保存重新核對紀錄';
    } else if(intent==='void') {
      title='作廢錯誤紀錄';body=notice('只作廢本站記錄。供應商取消、退款或銀行轉帳仍須另行處理。')+text('作廢原因','reason','',true,500)+evidence('我已核對原紀錄及作廢依據，確認是修正本站記錄。');
      endpoint=`${module}/${id}/void`;payload=v=>({...proof(v),reason:v.reason});
    } else if(module==='quotes'&&intent==='create') {
      if(!workflow.can_draft_offer) {A.openSheet('尚不能建立報價',notice('請先選取仍有效、符合案件需求的實際方案。')+btn('比較與選方案','case-options',c),true,'quotes',c,generation);return;}
      title='建立報價新版';const expiry=workflow.selections.map(o=>new Date(o.valid_until||new Date(new Date(o.observed_at).getTime()+24*3600000)));
      const until=new Date(Math.min(Date.now()+3600000,...expiry.map(v=>v.getTime())));
      const currencies=[...new Set(workflow.selections.map(o=>o.currency))];
      body=workflow.selections.map(o=>record(o.title,note(`${o.currency} ${o.total_amount}\n${o.conditions}`))).join('')+input('報價名稱','title',`${b.case.destination||'旅行'}方案報價`,'required maxlength="160"')+input('報價有效至（裝置時區；不能晚於供應商期限）','valid_until',A.localDateTime(until),'type="datetime-local" required')+text('包含項目與服務','includes')+text('不含項目、退改與付款條件','excludes')+currencies.map(currency=>`<div class="form-grid two">${input(`${currency} 服務費`,'fee_'+currency,'0','type="number" min="0" step="0.01" required')}${input(`${currency} 折扣`,'discount_'+currency,'0','type="number" min="0" step="0.01" required')}</div>`).join('')+'<details><summary>內部成本（選填，不放入對客文件）</summary>'+workflow.selections.map(o=>input(`${o.title} · ${o.currency}`,'cost_'+o.id,'','type="number" min="0" step="0.01"')).join('')+'</details>';
      endpoint='quotes';payload=v=>({title:v.title,valid_until:new Date(v.valid_until).toISOString(),includes:v.includes,excludes:v.excludes,adjustments:currencies.map(currency=>({currency,service_fee:v['fee_'+currency],discount:v['discount_'+currency]})),costs:Object.fromEntries(workflow.selections.filter(o=>v['cost_'+o.id]!=='').map(o=>[o.id,v['cost_'+o.id]]))});submit='保存報價新版';
    } else if(module==='quotes') {
      title={sent:'記錄已人工送出報價',accept:'記錄客人採用報價',reject:'記錄客人未採用'}[intent];
      body=note(`第 ${item.version} 版 · ${item.title}`)+evidence(intent==='sent'?'我已核對這一版並透過 LINE／Email 等方式實際送給客人。':intent==='accept'?'我已核對客人的明確採用回覆及此版本內容。':'我已確認客人未採用此版本。');
      if(intent==='accept'&&q&&q.id!==id)body+=notice('已有採用版本；更換後，收付款與舊訂購紀錄保留，訂購確認與行前文件須重新核對。')+check('amend','我已核對這次報價異動及訂購、付款影響。')+text('更換採用版本的原因','reason','',true,1000);
      endpoint=`quotes/${id}/${intent}`;payload=v=>({...proof(v),amend:v.amend==='on',reason:v.reason||''});submit=title;
    } else if(module==='tasks'&&intent==='acknowledge') {
      title='確認已看到待辦';body=note(item.title)+notice('已確認看到，不代表已完成。負責人或期限變更後須重新確認。')+evidence('我已核對這項待辦及目前期限。');endpoint=`work-items/${id}/acknowledge`;payload=v=>({...proof(v),expected_revision:item.revision});
    } else if(module==='tasks'&&intent==='handover') {
      const open=b.work_items.filter(t=>t.status==='open');if(!open.length)throw new Error('沒有待處理的待辦可交接。');
      title='記錄待辦交接';body=notice('這會更新負責人及保留交接紀錄。系統沒有傳訊息給新負責人。')+open.map(t=>check('item_'+t.id,`${t.title} · ${t.owner}`,false,false)).join('')+input('新負責人','owner','','required maxlength="100"')+text('交接原因與處理重點','reason','',true,500)+evidence('我已核對交接項目、期限與新負責人。');endpoint='work-handover';payload=v=>({...proof(v),owner:v.owner,reason:v.reason,items:Object.fromEntries(open.filter(t=>v['item_'+t.id]==='on').map(t=>[t.id,t.revision]))});
    } else if(module==='tasks') {
      title=intent==='create'?'新增案件待辦':'更新期限／完成待辦';
      if(intent==='create')body=select('常用待辦（可選；仍須填實際期限與依據）','task_template',{'':'自行填寫',reply:'回覆客人',deposit:'追蹤訂金',balance:'追蹤尾款',ticketing:'確認開票期限',cancellation:'確認取消期限',document:'追蹤補件',pretrip:'交付行前資料',change:'改期／異動：核對供應商與客人決定',refund:'退款：核對金額與供應商處理',other:'突發事件：追蹤協助與後續安排'},'',false)+input('待辦名稱','title','','required maxlength="500"')+select('工作種類','kind',kinds)+input('負責人','owner','','required maxlength="100"')+input('期限（裝置時區）','due_at','','type="datetime-local" required')+input('期限來源（供應商通知、客人約定等）','source','','required maxlength="500"')+refs('關聯報價','quote_id',b.quotes)+refs('關聯訂購','booking_id',b.bookings)+refs('關聯文件','document_id',b.documents)+text('備註','notes','',false,2000);
      else body=note(item.title)+select('處理狀態','status',{open:'待處理',done:'已完成',cancelled:'取消這項待辦'},item.status)+input('負責人','owner',item.owner,'required maxlength="100"')+input('期限（裝置時區）','due_at',A.localDateTime(item.due_at),'type="datetime-local" required')+text('備註','notes',item.notes,false,2000)+input('此次更新原因／完成依據','reason','','required maxlength="500"');
      endpoint=intent==='create'?'work-items':`work-items/${id}`;method=intent==='create'?'POST':'PATCH';payload=v=>intent==='create'?{title:v.title,kind:v.kind,owner:v.owner,due_at:new Date(v.due_at).toISOString(),source:v.source,notes:v.notes,quote_id:v.quote_id||null,booking_id:v.booking_id||null,document_id:v.document_id||null}:{status:v.status,owner:v.owner,due_at:new Date(v.due_at).toISOString(),notes:v.notes,reason:v.reason,expected_revision:item.revision};
    } else if(module==='bookings') {
      if(!q)throw new Error('請先記錄客人採用的報價。');title='新增已核對的訂購確認';
      body=select('訂購種類','kind',Object.fromEntries(q.items.map(v=>[v.kind,v.kind==='flight'?'機票':'飯店'])))+input('對客名稱（放入行前摘要）','title','','required maxlength="200"')+text('對客內容（日期、旅客、航班或房型等）','customer_details')+input('內部供應商／窗口','supplier','','required maxlength="160"')+input('正式訂購確認號（放入行前摘要）','confirmation_number','','required maxlength="100"')+evidence('我已在供應商正式系統核對日期、旅客、方案及確認號；不是只有詢價或查價。');
      endpoint='bookings';payload=v=>({...proof(v),kind:v.kind,title:v.title,customer_details:v.customer_details,supplier:v.supplier,confirmation_number:v.confirmation_number});
    } else if(module==='ledger') {
      if(!q)throw new Error('請先記錄客人採用的報價。');title='新增實際收付款';
      body=select('收付種類','kind',moneyKinds)+input('實際金額','amount','','type="number" min="0.01" step="0.01" required')+input('幣別（例如 TWD／USD）','currency',Object.keys(q.totals)[0],'required pattern="[A-Z]{3}" maxlength="3"')+refs('關聯訂購（選填）','booking_id',b.bookings.filter(v=>v.status==='confirmed'))+text('內部備註','memo','',false,1000)+evidence('我已核對實際收款／付款或退款憑據；這不是預定收付。');
      endpoint='ledger';payload=v=>({...proof(v),kind:v.kind,amount:v.amount,currency:v.currency,booking_id:v.booking_id||null,memo:v.memo});
    } else if(intent==='create') {
      title='新增文件清單項目';body=select('文件種類','kind',docKinds)+input('文件名稱','title','','required maxlength="500"')+check('required','此文件是交付前必備項目。',true,false)+bookingSelector(b);
      endpoint='documents';payload=v=>({kind:v.kind,title:v.title,required:v.required==='on',booking_id:v.booking_id||null});
    } else if(intent==='document') {
      title='核對文件／補件';body=note(item.title)+check('required','此文件是交付前必備項目。',item.required,false)+bookingSelector(b,item.booking_id,item.kind)+input('修改必備標示／關聯的原因（未變更可留白）','reason','','maxlength="500"')+select('文件狀態','status',{missing:'待補／需重新核對',ready:'文件已備妥'},item.needs_recheck?'missing':item.status)+text('對客說明（不要填內部成本或帳密）','customer_text',item.customer_text,false,6000)+input('對客文件連結（HTTPS；不含帳密；可留白）','customer_url',item.customer_url||'','type="url" maxlength="2000"')+evidence('我已人工核對此文件狀態、內容、日期與旅客；連結並未由系統自動驗證。');
      endpoint=`documents/${id}`;method='PATCH';payload=v=>({...proof(v),expected_revision:item.revision,status:v.status,customer_text:v.customer_text,customer_url:v.customer_url||null,required:v.required==='on',booking_id:v.booking_id||null,reason:v.reason});
    } else if(intent==='pack') {
      title='產生行前摘要新版';body=b.warnings.map(notice).join('')+input('行前摘要名稱','title',`${b.case.destination||'旅行'}行前資料`,'required maxlength="200"')+note('保留當下報價、訂購與文件版本。缺件會生成草稿，不能標記交付。摘要不會合併原始附件或自動寄送。');endpoint='pretrip';payload=v=>({title:v.title});submit='產生摘要新版';
    } else if(intent==='deliver') {
      title='記錄已人工交付';body=note(`第 ${item.version} 版 · ${item.title}`)+input('實際交付管道','channel','','required maxlength="100"')+evidence('我已核對完整摘要及電子機票／住宿憑證等原件，並實際交付給客人。');endpoint=`pretrip/${id}/deliver`;payload=v=>({...proof(v),channel:v.channel});submit=title;
    }
    if(!payload)throw new Error('不支援的操作，請重新開啟案件。');
    if(!A.openSheet(title,formHTML(body,submit),true,module==='tasks'?'deadlines':module==='bookings'?'confirmations':module==='ledger'?'payments':module,c,generation))return;
    const form=$('#operationForm'), stamp=A.currentSheetGeneration();
    form.operation={c,module,endpoint,method,payload,values,stamp,intent:null,origin:trigger?.closest('#homeDeadlines,#allDeadlines')?.id||'module',id};
    A.setSheetBack(()=>returnToOrigin(form.operation,`[data-action="ops-form"][data-intent="${intent}"]${id?`[data-id="${id}"]`:''}`),form.operation.origin==='homeDeadlines'?'返回工作總覽':form.operation.origin==='allDeadlines'?'返回全部待辦':'返回'+labels[module]);
    form.addEventListener('change',event=>{
      if(event.target.name==='task_template'&&event.target.value) {
        form.elements.title.value=event.target.selectedOptions[0].textContent;
        form.elements.kind.value=event.target.value;
      }
      if(event.target.name==='kind'&&form.elements.booking_id&&module==='pretrip') {
        const needed={e_ticket:'flight',hotel_voucher:'hotel'}[event.target.value];
        [...form.elements.booking_id.options].forEach(o=>{o.disabled=Boolean(o.value&&needed&&o.dataset.kind!==needed);});
        if(form.elements.booking_id.selectedOptions[0]?.disabled)form.elements.booking_id.value='';
      }
    });
  }
  async function returnToOrigin(op,focus='') {
    if(op.origin==='module')return openModule(op.c,op.module,focus);
    if(!A.closeSheet())return;
    if(op.origin==='homeDeadlines')await loadHomeDeadlines();else await loadTasks();
    requestAnimationFrame(()=>{
      const target=$(`#${op.origin} [data-id="${op.id}"]`)||$(op.origin==='homeDeadlines'?'#deadlineHomeTitle':'#tasksTitle');
      target.tabIndex=target.matches('button')?0:-1;target.focus({preventScroll:true});
    });
  }
  async function submit(form) {
    const op=form.operation, data=op.payload(op.values(form)), signature=JSON.stringify(data);
    // Reuse the UUID for uncertain failures. A changed form is a new intent.
    if(op.intent?.signature!==signature)op.intent={signature,id:crypto.randomUUID()};
    try {await A.api(`${path(op.c)}/${op.endpoint}`,{method:op.method,body:JSON.stringify({...data,request_id:op.intent.id})});}
    catch(err){if(err.status>=400&&err.status<500)op.intent=null;throw err;}
    A.markFormCommitted(form,'ops-open',{caseId:op.c,module:op.module});form.dataset.dirty='false';A.showToast(op.endpoint==='work-handover'?'交接已記錄；系統沒有傳訊息給新負責人。':'已保存，歷史紀錄會保留。');
    if(A.sheetRequestCurrent(op.stamp)&&form.isConnected)await returnToOrigin(op);
    if(op.module==='lifecycle')await A.loadCases();
    await A.loadHome();
    if($('#view-tasks').classList.contains('is-active'))await loadTasks();
  }
  async function openDocument(el) {
    // Open synchronously, then authenticate through the shared API helper. Never put tokens in URLs.
    const popup=window.open('about:blank','_blank');
    if(!popup){A.showToast('瀏覽器阻擋了新分頁，請允許此網站開啟分頁後再試。');return;}
    popup.opener=null;
    try {
      const html=await A.api(`${path(el.dataset.caseId)}/${el.dataset.module}/${encodeURIComponent(el.dataset.id)}/document`);
      const doc=new DOMParser().parseFromString(html,'text/html');
      doc.querySelectorAll('[src],[href]').forEach(node=>{const attr=node.hasAttribute('src')?'src':'href';const url=node.getAttribute(attr);if(url?.startsWith('/static/'))node.setAttribute(attr,new URL(url,location.origin).href);});
      popup.document.open();popup.document.write('<!doctype html>'+doc.documentElement.outerHTML);popup.document.close();
    }catch(err){popup.close();throw err;}
  }
  async function loadTasks() {
    const generation=++tasksGeneration;
    try {const {items}=await A.api('/api/mom/work-items');if(generation!==tasksGeneration)return;const filter=$('#taskStatusFilter').value;const visible=items.filter(t=>t.status===filter);const today=new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'});const horizon=new Date(Date.now()+7*86400000).toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'});const buckets={overdue:'逾期',today:'今天',week:'未來 7 天（不含今天）',later:'較晚的期限'};const summary=filter==='open'?Object.entries(buckets).map(([key,label])=>{const group=visible.filter(t=>{const day=new Date(t.due_at).toLocaleDateString('sv-SE',{timeZone:'Asia/Taipei'});return key==='overdue'?t.timing==='overdue':key==='today'?t.timing==='today':key==='week'?day>today&&day<=horizon:day>horizon;});return `<details class="task-summary" ${key==='overdue'||key==='today'?'open':''}><summary>${E(label)} · ${group.length} 件</summary>${group.length?[...new Set(group.map(t=>t.owner.trim().replace(/\s+/g,' ')))].map(owner=>`<h3>${E(owner)}</h3>`+group.filter(t=>t.owner.trim().replace(/\s+/g,' ')===owner).map(t=>renderTask(t)).join('')).join(''):'<p class="muted">沒有待辦。</p>'}</details>`;}).join(''):visible.map(t=>renderTask(t)).join('');$('#allDeadlines').innerHTML=visible.length?summary:'<div class="empty-state">沒有符合的待辦。請從案件的「期限待辦」新增。</div>';}
    catch(err){if(!(err instanceof A.ReauthenticationError))renderLoadError('allDeadlines',err,'ops-refresh-tasks');}
  }
  function renderLoadError(id,err,action) {
    const container=$('#'+id);container.querySelector('.operation-load-error')?.remove();
    container.insertAdjacentHTML('afterbegin',`<div class="notice-card warn operation-load-error" role="alert">資料更新失敗，畫面可能仍是上次內容。${E(A.friendlyError(err))}${btn('重新載入',action,'')}</div>`);
  }
  async function loadHomeDeadlines() {
    const generation=++homeGeneration;
    try {
      const {items}=await A.api('/api/mom/work-items');if(generation!==homeGeneration)return;
      const urgent=items.filter(t=>t.status==='open'&&['overdue','today'].includes(t.timing));
      $('#homeDeadlines').innerHTML=urgent.length?urgent.map(t=>renderTask(t)).join(''):'<div class="empty-state">目前沒有逾期或今天到期的待辦。之後的期限可到「待辦」查看。</div>';
    }catch(err){if(generation===homeGeneration&&!(err instanceof A.ReauthenticationError))renderLoadError('homeDeadlines',err,'ops-refresh-home');}
  }
  A.registerAction('ops-open',el=>openModule(el.dataset.caseId,el.dataset.module,el.dataset.recordId?`[data-id="${CSS.escape(el.dataset.recordId)}"]`:''));
  A.registerAction('ops-form',el=>openForm(el.dataset.caseId,el.dataset.module,el.dataset.intent,el.dataset.id||'',el));
  A.registerAction('ops-document',openDocument);
  A.registerAction('ops-refresh-tasks',loadTasks);
  A.registerAction('ops-refresh-home',loadHomeDeadlines);
  A.registerForm('operationForm',submit);
  A.registerView('tasks',loadTasks);
  A.registerHomeLoader(loadHomeDeadlines);
  $('#taskStatusFilter').addEventListener('change',loadTasks);
})();
