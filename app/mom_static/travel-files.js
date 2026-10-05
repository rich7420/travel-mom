'use strict';
// Full private fields exist only after explicit reveal; uploads keep non-sensitive retry receipts.
(() => {
  let privacyEpoch=0;
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
  function scrub(){
    $('#sheetBody')?.querySelectorAll('[data-private]').forEach(node=>{node.querySelectorAll('input,textarea').forEach(input=>{input.value='';});node.replaceChildren();node.dataset.dirty='false';if(node.travelOperation)node.travelOperation.retry=null;});
  }
  window.addEventListener('travel-auth-expired',()=>{++privacyEpoch;scrub();});
  $('#sheet').addEventListener('close',()=>{if(!$('#sheet').open)scrub();});
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
    const travellerRows=b.travellers.map((t,i)=>`<article class="operation-record"><h3>旅客 ${i+1} · ${E(categories[t.category])}${t.status==='archived'?' · 已封存':''}</h3><p class="muted">姓名、生日與護照資料預設隱藏。</p><div class="operation-actions">${button('查看完整資料','files-reveal',c,`data-id="${E(t.id)}"`)}${!b.case_closed&&t.status==='active'?button('修改旅客','files-form',c,`data-intent="traveller" data-id="${E(t.id)}"`)+button('封存移出名冊','files-form',c,`data-intent="traveller-archive" data-id="${E(t.id)}"`):''}</div></article>`).join('');
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
    const epoch=privacyEpoch,c=el.dataset.caseId,id=el.dataset.id,generation=A.beginSheetRequest();if(generation===null)return;
    const value=await A.api(`${base(c)}/travellers/${encodeURIComponent(id)}/reveal`);
    if(!A.sheetRequestCurrent(generation)||epoch!==privacyEpoch)return;
    const labels={name:'證件姓名',date_of_birth:'生日',passport_number:'護照號碼',passport_expiry:'護照效期',nationality:'國籍'};
    if(!A.openSheet('查看旅客資料',`<div data-private>${Object.entries(labels).map(([k,label])=>`<p><b>${E(label)}</b><br>${E(value[k])}</p>`).join('')}${button('隱藏並返回名冊','files-open',c)}</div>`,true,'pretrip',c,generation))return;
    A.setSheetBack(()=>open(c,`[data-action="files-reveal"][data-id="${CSS.escape(id)}"]`),'返回名冊');
  }
  async function form(el){
    const epoch=privacyEpoch,c=el.dataset.caseId,id=el.dataset.id||'',intent=el.dataset.intent;
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
    if(!A.sheetRequestCurrent(generation)||epoch!==privacyEpoch)return;
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
  A.registerAction('files-open',el=>open(el.dataset.caseId));
  A.registerAction('files-form',form);
  A.registerAction('files-reveal',reveal);
  A.registerAction('files-download',download);
  A.registerForm('travelFileForm',submit);
})();
