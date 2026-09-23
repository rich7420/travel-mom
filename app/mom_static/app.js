'use strict';

const state = {
  token: sessionStorage.getItem('travelDeskToken') || '',
  preferences: null,
  airlines: [],
  hotelNetworks: [],
  cases: [],
  home: null,
  wizardSession: localStorage.getItem('momGuidedSession') || `mom-${crypto.randomUUID()}`,
  currentDraft: null,
  activePollers: new Map(),
};
localStorage.setItem('momGuidedSession', state.wizardSession);

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const sheet = $('#sheet');
const sheetTitle = $('#sheetTitle');
const sheetBody = $('#sheetBody');
const toast = $('#toast');

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove('show'), 2600);
}

function friendlyError(err) {
  const raw = String(err?.message || err || '發生未知錯誤');
  const lower = raw.toLowerCase();
  if (lower.includes('captcha')) return '網站需要確認您是真人。我已經停下來，不會嘗試繞過驗證。';
  if (lower.includes('3ds') || lower.includes('otp')) return '網站需要一次性驗證。請由您本人完成後再繼續。';
  if (lower.includes('login') || lower.includes('登入')) return '這個步驟需要登入。我不會替您輸入密碼，可以先看一般價格。';
  if (lower.includes('openclaw') && lower.includes('disabled')) return '目前尚未連上 OpenClaw。查詢已經存好，可以之後再開始。';
  if (lower.includes('allow') || lower.includes('trusted') || lower.includes('信任')) return '這個網站尚未確認為官方網站，為了安全我先停止。';
  if (lower.includes('timeout') || lower.includes('browser') || lower.includes('502')) return '網站今天比較慢，這次沒有查完，但案件資料都還在。';
  if (lower.includes('operator authentication')) return '需要連線密碼才能讀取案件。';
  return raw.length > 180 ? '這次沒有完成，我已經保留進度。請稍後重試或請管理員查看。' : raw;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('content-type')) headers.set('content-type', 'application/json');
  if (state.token) headers.set('x-travel-desk-admin-token', state.token);
  const response = await fetch(path, {...options, headers});
  if (response.status === 401) {
    $('#tokenDialog').showModal();
    throw new Error('operator authentication required');
  }
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!response.ok) {
    const detail = body?.detail || body?.message || body || `${response.status}`;
    throw new Error(detail);
  }
  return body;
}

function openSheet(title, html) {
  sheetTitle.textContent = title;
  sheetBody.innerHTML = html;
  if (!sheet.open) sheet.showModal();
}

function closeSheet() { if (sheet.open) sheet.close(); }

function setView(name) {
  $$('.view').forEach((el) => el.classList.toggle('is-active', el.dataset.view === name));
  $$('.nav-item').forEach((el) => el.classList.toggle('is-active', el.dataset.nav === name));
  if (name === 'today') loadHome();
  if (name === 'cases') loadCases();
  if (name === 'new') resumeGuided();
  if (name === 'settings') renderSettings();
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function applyFontScale(scale) {
  document.documentElement.dataset.font = scale || 'large';
}

async function boot() {
  try {
    const health = await api('/health');
    const badge = $('#connectionBadge');
    badge.textContent = health.openclaw_enabled ? 'AI 已連線' : '本機模式';
    badge.className = `status-badge ${health.openclaw_enabled ? 'status-ok' : 'status-warn'}`;
  } catch {
    $('#connectionBadge').textContent = '離線';
  }
  try {
    const [prefs, airlines, hotels] = await Promise.all([
      api('/api/mom/preferences'), api('/api/airlines'), api('/api/hotels/networks')
    ]);
    state.preferences = prefs;
    state.airlines = airlines.airlines || [];
    state.hotelNetworks = hotels.networks || [];
    applyFontScale(prefs.font_scale);
    if (!prefs.onboarding_complete) showOnboarding();
    await Promise.all([loadHome(), loadCases()]);
  } catch (err) {
    if (!String(err.message).includes('operator authentication')) showToast(friendlyError(err));
  }
}

function showOnboarding() {
  $('#onboardingOrigin').value = state.preferences?.default_origin || 'TPE';
  const scale = state.preferences?.font_scale || 'large';
  const radio = document.querySelector(`input[name="onboardingFont"][value="${scale}"]`);
  if (radio) radio.checked = true;
  if (!$('#onboardingDialog').open) $('#onboardingDialog').showModal();
}

async function saveOnboarding(event) {
  event.preventDefault();
  const scale = document.querySelector('input[name="onboardingFont"]:checked')?.value || 'large';
  const payload = {default_origin: $('#onboardingOrigin').value, font_scale: scale, onboarding_complete: true};
  try {
    state.preferences = await api('/api/mom/preferences', {method: 'PATCH', body: JSON.stringify(payload)});
    applyFontScale(scale);
    $('#onboardingDialog').close();
    showToast('設定好了，之後會幫您記住。');
    await loadHome();
  } catch (err) { showToast(friendlyError(err)); }
}

function actionButton(action) {
  const kind = action?.kind || 'case';
  const map = {
    flight_search: '查機票', flight_run: '看機票方案', hotel_search: '查飯店', hotel_run: '看飯店方案',
    customer_reply: '整理回覆', pretrip: '準備行前資料', case: action?.label || '打開案件'
  };
  return `<button class="primary-button" type="button" data-action="next-action" data-kind="${escapeHtml(kind)}" data-case-id="${escapeHtml(action?.case_id || '')}" data-run-id="${escapeHtml(action?.run_id || '')}">${escapeHtml(map[kind] || action?.label || '繼續處理')}</button>`;
}

function renderCaseCard(item, priority = false) {
  const days = item.days_until_departure;
  const when = days === null || days === undefined ? item.date_label : days < 0 ? '已過出發日' : days === 0 ? '今天出發' : `${days} 天後出發`;
  return `<article class="${priority ? 'work-card' : 'case-card'}">
    <div class="card-top"><div><div class="card-title">${escapeHtml(item.customer_name)} · ${escapeHtml(item.destination)}</div><div class="card-sub">${escapeHtml(when)} · ${escapeHtml(item.status)}</div></div></div>
    <div class="next-action"><b>下一步：</b>${escapeHtml(item.next_action?.label || '查看案件')}<br><span class="muted">${escapeHtml(item.next_action?.reason || '')}</span></div>
    ${actionButton(item.next_action || {kind:'case',case_id:item.id})}
  </article>`;
}

function renderProgressCard(progress) {
  const title = progress.kind === 'flight' ? '✈️ 機票官網查價' : '🏨 飯店官網查價';
  const pct = progress.total ? Math.round(progress.completed / progress.total * 100) : 0;
  const pClass = `p${Math.min(100, Math.max(0, Math.round(pct / 10) * 10))}`;
  const rows = (progress.tasks || []).slice(0, 6).map(t => `<div class="provider-row"><span>${escapeHtml(t.provider_code || (progress.kind === 'hotel' ? '飯店官網' : '官方網站'))}</span><span class="progress-chip ${t.needs_attention ? 'attention' : ''}">${escapeHtml(t.label)}</span></div>`).join('');
  return `<article class="search-card"><div class="card-top"><div><div class="card-title">${title}</div><div class="card-sub">${progress.completed}/${progress.total} 完成${progress.attention ? ` · ${progress.attention} 件需要確認` : ''}</div></div><span class="progress-chip">可先離開</span></div><div class="progress-track"><div class="progress-fill ${pClass}"></div></div>${rows}<button class="secondary-button" type="button" data-action="refresh-progress" data-kind="${escapeHtml(progress.kind)}" data-run-id="${escapeHtml(progress.run_id)}">更新進度</button></article>`;
}

async function loadHome() {
  try {
    state.home = await api('/api/mom/home');
    const priority = state.home.priority || [];
    $('#todaySummary').textContent = priority.length ? `今天先處理 ${priority.length} 件比較重要的工作。` : '目前沒有急件，可以從新客人或回覆客人開始。';
    const p = $('#primaryTodayAction');
    if (priority[0]?.next_action) {
      p.textContent = `先處理：${priority[0].next_action.label}`;
      p.dataset.action = 'next-action'; p.dataset.kind = priority[0].next_action.kind; p.dataset.caseId = priority[0].id; p.dataset.runId = priority[0].next_action.run_id || '';
    } else { p.textContent = '＋ 新客人'; p.dataset.action = 'new-case'; p.dataset.kind=''; p.dataset.caseId=''; }
    $('#priorityList').innerHTML = priority.length ? priority.map(i => renderCaseCard(i, true)).join('') : '<div class="empty-state">今天沒有急件。需要時可以直接建立新客人。</div>';
    $('#recentCases').innerHTML = (state.home.recent_cases || []).length ? state.home.recent_cases.map(i => renderCaseCard(i)).join('') : '<div class="empty-state">還沒有案件。</div>';
    const searches = [...(state.home.searches?.flight || []), ...(state.home.searches?.hotel || [])];
    $('#searchProgressList').innerHTML = searches.length ? searches.map(renderProgressCard).join('') : '<p class="muted">目前沒有背景查價。</p>';
  } catch (err) { $('#priorityList').innerHTML = `<div class="notice-card warn">${escapeHtml(friendlyError(err))}</div>`; }
}

async function loadCases() {
  try {
    state.cases = await api('/api/cases');
    renderCases();
  } catch (err) { $('#caseList').innerHTML = `<div class="notice-card warn">${escapeHtml(friendlyError(err))}</div>`; }
}

function renderCases() {
  const q = ($('#caseSearchInput')?.value || '').trim().toLowerCase();
  const rows = state.cases.filter(c => !q || `${c.customer_name} ${c.destination || ''}`.toLowerCase().includes(q));
  $('#caseList').innerHTML = rows.length ? rows.map(c => `<article class="case-card"><div class="card-title">${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination || '目的地未定')}</div><div class="card-sub">${escapeHtml(c.depart_date || '日期未定')} ${c.return_date ? `→ ${escapeHtml(c.return_date)}` : ''}</div><button class="secondary-button" type="button" data-action="open-case" data-case-id="${escapeHtml(c.id)}">繼續處理</button></article>`).join('') : '<div class="empty-state">找不到符合的案件。</div>';
}

async function openCase(caseId) {
  try {
    const data = await api(`/api/mom/cases/${encodeURIComponent(caseId)}`);
    const c = data.case, a = data.next_action;
    openSheet(`${c.customer_name} · ${c.destination || '旅行案件'}`, `<div class="notice-card"><b>下一步：${escapeHtml(a.label)}</b><br><span class="muted">${escapeHtml(a.reason)}</span></div><div class="form-grid"><div><b>日期</b><p>${escapeHtml(c.depart_date || '未定')} ${c.return_date ? `→ ${escapeHtml(c.return_date)}` : ''}</p></div><div><b>旅客</b><p>${c.adults} 大人${c.children ? `、${c.children} 小孩` : ''}</p></div><div><b>預算</b><p>${c.budget_twd ? `NT$ ${Number(c.budget_twd).toLocaleString()}` : '尚未設定'}</p></div></div>${actionButton(a)}<button class="secondary-button full" type="button" data-action="customer-reply" data-case-id="${escapeHtml(c.id)}">💬 回覆這位客人</button>`);
  } catch (err) { showToast(friendlyError(err)); }
}

async function startGuided(reset = false) {
  setView('new');
  try {
    const reply = await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/start?reset=${reset ? 'true' : 'false'}`, {method:'POST'});
    renderGuided(reply);
  } catch (err) { showToast(friendlyError(err)); }
}
async function resumeGuided() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/resume`)); } catch (err) { showToast(friendlyError(err)); } }
async function sendGuided(textOverride) {
  const input = $('#wizardInput'); const text = textOverride ?? input.value;
  if (!String(text).trim()) return showToast('先回答這一題就好。');
  try { const r = await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/reply`, {method:'POST', body:JSON.stringify({text})}); input.value=''; renderGuided(r); if (r.done) { await Promise.all([loadHome(),loadCases()]); } } catch (err) { showToast(friendlyError(err)); }
}
async function guidedBack() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/back`, {method:'POST'})); } catch (err) { showToast(friendlyError(err)); } }
async function guidedSave() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/save`, {method:'POST'})); showToast('已經幫您存好了。'); } catch (err) { showToast(friendlyError(err)); } }
async function guidedReset() { if (!confirm('要重新開始這個尚未完成的引導嗎？')) return; try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/reset`, {method:'POST'})); } catch (err) { showToast(friendlyError(err)); } }

function renderGuided(reply) {
  $('#wizardQuestion').textContent = reply.text;
  const current = reply.progress_current || 0, total = reply.progress_total || 6;
  $('#wizardProgressLabel').textContent = reply.done ? '完成' : `第 ${Math.max(1,current)} 題，共 ${total} 題`;
  const pct = reply.done ? 100 : Math.round((current-1) / total * 100);
  $('#wizardProgressBar').className = `progress-fill p${Math.min(100, Math.max(0, Math.round(pct/10)*10))}`;
  $('#wizardOptions').innerHTML = (reply.options || []).map(o => `<button class="choice-button" type="button" data-guided-option="${escapeHtml(o)}">${escapeHtml(o)}</button>`).join('');
  $('#wizardBack').disabled = !reply.can_back;
  if (reply.done && reply.case_id) {
    $('#wizardOptions').insertAdjacentHTML('beforeend', `<button class="primary-button full" type="button" data-action="open-case" data-case-id="${escapeHtml(reply.case_id)}">打開案件</button>`);
  }
}

function selectedCaseOptions(selected='') {
  return `<option value="">不綁定案件</option>${state.cases.map(c => `<option value="${escapeHtml(c.id)}" ${selected===c.id?'selected':''}>${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination||'未定')}</option>`).join('')}`;
}

function openFlightSearch(caseId='') {
  const prefs = state.preferences || {default_origin:'TPE',preferred_airlines:['CI','JX','CX','AE','BR']};
  const airlineChecks = state.airlines.map(a => `<label class="checkbox-pill"><input type="checkbox" name="airline" value="${escapeHtml(a.code)}" ${prefs.preferred_airlines.includes(a.code)?'checked':''}>${escapeHtml(a.name_zh || a.name || a.code)}</label>`).join('');
  openSheet('查官方航空網站', `<form id="flightForm" class="form-grid"><label><span>案件（可不選）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label><div class="form-grid two"><label><span>出發機場</span><input name="origin" maxlength="3" value="${escapeHtml(prefs.default_origin)}" required></label><label><span>目的地機場</span><input name="destination" maxlength="3" placeholder="NRT" required></label></div><label><span>出發日期</span><input name="depart_date" type="date" required></label><label><span>回程日期（單程可留白）</span><input name="return_date" type="date"></label><div class="form-grid two"><label><span>成人</span><input name="adults" type="number" min="1" max="20" value="2"></label><label><span>小孩</span><input name="children" type="number" min="0" max="20" value="0"></label></div><fieldset><legend class="fieldset-title">要查哪些航空公司？</legend><div class="checkbox-grid">${airlineChecks}</div></fieldset><label class="checkbox-pill"><input name="nonstop" type="checkbox">直飛優先</label><label><span>最重要的偏好</span><textarea name="notes" rows="3" placeholder="例如：含托運行李、不要太早、時間漂亮"></textarea></label><div class="notice-card">只會搜尋與比較官方網站。付款、OTP、3DS、最終開票一定停下來給您本人處理。</div><button class="primary-button full" type="submit">開始查官方網站</button></form>`);
}

async function submitFlightSearch(form) {
  const fd = new FormData(form); const airlines = [...form.querySelectorAll('input[name="airline"]:checked')].map(x=>x.value);
  if (!airlines.length) return showToast('至少選一家航空公司。');
  const returnDate = fd.get('return_date') || null;
  const payload = {case_id:fd.get('case_id')||null, origin:String(fd.get('origin')).toUpperCase(), destination:String(fd.get('destination')).toUpperCase(), depart_date:fd.get('depart_date'), return_date:returnDate, trip_type:returnDate?'round_trip':'one_way', adults:Number(fd.get('adults')||1), children:Number(fd.get('children')||0), infants:0, airline_codes:airlines, nonstop_preferred:fd.get('nonstop')==='on', notes:String(fd.get('notes')||'')};
  try {
    const plan=await api('/api/browser/flight-search',{method:'POST',body:JSON.stringify(payload)}); const runId=plan.run.id;
    const start=await api(`/api/mom/flight-search/${encodeURIComponent(runId)}/start`,{method:'POST'});
    closeSheet(); showToast(start.message || '查詢已建立。'); await loadHome(); openSearchProgress('flight',runId);
  } catch(err){ showToast(friendlyError(err)); }
}

function openHotelSearch(caseId='') {
  const networks = state.hotelNetworks.map(n=>`<option value="${escapeHtml(n.code)}" data-home="${escapeHtml(n.official_home)}">${escapeHtml(n.name)}</option>`).join('');
  openSheet('查飯店官網', `<form id="hotelForm" class="form-grid"><label><span>案件（可不選）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label><label><span>飯店集團</span><select id="hotelNetworkSelect" name="network"><option value="">自己輸入官方網址</option>${networks}</select></label><label><span>飯店名稱</span><input name="hotel_name" placeholder="例如 Hilton Tokyo" required></label><label><span>官方網站</span><input id="hotelOfficialUrl" name="official_url" type="url" placeholder="https://www.hilton.com/…" required></label><div class="form-grid two"><label><span>入住</span><input name="checkin_date" type="date" required></label><label><span>退房</span><input name="checkout_date" type="date" required></label></div><div class="form-grid two"><label><span>房間</span><input name="rooms" type="number" min="1" max="8" value="1"></label><label><span>成人</span><input name="adults" type="number" min="1" max="24" value="2"></label></div><label class="checkbox-pill"><input name="breakfast" type="checkbox">需要早餐</label><label class="checkbox-pill"><input name="free_cancel" type="checkbox" checked>優先可免費取消</label><label><span>偏好</span><textarea name="notes" rows="3" placeholder="例如：近車站、安靜、兩張床"></textarea></label><div class="notice-card">第一次使用獨立飯店官網時，系統會先要求管理員確認這是真正官方網站，不會把 OTA 當官網。</div><button class="primary-button full" type="submit">開始查飯店官網</button></form>`);
}

async function submitHotelSearch(form) {
  const fd=new FormData(form); const payload={case_id:fd.get('case_id')||null,hotel_name:fd.get('hotel_name'),official_url:fd.get('official_url'),checkin_date:fd.get('checkin_date'),checkout_date:fd.get('checkout_date'),rooms:Number(fd.get('rooms')||1),adults:Number(fd.get('adults')||2),children_ages:[],currency_preference:'TWD',breakfast_required:fd.get('breakfast')==='on',free_cancellation_preferred:fd.get('free_cancel')==='on',notes:String(fd.get('notes')||'')};
  try{const plan=await api('/api/browser/hotel-search',{method:'POST',body:JSON.stringify(payload)});const runId=plan.run.id;const start=await api(`/api/mom/hotel-search/${encodeURIComponent(runId)}/start`,{method:'POST'});closeSheet();showToast(start.message||'查詢已建立。');await loadHome();openSearchProgress('hotel',runId);}catch(err){showToast(friendlyError(err));}
}

async function openSearchProgress(kind,runId){try{const p=await api(`/api/mom/search-progress/${kind}/${encodeURIComponent(runId)}`);openSheet(kind==='flight'?'機票查價進度':'飯店查價進度',renderProgressCard(p)+`<p class="muted">這個畫面可以關掉，查詢進度會留著。</p>`);if(['running','planned'].includes(p.status)) startPolling(kind,runId);}catch(err){showToast(friendlyError(err));}}
function startPolling(kind,runId){const key=`${kind}:${runId}`;if(state.activePollers.has(key))return;const id=setInterval(async()=>{try{const p=await api(`/api/mom/search-progress/${kind}/${encodeURIComponent(runId)}`);if(sheet.open && sheetBody.querySelector(`[data-run-id="${CSS.escape(runId)}"]`)) sheetBody.innerHTML=renderProgressCard(p)+`<p class="muted">這個畫面可以關掉，查詢進度會留著。</p>`;if(!['running','planned'].includes(p.status)){clearInterval(id);state.activePollers.delete(key);loadHome();}}catch{clearInterval(id);state.activePollers.delete(key);}},3500);state.activePollers.set(key,id);}

function openCustomerReply(caseId='') {
  openSheet('幫您整理客戶回覆', `<form id="replyForm" class="form-grid"><label><span>案件（可不選）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label><label><span>客人說什麼？</span><textarea name="incoming_text" rows="6" placeholder="直接貼客人的 LINE 訊息就好…" required></textarea></label><label><span>語氣</span><select name="tone"><option>專業、親切、簡潔</option><option>比較口語、自然</option><option>正式、穩重</option></select></label><button class="primary-button full" type="submit">先幫我寫草稿</button><p class="muted">只會產生草稿，不會直接傳給客人。</p></form>`);
}

async function submitCustomerReply(form){const fd=new FormData(form);try{const result=await api('/api/customer-reply',{method:'POST',body:JSON.stringify({case_id:fd.get('case_id')||null,incoming_text:fd.get('incoming_text'),tone:fd.get('tone')})});state.currentDraft={case_id:fd.get('case_id')||null,text:result.text};sheetBody.innerHTML=`<div class="notice-card ${result.degraded?'warn':'ok'}">${result.degraded?'目前 AI 回覆使用降級模式，送出前請特別確認。':'這是草稿，請您確認後再貼給客人。'}</div><div class="draft-box" id="replyDraft">${escapeHtml(result.text)}</div><button class="primary-button full" type="button" data-action="copy-draft">複製草稿</button><div class="feedback-row"><button type="button" data-feedback="accepted">👍 可以直接用</button><button type="button" data-feedback="edited">✏️ 我有修改</button><button type="button" data-feedback="prefer_future">🧠 以後都這樣</button><button type="button" data-feedback="rejected">👎 不要這樣</button></div><p class="muted">這些回饋會先去識別化、累積成 Skill 改進證據；v0.8.1 不會自動改掉正式 Skill。</p>`;}catch(err){showToast(friendlyError(err));}}

async function submitFeedback(type){
  if(!state.currentDraft)return;
  if(type==='accepted'){
    try{await api('/api/mom/skill-feedback',{method:'POST',body:JSON.stringify({skill_key:'customer-reply',feedback_type:type,case_id:state.currentDraft.case_id,draft_text:state.currentDraft.text})});showToast('收到，這次草稿可以直接使用。');}catch(err){showToast(friendlyError(err));}
    return;
  }
  const title=type==='edited'?'把最後修改的版本貼給我':type==='prefer_future'?'希望以後保留哪個做法？':'哪一點不要再這樣？';
  const help=type==='edited'?'只要貼您最後真的會傳給客人的版本。':'簡單說一句就好，不需要寫成規則。';
  sheetBody.insertAdjacentHTML('beforeend',`<form id="feedbackDetailForm" class="form-grid notice-card" data-feedback-type="${escapeHtml(type)}"><label><span>${escapeHtml(title)}</span><textarea name="detail" rows="4" placeholder="${escapeHtml(help)}" required></textarea></label><button class="primary-button full" type="submit">送出這次回饋</button></form>`);
  $('#feedbackDetailForm textarea')?.focus();
}

async function submitFeedbackDetail(form){
  const type=form.dataset.feedbackType; const detail=new FormData(form).get('detail');
  const payload={skill_key:'customer-reply',feedback_type:type,case_id:state.currentDraft?.case_id||null,draft_text:state.currentDraft?.text||null};
  if(type==='edited') payload.final_text=detail; else payload.note=detail;
  try{await api('/api/mom/skill-feedback',{method:'POST',body:JSON.stringify(payload)});form.remove();showToast('收到，我會把這次經驗留給後續 Skill 改進。');}catch(err){showToast(friendlyError(err));}
}

async function inferIntent(){const text=$('#intentInput').value.trim();if(!text)return showToast('直接說現在發生什麼事就好。');try{const r=await api('/api/mom/intent',{method:'POST',body:JSON.stringify({text})});$('#intentResults').innerHTML=`<div class="notice-card">${escapeHtml(r.text)}</div>`+(r.suggestions||[]).map(s=>`<button class="quick-card" type="button" data-intent-action="${escapeHtml(s.action)}"><span><b>${escapeHtml(s.label)}</b><small>${escapeHtml(s.reason)}</small></span></button>`).join('');}catch(err){showToast(friendlyError(err));}}

function runIntentAction(action){const map={customer_reply:()=>openCustomerReply(),flight_search:()=>openFlightSearch(),hotel_search:()=>openHotelSearch(),new_case:()=>startGuided(false),case_lookup:()=>setView('cases'),itinerary:()=>showToast('行程規劃會綁定案件處理，先選一個案件。'),visa:()=>showToast('簽證與入境資訊會要求權威來源，請先選案件。')};(map[action]||(()=>showToast('先從新客人或案件開始就好。')))();}

async function renderSettings(){if(!state.preferences)return;$('#defaultOrigin').value=state.preferences.default_origin;$('#preferredAirlines').innerHTML=state.airlines.map(a=>`<label class="checkbox-pill"><input type="checkbox" value="${escapeHtml(a.code)}" ${state.preferences.preferred_airlines.includes(a.code)?'checked':''}>${escapeHtml(a.name_zh||a.code)}</label>`).join('');const radio=document.querySelector(`input[name="fontScale"][value="${state.preferences.font_scale}"]`);if(radio)radio.checked=true;}
async function saveSettings(event){event.preventDefault();const preferred=[...$('#preferredAirlines').querySelectorAll('input:checked')].map(x=>x.value);const scale=document.querySelector('input[name="fontScale"]:checked')?.value||'large';try{state.preferences=await api('/api/mom/preferences',{method:'PATCH',body:JSON.stringify({default_origin:$('#defaultOrigin').value,preferred_airlines:preferred,font_scale:scale})});applyFontScale(scale);showToast('設定已儲存。');}catch(err){showToast(friendlyError(err));}}

async function handleNextAction(el){const kind=el.dataset.kind,caseId=el.dataset.caseId,runId=el.dataset.runId;if(kind==='flight_search')return openFlightSearch(caseId);if(kind==='hotel_search')return openHotelSearch(caseId);if(kind==='flight_run'&&runId)return openSearchProgress('flight',runId);if(kind==='hotel_run'&&runId)return openSearchProgress('hotel',runId);if(kind==='customer_reply')return openCustomerReply(caseId);return openCase(caseId);}

function actionFromDataset(el){const action=el.dataset.action;if(action==='open-settings')return setView('settings');if(action==='refresh-home')return loadHome();if(action==='new-case')return startGuided(false);if(action==='customer-reply')return openCustomerReply(el.dataset.caseId||'');if(action==='flight-search')return openFlightSearch(el.dataset.caseId||'');if(action==='hotel-search')return openHotelSearch(el.dataset.caseId||'');if(action==='open-case')return openCase(el.dataset.caseId);if(action==='next-action')return handleNextAction(el);if(action==='guided-send')return sendGuided();if(action==='guided-back')return guidedBack();if(action==='guided-save')return guidedSave();if(action==='guided-reset')return guidedReset();if(action==='infer-intent')return inferIntent();if(action==='close-sheet')return closeSheet();if(action==='refresh-progress')return openSearchProgress(el.dataset.kind,el.dataset.runId);if(action==='copy-draft'){navigator.clipboard?.writeText(state.currentDraft?.text||'');return showToast('已複製，可以貼給客人。');}if(action==='open-token'){ $('#tokenInput').value=state.token;return $('#tokenDialog').showModal();}if(action==='clear-token'){state.token='';sessionStorage.removeItem('travelDeskToken');$('#tokenInput').value='';return showToast('連線密碼已清除。');}}

document.addEventListener('click',(event)=>{const nav=event.target.closest('[data-nav]');if(nav)return setView(nav.dataset.nav);const guided=event.target.closest('[data-guided-option]');if(guided)return sendGuided(guided.dataset.guidedOption);const intent=event.target.closest('[data-intent-action]');if(intent)return runIntentAction(intent.dataset.intentAction);const feedback=event.target.closest('[data-feedback]');if(feedback)return submitFeedback(feedback.dataset.feedback);const action=event.target.closest('[data-action]');if(action)return actionFromDataset(action);});

document.addEventListener('submit',(event)=>{const form=event.target;if(form.id==='flightForm'){event.preventDefault();submitFlightSearch(form);}else if(form.id==='hotelForm'){event.preventDefault();submitHotelSearch(form);}else if(form.id==='replyForm'){event.preventDefault();submitCustomerReply(form);}else if(form.id==='feedbackDetailForm'){event.preventDefault();submitFeedbackDetail(form);}});
document.addEventListener('change',(event)=>{if(event.target.id==='hotelNetworkSelect'){const option=event.target.selectedOptions[0];$('#hotelOfficialUrl').value=option?.dataset.home||'';}});
$('#caseSearchInput').addEventListener('input',renderCases);
$('#settingsForm').addEventListener('submit',saveSettings);
$('#onboardingForm').addEventListener('submit',saveOnboarding);
$('#tokenForm').addEventListener('submit',(event)=>{event.preventDefault();state.token=$('#tokenInput').value.trim();if(state.token)sessionStorage.setItem('travelDeskToken',state.token);else sessionStorage.removeItem('travelDeskToken');$('#tokenDialog').close();showToast('已套用連線密碼。');boot();});
$('#wizardInput').addEventListener('keydown',(event)=>{if(event.key==='Enter'){event.preventDefault();sendGuided();}});

boot();
