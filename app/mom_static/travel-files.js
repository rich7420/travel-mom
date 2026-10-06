'use strict';
// Full private fields exist only after explicit reveal; uploads keep non-sensitive retry receipts.
(() => {
  const P=window.TravelPrivacy;
  const A=window.MomApp,E=A.escapeHtml,$=s=>document.querySelector(s);
  const base=c=>`/api/mom/cases/${encodeURIComponent(c)}`;
  const categories={adult:'大人',child:'小孩',infant:'嬰兒'};
  const button=(label,action,c,extra='')=>`<button type="button" class="secondary-button" data-action="${action}" data-case-id="${E(c)}" ${extra}>${E(label)}</button>`;
  const field=(label,name,value='',attributes='required')=>A.field(label,name,value,attributes);
  const proof=()=>field('核對依據（填通知編號，請勿填護照資料）','reference','','required maxlength="500"')+field('實際完成時間（裝置時區）','occurred_at',A.localDateTime(),'type="datetime-local" required')+'<label class="checkbox-pill"><input type="checkbox" name="checked" required>我已核對內容、旅客與日期。</label>';
  const evidence=v=>({reference:v.reference,occurred_at:new Date(v.occurred_at).toISOString(),checked:v.checked==='on'});
  const key=c=>'travel-upload-intents:'+c;
  const pending=c=>{try{return JSON.parse(sessionStorage.getItem(key(c))||'[]');}catch{return [];}};
  function storePending(c,values){if(values.length)sessionStorage.setItem(key(c),JSON.stringify(values));else sessionStorage.removeItem(key(c));}
  function forget(c,id){storePending(c,pending(c).filter(p=>p.id!==id));}
  async function open(c,focus='') {
    const generation=A.beginSheetRequest();if(generation===null)return;
    let reconciliation='';
    for(const intent of pending(c)) {
      const receipt=await A.api(`${base(c)}/attachment-receipts/${intent.id}`);
      if(receipt.committed){forget(c,intent.id);reconciliation='已確認上次原件儲存成功，沒有重複上傳。';}
      else reconciliation='上次上傳尚未查到已保存紀錄。請回到該文件重新選擇原件；系統會沿用原重試編號。';
    }
    const b=await A.api(`${base(c)}/travel-files`);if(!A.sheetRequestCurrent(generation))return;
    const roster=b.roster;
    const message=!roster.used?'尚未建立名冊。已使用名冊的案件，交付前須人數相符並完成核對。':roster.current?'目前名冊已核對。':'名冊或需求已變更，需重新核對。';
    const travellerRows=b.travellers.map((t,i)=>`<article class="operation-record"><h3>旅客 ${i+1} · ${E(categories[t.category])}${t.status==='archived'?' · 已封存':''}</h3><p class="muted">姓名、生日與護照資料預設隱藏。</p><div class="operation-actions">${button('票號與特殊需求','files-service-open',c,`data-id="${E(t.id)}"`)+button('查看完整資料','files-reveal',c,`data-id="${E(t.id)}"`)}${!b.case_closed&&t.status==='active'?button('修改旅客','files-form',c,`data-intent="traveller" data-id="${E(t.id)}"`)+button('封存移出名冊','files-form',c,`data-intent="traveller-archive" data-id="${E(t.id)}"`):''}</div></article>`).join('');
    const documents=b.documents.map(doc=>{
      const files=b.attachments.filter(a=>a.document_id===doc.id);
      return `<article class="operation-record"><h3>${E(doc.title)}</h3><p class="muted">${doc.needs_recheck?'內容已變更，需重新核對':doc.status==='ready'?'已核對':files.some(a=>a.status==='active')?'已上傳待核對':'尚無有效原件'} · ${files.length} 份原件</p>${files.map((a,index)=>`<div class="file-row"><p class="muted">原件 ${index+1} · ${E(new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',dateStyle:'short',timeStyle:'short'}).format(new Date(a.created_at)))}（台北）</p><span>${E(a.media_type.split('/')[1].toUpperCase())} · ${Math.ceil(a.size/1024)} KB · ${a.status==='archived'?'已封存':'待人工核對／保留原件'}</span><div class="operation-actions">${button('下載原件','files-download',c,`data-id="${E(a.id)}"`)}${!b.case_closed&&a.status==='active'?button('封存原件','files-form',c,`data-intent="attachment-archive" data-id="${E(a.id)}"`):''}</div></div>`).join('')}${!b.case_closed?button('上傳原件','files-form',c,`data-intent="upload" data-id="${E(doc.id)}"`):''}</article>`;
    }).join('');
    const html=`${b.case_closed?'<div class="notice-card warn">案件已結案，僅供查看與下載。</div>':''}${reconciliation?`<p class="notice-card" role="status">${E(reconciliation)}</p>`:''}<details class="private-section" open><summary>旅客名冊 · ${roster.count} 位</summary><p class="muted">${E(message)} 類別請按此次訂購規則人工選擇；系統不判定簽證資格或護照效期門檻。</p>${!b.case_closed?button('新增旅客','files-form',c,'data-intent="traveller"')+button('核對整份名冊','files-form',c,'data-intent="verify"'):''}${travellerRows||'<p class="empty-state">尚無旅客資料。</p>'}</details><details class="private-section" open><summary>原始文件 · ${b.attachments.length} 份</summary><p class="muted">上傳、封存都須重新核對文件，並重新產生行前摘要。封存保留歷史。PDF、JPEG、PNG，單檔最多 10 MB；原件不會附在對客摘要中。</p>${documents||'<p class="empty-state">請先在行前交付新增文件清單項目，再上傳原件。</p>'}</details>`;
    if(!A.openSheet('旅客名冊與原始文件',html,true,'pretrip',c,generation))return;
    A.setSheetBack(()=>A.openCase(c),'返回案件');
    if(focus)requestAnimationFrame(()=>$('#sheetBody').querySelector(focus)?.focus());
  }
  async function reveal(el){
    const token=P.capture(),c=el.dataset.caseId,id=el.dataset.id,generation=A.beginSheetRequest();if(generation===null)return;
    const value=await A.api(`${base(c)}/travellers/${encodeURIComponent(id)}/reveal`);
    if(!A.sheetRequestCurrent(generation)||!P.current(token))return;
    const labels={name:'證件姓名',date_of_birth:'生日',passport_number:'護照號碼',passport_expiry:'護照效期',nationality:'國籍'};
    if(!A.openSheet('查看旅客資料',`<div data-private>${Object.entries(labels).map(([k,label])=>`<p><b>${E(label)}</b><br>${E(value[k])}</p>`).join('')}${button('隱藏並返回名冊','files-open',c)}</div>`,true,'pretrip',c,generation))return;
    A.setSheetBack(()=>open(c,`[data-action="files-reveal"][data-id="${CSS.escape(id)}"]`),'返回名冊');
  }
  async function form(el){
    const token=P.capture(),c=el.dataset.caseId,id=el.dataset.id||'',intent=el.dataset.intent;
    const generation=A.beginSheetRequest();if(generation===null)return;
    const b=await A.api(`${base(c)}/travel-files`);
    if(b.case_closed)throw new Error('案件已結案，請先重新開案。');
    let body='',endpoint='',method='POST',payload,title='';
    if(intent==='traveller') {
      const t=id?await A.api(`${base(c)}/travellers/${encodeURIComponent(id)}/reveal`):{};
      title=id?'修改旅客資料':'新增旅客資料';
      body=field('證件姓名','name',t.name||'','required maxlength="120" autocomplete="off"')+`<label><span>此次訂購旅客類別（按供應商規則核對）</span><select name="category">${Object.entries(categories).map(([k,label])=>`<option value="${k}" ${k===t.category?'selected':''}>${label}</option>`).join('')}</select></label>`+field('生日','date_of_birth',t.date_of_birth||'','type="date" required')+field('護照號碼','passport_number',t.passport_number||'','required maxlength="40" autocomplete="off"')+field('護照效期','passport_expiry',t.passport_expiry||'','type="date" required')+field('國籍','nationality',t.nationality||'','required maxlength="80"');
      endpoint=id?`travellers/${encodeURIComponent(id)}`:'travellers';method=id?'PATCH':'POST';const revision=t.revision;payload=v=>({...v,...(id?{expected_revision:revision}:{})});
    } else if(intent==='verify') {
      title='核對整份旅客名冊';body='<p class="notice-card">請先逐一核對證件姓名、生日、護照與國籍。此核對保留目前全部旅客與需求，之後修改將失效。</p>'+proof();endpoint='roster/verify';payload=v=>({...evidence(v),expected_state:b.roster.expected_state});
    } else if(intent==='upload') {
      const doc=b.documents.find(d=>d.id===id);if(!doc)throw new Error('文件已不存在。');
      title='上傳原始文件';body=`<p>${E(doc.title)}</p><label><span>選擇 PDF、JPEG 或 PNG（最多 10 MB）</span><input type="file" name="file" accept="application/pdf,image/jpeg,image/png" required></label><p class="muted">原件僅供本站登入者下載。上傳後仍須核對，系統沒有進行防毒掃描。</p><p id="uploadStatus" role="status"></p>`;endpoint=`documents/${encodeURIComponent(id)}/attachments`;payload=null;
    } else {
      const traveller=intent==='traveller-archive',value=(traveller?b.travellers:b.attachments).find(t=>t.id===id);if(!value)throw new Error('紀錄已不存在。');
      title=traveller?'封存旅客':'封存原件';body='<p class="notice-card">保留歷史，不刪除資料；此案件須重新核對。</p>'+field('原因','reason','','required maxlength="500"')+proof();endpoint=`${traveller?'travellers':'attachments'}/${encodeURIComponent(id)}/archive`;payload=v=>({...evidence(v),reason:v.reason,expected_revision:value.revision});
    }
    if(!A.sheetRequestCurrent(generation)||!P.current(token))return;
    if(!A.openSheet(title,`<form id="travelFileForm" class="form-grid" ${['traveller','upload'].includes(intent)?'data-private':''}>${body}<button type="submit" class="primary-button full">${E(title)}</button></form>`,true,'pretrip',c,generation))return;
    const node=$('#travelFileForm');node.travelOperation={c,id,intent,endpoint,method,payload,stamp:A.currentSheetGeneration(),revision:b.documents.find(d=>d.id===id)?.revision};
    A.setSheetBack(()=>open(c,`[data-action="files-form"][data-intent="${intent}"]${id?`[data-id="${CSS.escape(id)}"]`:''}`),'返回名冊與原件');
  }
  async function submit(form){
    const op=form.travelOperation;
    if(op.intent==='upload') {
      const file=form.elements.file.files[0];
      if(!file||!['application/pdf','image/jpeg','image/png'].includes(file.type)||file.size>10*1024*1024||file.size===0)throw new Error('請選擇 PDF、JPEG 或 PNG，單檔上限 10 MB。');
      let intent=pending(op.c).find(p=>p.documentId===op.id);
      if(intent){$('#uploadStatus').textContent='正在確認是否已保存…';const receipt=await A.api(`${base(op.c)}/attachment-receipts/${intent.id}`);if(receipt.committed){forget(op.c,intent.id);await completed(form);return;}}
      else {intent={id:crypto.randomUUID(),documentId:op.id,documentRevision:op.revision};storePending(op.c,[...pending(op.c),intent]);}
      const encoded=btoa(String.fromCharCode(...new TextEncoder().encode(file.name)));
      $('#uploadStatus').textContent='正在上傳並確認儲存…';
      try {await A.api(`${base(op.c)}/${op.endpoint}?request_id=${intent.id}&expected_revision=${intent.documentRevision??op.revision}`,{method:'POST',headers:{'content-type':file.type,'x-file-name':encoded},body:file});}
      catch(err){if(err.status>=400&&err.status<500&&![401,429].includes(err.status))forget(op.c,intent.id);else if($('#uploadStatus'))$('#uploadStatus').textContent='尚無法確認是否已保存。重新登入或稍後重試時，會先查詢這次上傳。';throw err;}
      forget(op.c,intent.id);
    } else {
      const v=Object.fromEntries(new FormData(form)),data=op.payload(v),signature=JSON.stringify(data);
      if(op.retry?.signature!==signature)op.retry={signature,id:crypto.randomUUID()};
      try {await A.api(`${base(op.c)}/${op.endpoint}`,{method:op.method,body:JSON.stringify({...data,request_id:op.retry.id})});}
      catch(err){if(err.status>=400&&err.status<500)op.retry=null;throw err;}
    }
    await completed(form);
  }
  async function completed(form){
    const op=form.travelOperation;A.markFormCommitted(form,'files-open',{caseId:op.c});form.dataset.dirty='false';
    // Clear private values immediately even if loading the saved record fails.
    if(form.hasAttribute('data-private'))form.querySelectorAll('input').forEach(input=>{input.value='';});
    A.showToast('已保存；請核對目前名冊與文件。');
    if(form.isConnected&&A.sheetRequestCurrent(op.stamp))await open(op.c);
  }
  async function download(el){
    const blob=await A.api(`${base(el.dataset.caseId)}/attachments/${encodeURIComponent(el.dataset.id)}/download`,{responseType:'blob'});
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=`原始文件.${{'application/pdf':'pdf','image/jpeg':'jpg','image/png':'png'}[blob.type]||'bin'}`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  window.TravelFiles=Object.freeze({open});
  A.registerAction('files-open',el=>open(el.dataset.caseId));
  A.registerAction('files-form',form);
  A.registerAction('files-reveal',reveal);
  A.registerAction('files-download',download);
  A.registerForm('travelFileForm',submit);
})();

// Passenger fulfilment is separate from identity verification and original files.
(() => {
  const A=window.MomApp,H=window.Assistance,E=A.escapeHtml;
  const labels={seat:'座位',meal:'餐食',wheelchair:'輪椅',baggage:'行李',other:'其他需求'};
  const states={not_requested:'未提出',requested:'已提出待回覆',confirmed:'供應商已確認',declined:'供應商未能提供'};
  async function open(c,t){
    const ctx=H.context();if(!ctx)return;
    const recovered=await H.recover(c),b=await A.api(`${H.base(c)}/travel-files`);if(!H.current(ctx))return;
    const rows=b.traveller_services.filter(v=>v.traveller_id===t);
    const body=recovered+'<p class="muted">票號與需求分別關聯每位旅客及實際訂購。修改不會撤銷證件名冊核對；行前文件仍需核對最新服務內容。</p>'+(!b.case_closed?H.button('新增票號／需求','files-service-form',c,'',`data-traveller-id="${E(t)}"`):'')+rows.map(v=>`<article class="operation-record"><h3>${v.status==='archived'?'已封存':v.current?'目前有效':'旅客或訂購已變更，需重新核對'}</h3><p class="muted">票號與需求預設隱藏。</p><div class="operation-actions">${H.button('查看完整內容','files-service-reveal',c,v.id,`data-traveller-id="${E(t)}"`)}${!b.case_closed&&v.status==='active'?H.button('修改／重新核對','files-service-form',c,v.id,`data-traveller-id="${E(t)}"`)+H.button('封存此筆服務','files-service-archive',c,v.id,`data-traveller-id="${E(t)}"`):''}</div></article>`).join('');
    if(A.openSheet('逐人票號與特殊需求',body,true,'pretrip',c,ctx.generation))A.setSheetBack(()=>window.TravelFiles.open(c,`[data-action=files-service-open][data-id="${CSS.escape(t)}"]`),'返回名冊與原件');
  }
  async function form(el,archive=false){
    const c=el.dataset.caseId,t=el.dataset.travellerId,id=el.dataset.id,ctx=H.context();if(!ctx)return;
    const b=await A.api(`${H.base(c)}/travel-files`);if(b.case_closed)throw new Error('案件已結案，服務內容僅供查看。');
    const old=id?await A.api(`${H.base(c)}/traveller-services/${encodeURIComponent(id)}/reveal`,{headers:H.headers(ctx.privacy.actor)}):{};
    const traveller=b.travellers.find(v=>v.id===t&&v.status==='active');
    let body='<p class="notice-card">封存保留歷史，行前交付須重新核對。</p>';
    if(!archive){
      if(!traveller)throw new Error('旅客已封存，無法新增或重新核對服務。');
      const bookings=b.bookings.filter(v=>v.status==='confirmed');if(!bookings.length)throw new Error('請先登錄供應商訂購確認。');
      body=H.select('已確認訂購','booking_id',Object.fromEntries(bookings.map(v=>[v.id,v.title])),old.booking_id)+A.field('航段／日期或服務描述','segment_label',old.segment_label||'','required maxlength="160"')+A.field('票號（可留空）','ticket_number',old.ticket_number||'','maxlength="40" autocomplete="off"');
      for(const [k,label] of Object.entries(labels)){
        const request=old.requests?.[k]||{};
        body+=`<fieldset><legend>${E(label)}</legend>`+A.field('需求內容',k,request.value||'','maxlength="500"')+H.select('處理狀態',k+'_status',states,request.status||'not_requested')+A.field('供應商確認依據',k+'_reference',request.supplier_reference||'','maxlength="500"')+'</fieldset>';
      }
      body+=`<label><span>服務備註</span><textarea name="notes" maxlength="2000" rows="3">${E(old.notes||'')}</textarea></label>`;
    }
    H.mount(ctx,c,archive?'封存旅客服務':'逐人票號與需求','travellerServiceForm',body,{scope:c,target:id,action:archive?'traveller-service.archive':'traveller-service.write',endpoint:`${H.base(c)}/traveller-services${id?'/'+encodeURIComponent(id):''}${archive?'/archive':''}`,method:id&&!archive?'PATCH':'POST',revision:old.revision,returnId:t,traveller,bookings:b.bookings,archive,returnAction:'files-service-open'},()=>open(c,t));
  }
  async function reveal(el){
    const c=el.dataset.caseId,id=el.dataset.id,t=el.dataset.travellerId,ctx=H.context();if(!ctx)return;
    const v=await A.api(`${H.base(c)}/traveller-services/${encodeURIComponent(id)}/reveal`,{headers:H.headers(ctx.privacy.actor)});if(!H.current(ctx))return;
    const content=value=>`<p>${E(value.segment_label)}<br>票號：${E(value.ticket_number||'未填')}</p>${Object.entries(labels).map(([k,label])=>`<p><b>${E(label)}</b> · ${E(states[value.requests?.[k]?.status||'not_requested'])}<br>${E(value.requests?.[k]?.value||'')}<br>${E(value.requests?.[k]?.supplier_reference||'')}</p>`).join('')}<p class="preserve-lines">${E(value.notes)}</p>`;
    if(A.openSheet('查看票號與需求',`<div data-private>${content(v)}<details><summary>歷史 · ${v.history.length} 筆</summary>${v.history.map(h=>`<article>${content(h.content)}<p>${E(h.at)} · ${E(h.actor)}</p></article>`).join('')}</details></div>`,true,'pretrip',c,ctx.generation))A.setSheetBack(()=>open(c,t),'返回旅客服務');
  }
  A.registerAction('files-service-open',el=>open(el.dataset.caseId,el.dataset.id));
  A.registerAction('files-service-form',el=>form(el));A.registerAction('files-service-archive',el=>form(el,true));A.registerAction('files-service-reveal',reveal);
  A.registerForm('travellerServiceForm',async form=>{
    const op=form.assistanceOperation;
    if(form.assistanceCommand?.frozen){await H.submit(form,{},op);await H.saved(form,'已核對上次保存結果。');return;}
    const v=Object.fromEntries(new FormData(form));let data=H.evidence(v);
    if(op.archive)data={...data,expected_revision:op.revision};
    else{
      const booking=op.bookings.find(b=>b.id===v.booking_id);
      data={...data,traveller_id:op.traveller.id,traveller_revision:op.traveller.revision,booking_id:booking.id,booking_revision:booking.revision,segment_label:v.segment_label,ticket_number:v.ticket_number,notes:v.notes,requests:Object.fromEntries(Object.keys(labels).map(k=>[k,{value:v[k],status:v[k+'_status'],supplier_reference:v[k+'_reference']}])),...(op.target?{expected_revision:op.revision}:{})};
    }
    await H.submit(form,data,op);await H.saved(form,'逐人服務已保存，請核對行前交付。');
  });
})();
