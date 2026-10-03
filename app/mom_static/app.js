'use strict';

const state = {
  token: '',
  auth: null,
  preferences: null,
  airlines: [],
  hotelNetworks: [],
  cases: [],
  home: null,
  wizardSession: localStorage.getItem('momGuidedSession') || `mom-${crypto.randomUUID()}`,
  currentDraft: null,
  openclawEnabled: false,
  guidedBusy: false,
  activePollers: new Map(),
};
localStorage.setItem('momGuidedSession', state.wizardSession);

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const sheet = $('#sheet');
const sheetTitle = $('#sheetTitle');
const sheetBody = $('#sheetBody');
const toast = $('#toast');
let sheetGeneration = 0;
let renderedSheetGeneration = 0;
let sheetBack = null;
const extraActions = new Map(), extraForms = new Map(), extraViews = new Map(), homeLoaders = [];
let editEpoch = 0, authorizedEditEpoch = -1, authorizedGeneration = -1;
let homeGeneration = 0, casesGeneration = 0;
function sheetDirty() {
  return Boolean(sheetBody.querySelector('[data-dirty="true"]:not([data-committed="true"])'));
}
function allowSheetTransition() {
  if (sheetBody.dataset.saving === 'true' || sheetBody.querySelector('form[data-busy="true"]:not([data-committed="true"])')) {
    showToast('正在儲存，請等結果顯示後再離開。'); return false;
  }
  if(authorizedGeneration===sheetGeneration&&authorizedEditEpoch===editEpoch)return true;
  return !sheet.open || !sheetDirty() || confirm('尚未儲存的填寫內容或回覆草稿會捨棄。確定離開？取消可繼續編輯。');
}
function beginSheetRequest() {
  if (!allowSheetTransition()) return null;
  authorizedEditEpoch = editEpoch;
  authorizedGeneration=++sheetGeneration;
  return sheetGeneration;
}
function cancelSheetRequest(token) {if(token===sheetGeneration)authorizedGeneration=-1;}
function sheetRequestCurrent(token) { return token === sheetGeneration; }
function setSheetBack(handler, label='返回案件') { sheetBack=handler; $('#sheetBack').textContent=label; $('#sheetBack').classList.toggle('hidden',!handler); }

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
}

const iconPaths = {
  tasks:'<rect x="4" y="4" width="16" height="17" rx="2"/><path d="m8 11 2 2 5-5M8 17h8M9 2v4m6-4v4"/>',
  overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  person:'<circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M19 8v6m-3-3h6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  folder:'<path d="M3 7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/>',
  reply:'<path d="M21 11a8 8 0 0 1-8 8H7l-4 3V11a9 9 0 0 1 18 0ZM7 10h10M7 14h6"/>',
  plane:'<path d="m21 3-6 18-4-8-8-4Z"/><path d="m11 13 10-10"/>',
  hotel:'<path d="M5 21V3h14v18M3 21h18M9 7h1m4 0h1M9 11h1m4 0h1M10 21v-6h4v6"/>',
  settings:'<path d="m9 3-.5 3-2.5 1-2.5-1.5-2 3L4 11v2l-2.5 2.5 2 3L6 17l2.5 1 .5 3h6l.5-3 2.5-1 2.5 1.5 2-3L20 13v-2l2.5-2.5-2-3L18 7l-2.5-1-.5-3Z"/><circle cx="12" cy="12" r="3"/>',
};
function icon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${iconPaths[name] || iconPaths.overview}</svg>`;
}
$$('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon);});

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
  if (lower.includes('login session')) return '請重新登入後繼續，案件資料會保留。';
  if (lower.includes('temporarily unavailable')) return '登入驗證暫時無法使用，請稍後再試。';
  if (lower.includes('account not allowed') || lower.includes('administrator access')) return '此帳號沒有操作權限，請聯絡管理員。';
  if (lower.includes('login') || lower.includes('登入')) return '這個步驟需要登入。我不會替您輸入密碼，可以先看一般價格。';
  if (lower.includes('openclaw') && lower.includes('disabled')) return '目前尚未連上 OpenClaw。查詢已經存好，可以之後再開始。';
  if (lower.includes('allow') || lower.includes('trusted') || lower.includes('信任')) return '這個網站尚未確認為官方網站，為了安全我先停止。';
  if (lower.includes('timeout') || lower.includes('browser') || lower.includes('502')) return '網站今天比較慢，這次沒有查完，但案件資料都還在。';
  if (lower.includes('operator authentication')) return '需要連線密碼才能讀取案件。';
  return raw.length > 180 ? '這次沒有完成，我已經保留進度。請稍後重試或請管理員查看。' : raw;
}

class ReauthenticationError extends Error {
  constructor() { super('login session expired'); this.name = 'ReauthenticationError'; }
}
// Inline async actions without a local catch still show the dedicated login dialog.
window.addEventListener('unhandledrejection', event => {
  if (event.reason instanceof ReauthenticationError) event.preventDefault();
});

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !headers.has('content-type')) headers.set('content-type', 'application/json');
  if (state.token) headers.set('x-travel-desk-admin-token', state.token);
  const response = await fetch(path, {...options, headers, redirect:'manual'});
  if (response.type === 'opaqueredirect' || response.status === 0) {
    showLogin(); throw new ReauthenticationError();
  }
  const text = await response.text();
  let body = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (response.status === 401 && (state.auth?.mode === 'cloudflare' || body?.auth_mode === 'cloudflare')) {
    showLogin(); throw new ReauthenticationError();
  }
  if (response.status === 401) {
    $('#tokenDialog').showModal();
    throw new ReauthenticationError();
  }

  if (!response.ok) {
    const detail = body?.detail || body?.message || body || `${response.status}`;
    const error = new Error(Array.isArray(detail) ? detail.map(item=>item.msg || item).join('；') : detail);
    error.status=response.status; throw error;
  }
  return body;
}

function openSheet(title, html, resetScroll = true, helpSection = 'start', caseId = '', transition = null) {
  if (transition !== null) {
    if (!sheetRequestCurrent(transition)) return false;
    if (editEpoch !== authorizedEditEpoch && !allowSheetTransition()) return false;
  } else if (!allowSheetTransition()) return false;
  ++sheetGeneration;
  renderedSheetGeneration=sheetGeneration;
  authorizedGeneration=-1;
  setSheetBack(caseId && helpSection!=='new-case' ? ()=>openCase(caseId) : null);
  sheetTitle.textContent = title;
  $('#sheetHelp').href = `/static/guide.html#${helpSection}`;
  sheetBody.innerHTML = html;
  sheetBody.querySelectorAll('select[name="case_id"]').forEach(el=>{el.dataset.previous=el.value;});
  if (!sheet.open) sheet.showModal();
  if (resetScroll) { $('.sheet').scrollTop = 0; sheetTitle.tabIndex=-1; sheetTitle.focus({preventScroll:true}); }
  return true;
}

function closeSheet() { if(!allowSheetTransition())return false; ++sheetGeneration; setSheetBack(null); if(sheet.open)sheet.close(); return true; }

function setView(name, initialize = true) {
  $$('.view').forEach((el) => el.classList.toggle('is-active', el.dataset.view === name));
  $$('.nav-item').forEach(el=>{const active=el.dataset.nav===name;el.classList.toggle('is-active',active);if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
  $('#viewTitle').textContent={today:'工作總覽',cases:'旅行案件',new:'接待新客人',assistant:'旅行助理',settings:'偏好設定',tasks:'工作期限'}[name] || '工作總覽';
  if (name === 'today') loadHome();
  if (name === 'cases') loadCases();
  if (name === 'new' && initialize) resumeGuided();
  if (name === 'settings') renderSettings();
  if(extraViews.has(name))extraViews.get(name)();
  window.scrollTo({top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
  const heading=$(`#view-${name} h2`);if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true});}
}

function applyFontScale(scale) {
  document.documentElement.dataset.font = scale || 'large';
}

$('#loginDialog').addEventListener('cancel', event => event.preventDefault());

function showLogin() {
  const dialog = $('#loginDialog');
  if (!dialog.open) dialog.showModal();
}
async function loadSession() {
  state.auth = await api('/api/auth/session');
  const access = state.auth.mode === 'cloudflare';
  state.token = access ? '' : sessionStorage.getItem('travelDeskToken') || '';
  if (access) {sessionStorage.removeItem('travelDeskToken');sessionStorage.removeItem('travelDeskAdminToken');}
  $('#tokenSettingsButton').classList.toggle('hidden', access);
  $('#loginSettings').classList.toggle('hidden', !access);
  $('#loginIdentity').textContent = access ? `已登入：${state.auth.email}` : '';
  $('#headerIdentity').textContent=access?state.auth.email:'';
  $('#headerIdentity').classList.toggle('hidden',!access);
  $('#adminTools').classList.toggle('hidden', access && state.auth.role !== 'admin');
}

async function boot() {
  try { await loadSession(); } catch(err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); return; }
  try {
    const health = await api('/health');
    const badge = $('#connectionBadge');
    state.openclawEnabled = health.openclaw_enabled;
    badge.textContent = health.openclaw_enabled ? '自動查詢已設定' : '網頁工作模式';
    badge.className = `status-badge ${health.openclaw_enabled ? 'status-ok' : 'status-neutral'}`;
  } catch (err) {
    if (err instanceof ReauthenticationError) return;
    $('#connectionBadge').textContent = '離線';
    $('#connectionBadge').className = 'status-badge status-offline';
  }
  await Promise.allSettled([loadComponent('preferences'), loadComponent('airlines'), loadComponent('hotels'), loadHome(), loadCases()]);
}

async function loadComponent(name) {
  const endpoints={preferences:'/api/mom/preferences',airlines:'/api/airlines',hotels:'/api/hotels/networks'};
  const labels={preferences:'偏好設定',airlines:'航空公司清單',hotels:'飯店清單'};
  try {
    const value=await api(endpoints[name]);
    if(name==='preferences') {state.preferences=value;applyFontScale(value.font_scale);if(!value.onboarding_complete)showOnboarding();}
    if(name==='airlines')state.airlines=value.airlines||[];
    if(name==='hotels')state.hotelNetworks=value.networks||[];
    $(`#component-${name}`)?.remove();
  } catch(err) {
    if(err instanceof ReauthenticationError)return;
    $(`#component-${name}`)?.remove();
    $('#bootstrapNotices').insertAdjacentHTML('beforeend',`<div id="component-${name}" class="notice-card warn" role="alert">${labels[name]}暫時無法更新；仍可處理案件與人工錄入。<button class="secondary-button" type="button" data-action="retry-component" data-component="${name}">重試${labels[name]}</button></div>`);
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
  } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}

function actionButton(action) {
  const kind = action?.kind || 'case';
  const map = {
    flight_search: '查機票', flight_run: '看機票方案', hotel_search: '查飯店', hotel_run: '看飯店方案',
    quotes:action?.label,bookings:action?.label,tasks:action?.label,customer_reply: '整理回覆', case_options: '比較與選方案', pretrip:action?.label || '準備行前資料', case: action?.label || '打開案件'
  };
  return `<button class="primary-button" type="button" data-action="next-action" data-kind="${escapeHtml(kind)}" data-case-id="${escapeHtml(action?.case_id || '')}" data-run-id="${escapeHtml(action?.run_id || '')}" data-record-id="${escapeHtml(action?.record_id || '')}">${escapeHtml(map[kind] || action?.label || '繼續處理')}</button>`;
}

function renderCaseCard(item, priority = false, index = 0) {
  const days = item.days_until_departure;
  const when = days === null || days === undefined ? item.date_label : days < 0 ? '已過出發日' : days === 0 ? '今天出發' : `${days} 天後出發`;
  const button = priority ? actionButton(item.next_action || {kind:'case',case_id:item.id}) : `<button class="secondary-button compact" type="button" data-action="open-case" data-case-id="${escapeHtml(item.id)}">查看</button>`;
  return `<article class="${priority ? 'work-card' : 'case-card recent-card'}" ${priority?'role="listitem"':''}><div class="case-row">${priority?`<span class="priority-index" ><span class="sr-only">優先 </span>${String(index+1).padStart(2,'0')}</span>`:''}<div class="case-info"><div class="card-title">${escapeHtml(item.customer_name)}</div><div class="card-sub">${escapeHtml(item.destination)} · ${escapeHtml(when)}</div>${priority?`<div class="next-action">${escapeHtml(item.next_action?.reason || item.status)}</div>`:''}</div><div class="case-action"><span class="case-status">${escapeHtml(item.status)}</span>${button}</div></div></article>`;
}

function renderProgressCard(progress) {
  const title = progress.kind === 'flight' ? '✈️ 機票官網查價' : '🏨 飯店官網查價';
  const runLabels = {planned:'已保存查詢條件',running:'正在查詢',completed:'查詢已結束',partial:'部分完成',needs_review:'需要確認',failed:'查詢未完成'};
  const pct = progress.total ? Math.round(progress.completed / progress.total * 100) : 0;
  const pClass = `p${Math.min(100, Math.max(0, Math.round(pct / 10) * 10))}`;
  const rows = (progress.tasks || []).slice(0, 6).map(t => `<div class="provider-row"><span>${escapeHtml(t.provider_code || (progress.kind === 'hotel' ? '飯店官網' : '官方網站'))}</span><span class="progress-chip ${t.needs_attention ? 'attention' : ''}">${escapeHtml(t.label)}</span></div>`).join('');
  return `<article class="search-card"><div class="card-top"><div><div class="card-title">${title}</div><div class="card-sub">${escapeHtml(runLabels[progress.status] || progress.status)} · ${progress.completed}/${progress.total} 處理結束${progress.attention ? ` · ${progress.attention} 件需要確認` : ''}</div></div></div><div class="progress-track"><div class="progress-fill ${pClass}"></div></div>${rows}${progress.status==='planned'&&!state.openclawEnabled?'<p class="muted">自動查詢尚未啟用。可先到案件錄入人工查到的價格。</p>':''}<button class="secondary-button" type="button" data-action="refresh-progress" data-kind="${escapeHtml(progress.kind)}" data-run-id="${escapeHtml(progress.run_id)}">查看進度與結果</button>${progress.case_id?`<button class="primary-button" type="button" data-action="case-options" data-case-id="${escapeHtml(progress.case_id)}">比較與選方案</button>`:''}</article>`;
}

function renderSearchSummary(progress) {
  const label = progress.kind === 'flight' ? '機票' : '飯店';
  const statuses = {planned:'已保存需求',running:'查詢中',completed:'已完成',partial:'部分完成',needs_review:'待確認',failed:'未完成'};
  return `<div class="search-summary"><span class="search-icon">${icon(progress.kind==='flight'?'plane':'hotel')}</span><div><b>${label}查價</b><p class="card-sub">${escapeHtml(statuses[progress.status] || progress.status)} · ${escapeHtml(displayTime(progress.updated_at))}</p></div><button class="secondary-button compact" type="button" data-action="refresh-progress" data-kind="${escapeHtml(progress.kind)}" data-run-id="${escapeHtml(progress.run_id)}">查看</button></div>`;
}

async function loadHome() {
  const generation=++homeGeneration;
  const deadlineLoads=Promise.allSettled(homeLoaders.map(loader=>loader()));
  try {
    const home = await api('/api/mom/home');
    if(generation!==homeGeneration)return;
    state.home=home;
    $('#priorityList .load-error')?.remove();
    $('#todayDate').textContent = new Intl.DateTimeFormat('zh-TW',{timeZone:'Asia/Taipei',month:'long',day:'numeric',weekday:'long'}).format(new Date());
    const priority = state.home.priority || [];
    $('#todaySummary').textContent = priority.length ? `${state.home.counts.cases} 件旅行案件 · ${priority.length} 件優先處理` : '目前沒有待處理案件。';
    const p = $('#primaryTodayAction');
    if (priority[0]?.next_action) {
      p.textContent = `先處理：${priority[0].next_action.label}`;
      p.dataset.action = 'next-action'; p.dataset.kind = priority[0].next_action.kind; p.dataset.caseId = priority[0].id; p.dataset.runId = priority[0].next_action.run_id || '';p.dataset.recordId=priority[0].next_action.record_id||'';
    } else { p.textContent = '＋ 新客人'; p.dataset.action = 'new-case'; p.dataset.kind=''; p.dataset.caseId=''; }
    $('#priorityList').innerHTML = priority.length ? priority.map((i,index) => renderCaseCard(i,true,index)).join('') : '<div class="empty-state">今天沒有急件。需要時可以直接建立新客人。</div>';
    const priorityIds = new Set(priority.map(item=>item.id));
    const recent = (state.home.recent_cases || []).filter(item=>!priorityIds.has(item.id)).slice(0,3);
    $('#recentCases').innerHTML = recent.length ? recent.map(i=>renderCaseCard(i)).join('') : '<div class="empty-state">其餘案件可至「全部案件」查看。</div>';
    const searches = [...(state.home.searches?.flight || []), ...(state.home.searches?.hotel || [])].sort((a,b)=>(Date.parse(b.updated_at)||0)-(Date.parse(a.updated_at)||0));
    await deadlineLoads;
    if(generation!==homeGeneration)return;
    $('#searchProgressList').innerHTML = searches.length ? searches.slice(0,3).map(renderSearchSummary).join('') : '<p class="muted">目前沒有背景查價。</p>';
  } catch (err) { if (err instanceof ReauthenticationError || generation!==homeGeneration) return; showLoadError('priorityList',err,'retry-home'); }
}

async function loadCases() {
  const generation=++casesGeneration;
  try {
    const cases=await api('/api/cases');
    if(generation!==casesGeneration)return;
    state.cases=cases;
    renderCases();
  } catch (err) { if (err instanceof ReauthenticationError || generation!==casesGeneration) return; showLoadError('caseList',err,'retry-cases'); }
}

function showLoadError(id,err,action) {
  const el=$('#'+id);el.querySelector('.load-error')?.remove();
  el.insertAdjacentHTML('afterbegin',`<div class="notice-card warn load-error" role="alert">更新失敗，畫面可能仍是上次內容。${escapeHtml(friendlyError(err))}<button class="secondary-button" type="button" data-action="${action}">重新載入</button></div>`);
}

function renderCases() {
  const q = ($('#caseSearchInput')?.value || '').trim().toLowerCase();
  const rows = state.cases.filter(c => !q || `${c.customer_name} ${c.destination || ''}`.toLowerCase().includes(q));
  $('#caseList').innerHTML = rows.length ? rows.map(c => `<article class="case-card"><div class="card-title">${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination || '目的地未定')}</div><div class="card-sub">${escapeHtml(c.depart_date || '日期未定')} ${c.return_date ? `→ ${escapeHtml(c.return_date)}` : ''}</div><button class="secondary-button" type="button" data-action="open-case" data-case-id="${escapeHtml(c.id)}">繼續處理</button></article>`).join('') : '<div class="empty-state">找不到符合的案件。</div>';
}

async function openCase(caseId) {
  const sheetToken = beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const data = await api(`/api/mom/cases/${encodeURIComponent(caseId)}`);
    let operations=null;
    try {operations=await api(`/api/mom/cases/${encodeURIComponent(caseId)}/operations`);}
    catch(err){if(err instanceof ReauthenticationError)throw err;}
    const c = data.case, a = data.next_action;
    const primary=actionButton(a);
    const buttons = [
      ['edit-case','修改需求與旅客資料'], ['case-options','比較與選方案'],
      ['add-manual','＋ 錄入供應商方案'], ['flight-search','查機票'], ['hotel-search','查飯店'], ['customer-reply','回覆這位客人'],
    ].map(([action,label])=>`<button class="secondary-button full" type="button" data-action="${action}" data-case-id="${escapeHtml(c.id)}">${label}</button>`).join('');
    const selections = (data.selections || []).map(option=>`<div class="notice-card ${option.usable?'ok':'warn'}"><b>已選${option.kind==='flight'?'機票':'住宿'}：</b>${escapeHtml(option.title)}${option.usable?'':`<p>${escapeHtml(option.blockers.join('；'))}</p>`}</div>`).join('');
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet(`${c.customer_name} · ${c.destination || '旅行案件'}`, `<div class="notice-card"><b>下一步：${escapeHtml(a.label)}</b><br><span class="muted">${escapeHtml(a.reason)}</span><div class="operation-actions">${primary}</div></div><div class="form-grid"><div><b>日期</b><p>${escapeHtml(c.depart_date || '未定')} ${c.return_date ? `→ ${escapeHtml(c.return_date)}` : ''}</p></div><div><b>旅客</b><p>${c.adults} 大人、${c.children} 小孩、${c.infants || 0} 嬰兒${c.children?`<br>小孩年齡：${escapeHtml(c.children_ages?.join('、') || '待補齊')}`:''}</p></div><div><b>預算</b><p>${c.budget_twd !== null ? `NT$ ${Number(c.budget_twd).toLocaleString()}` : '尚未設定'}</p></div><div><b>偏好與備註</b><p>${escapeHtml(c.notes || '尚未填寫')}</p></div></div>${selections}${caseOperationTiles(c,operations)}<details class="sales-actions"><summary>查價、選案與修改需求</summary><div class="stack">${buttons}</div></details>`,true,'new-case',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}

async function startGuided(reset = false) {
  setView('new', false);
  try {
    const reply = await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/start?reset=${reset ? 'true' : 'false'}`, {method:'POST'});
    renderGuided(reply);
  } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
async function resumeGuided() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/resume`)); } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); } }
async function sendGuided(textOverride) {
  if (state.guidedBusy) return;
  const input = $('#wizardInput'); const text = textOverride ?? input.value;
  if (!String(text).trim()) return showToast('先回答這一題就好。');
  state.guidedBusy = true;
  try { const r = await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/reply`, {method:'POST', body:JSON.stringify({text})}); input.value=''; renderGuided(r); if (r.done) { await Promise.all([loadHome(),loadCases()]); } } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); } finally { state.guidedBusy = false; }
}
async function guidedBack() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/back`, {method:'POST'})); } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); } }
async function guidedSave() { try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/save`, {method:'POST'})); showToast('已經幫您存好了。'); } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); } }
async function guidedReset() { if (!confirm('要重新開始這個尚未完成的引導嗎？')) return; try { renderGuided(await api(`/api/guided/${encodeURIComponent(state.wizardSession)}/reset`, {method:'POST'})); } catch (err) { if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); } }

function renderGuided(reply) {
  $('#wizardQuestion').textContent = reply.text;
  const current = reply.progress_current || 0, total = reply.progress_total || 6;
  $('#wizardProgressLabel').textContent = reply.done ? '完成' : `第 ${Math.max(1,current)} 題，共 ${total} 題`;
  const pct = reply.done ? 100 : Math.round((current-1) / total * 100);
  $('#wizardProgressBar').className = `progress-fill p${Math.min(100, Math.max(0, Math.round(pct/10)*10))}`;
  $('#wizardOptions').innerHTML = reply.done ? '' : (reply.options || []).map(o => `<button class="choice-button" type="button" data-guided-option="${escapeHtml(o)}">${escapeHtml(o)}</button>`).join('');
  $('#wizardBack').disabled = !reply.can_back;
  if (reply.done && reply.case_id) {
    $('#wizardOptions').innerHTML = [['flight-search','✈️ 查機票'],['hotel-search','🏨 查飯店'],['add-manual','＋ 錄入已查到的方案'],['customer-reply','💬 回覆客人']].map(([action,label])=>`<button class="choice-button" type="button" data-action="${action}" data-case-id="${escapeHtml(reply.case_id)}">${label}</button>`).join('');
    $('#wizardOptions').insertAdjacentHTML('beforeend', `<button class="primary-button full" type="button" data-action="open-case" data-case-id="${escapeHtml(reply.case_id)}">打開案件</button>`);
  }
  $('#wizardInput').disabled = Boolean(reply.done);
  $('[data-action=guided-send]').disabled = Boolean(reply.done);
}

function selectedCaseOptions(selected='') {
  return `<option value="">不綁定案件</option>${state.cases.map(c => `<option value="${escapeHtml(c.id)}" ${selected===c.id?'selected':''}>${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination||'未定')}</option>`).join('')}`;
}

function field(label, name, value='', attributes='') {
  return `<label><span>${escapeHtml(label)}</span><input name="${escapeHtml(name)}" value="${escapeHtml(value ?? '')}" ${attributes}></label>`;
}
function parseAges(value) {
  const raw = String(value || '').trim();
  if (!raw) return null;
  const parts = raw.split(/[,，、\s]+/);
  if (parts.some(part=>!/^\d{1,2}$/.test(part) || Number(part)>17)) throw new Error('請用整數填小孩年齡（0–17 歲），以逗號分隔。');
  return parts.map(Number);
}
function localDateTime(value = new Date()) {
  const date = new Date(value);
  return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
}
function displayTime(value) {
  return value ? new Date(value).toLocaleString('zh-TW') : '未設定';
}
function optionPrice(option) {
  return `${escapeHtml(option.currency)} ${Number(option.total_amount).toLocaleString('zh-TW', {minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
async function openEditCase(caseId) {
  const sheetToken = beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const c = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    const statuses = {new:'剛建立',intake:'確認需求中',quoting:'查價與報價中',booking:'準備訂購',confirmed:'已人工確認訂購',travelling:'旅途中',closed:'已完成'};
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet('修改案件需求', `<form id="caseEditForm" class="form-grid" data-case-id="${escapeHtml(caseId)}">
      ${field('客人稱呼','customer_name',c.customer_name,'required maxlength="80"')}
      ${field('目的地','destination',c.destination)}${field('出發機場代碼','origin',c.origin,'maxlength="3" required')}
      <div class="form-grid two">${field('出發日期','depart_date',c.depart_date,'type="date"')}${field('回程／退房日期','return_date',c.return_date,'type="date"')}</div>
      <div class="form-grid two">${field('成人','adults',c.adults,'type="number" min="1" max="50" required')}${field('小孩','children',c.children,'type="number" min="0" max="50" required')}${field('嬰兒','infants',c.infants || 0,'type="number" min="0" max="20" required')}</div>
      ${field('每位小孩的年齡（例如 5, 8；未知可先留白）','children_ages',c.children_ages?.join(', ') || '')}
      ${field('全團總預算（NT$）','budget_twd',c.budget_twd,'type="number" min="0"')}
      <label><span>偏好與備註</span><textarea name="notes" rows="3">${escapeHtml(c.notes || '')}</textarea></label>
      <label><span>案件進度</span><select name="status">${Object.entries(statuses).map(([value,label])=>`<option value="${value}" ${c.status===value?'selected':''} ${['booking','confirmed'].includes(value)&&c.status!==value?'disabled':''}>${label}</option>`).join('')}</select></label>
      <p class="muted">變更日期、目的地或旅客後，原方案會要求重新查價。訂購進度由客人採用報價及訂購確認更新。</p>
      <button class="primary-button full" type="submit">儲存案件需求</button></form>`,true,'edit-case',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
function markFormCommitted(form, action, details={}) {
  form.dataset.committed='true';form.dataset.dirty='false';form.refreshAction={action,...details};
}
function savedFormRefresh(form) {
  const item=form.refreshAction;if(!item)return '';
  return `<button type="button" class="secondary-button" data-action="${escapeHtml(item.action)}" data-case-id="${escapeHtml(item.caseId||'')}" data-kind="${escapeHtml(item.kind||'')}" data-run-id="${escapeHtml(item.runId||'')}" data-module="${escapeHtml(item.module||'')}">重新載入已保存紀錄</button>`;
}
async function submitCaseEdit(form) {
  const submissionGeneration=sheetGeneration;
  const fd = new FormData(form), caseId = form.dataset.caseId;
  const payload = {customer_name:fd.get('customer_name'),destination:fd.get('destination')||null,origin:String(fd.get('origin')).toUpperCase(),depart_date:fd.get('depart_date')||null,return_date:fd.get('return_date')||null,adults:Number(fd.get('adults')),children:Number(fd.get('children')),infants:Number(fd.get('infants')),children_ages:parseAges(fd.get('children_ages')),budget_twd:fd.get('budget_twd')===''?null:Number(fd.get('budget_twd')),notes:fd.get('notes'),status:fd.get('status')};
  await api(`/api/cases/${encodeURIComponent(caseId)}`,{method:'PATCH',body:JSON.stringify(payload)});
  markFormCommitted(form,'open-case',{caseId});
  showToast('案件需求已更新。'); await Promise.all([loadCases(),loadHome()]); if(sheetRequestCurrent(submissionGeneration)&&form.isConnected)await openCase(caseId);
}
async function openFlightSearch(caseId='', transition=null) {
  const sheetToken = transition ?? beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const data = caseId ? await api(`/api/mom/cases/${encodeURIComponent(caseId)}`) : null;
    const c = data?.case;
    const prefs = state.preferences || {default_origin:'TPE',preferred_airlines:['CI','JX','CX','AE','BR']};
    const choices = data?.airport_choices || [];
    const destination = choices.length===1 ? choices[0] : '';
    const airlineChecks = state.airlines.map(a=>`<label class="checkbox-pill"><input type="checkbox" name="airline" value="${escapeHtml(a.code)}" ${prefs.preferred_airlines.includes(a.code)?'checked':''}>${escapeHtml(a.name_zh || a.name || a.code)}</label>`).join('');
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet('查機票', `<form id="flightForm" class="form-grid"><label><span>案件（選擇後自動帶入需求）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label>
      ${c?`<div class="notice-card">${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination || '目的地未定')}。${choices.length>1?`請選目的地機場：${escapeHtml(choices.join('、'))}`:'請核對以下需求。'}</div>`:''}
      <div class="form-grid two">${field('出發機場','origin',c?.origin || prefs.default_origin,'maxlength="3" required')}${field('目的地機場','destination',destination,'maxlength="3" list="airportChoices" placeholder="NRT" required')}</div><datalist id="airportChoices">${choices.map(code=>`<option value="${code}"></option>`).join('')}</datalist>
      ${field('出發日期','depart_date',c?.depart_date,'type="date" required')}${field('回程日期（單程可留白）','return_date',c?.return_date,'type="date"')}
      <div class="form-grid two">${field('成人','adults',c?.adults ?? 2,'type="number" min="1" max="20" required')}${field('小孩','children',c?.children ?? 0,'type="number" min="0" max="20" required')}${field('嬰兒','infants',c?.infants ?? 0,'type="number" min="0" max="20" required')}</div>
      ${field('每位小孩的年齡（例如 5, 8；未知可先留白）','children_ages',c?.children_ages?.join(', ') || '')}
      <fieldset><legend class="fieldset-title">航空公司</legend><div class="checkbox-grid">${airlineChecks}</div></fieldset><label class="checkbox-pill"><input name="nonstop" type="checkbox">直飛優先</label>
      <label><span>最重要的偏好</span><textarea name="notes" rows="3" placeholder="例如：含托運行李、不要太早">${escapeHtml(c?.notes || '')}</textarea></label>
      <div class="notice-card">${state.openclawEnabled?'可建立官網查詢。':'目前可保存查詢條件；實際價格可用下方「錄入人工查價」保存。'} 所有方案都需在訂購前再次確認。</div>
      <button class="primary-button full" type="submit">${state.openclawEnabled?'開始查官方網站':'保存查價條件'}</button><button class="secondary-button full" type="button" data-action="add-manual" data-kind="flight" data-case-id="${escapeHtml(caseId)}">＋ 錄入人工查價</button>
      ${caseId?`<button class="secondary-button full" type="button" data-action="edit-case" data-case-id="${escapeHtml(caseId)}">需求有變？先修改案件</button>`:''}</form>`,true,'search',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
async function submitFlightSearch(form) {
  const submissionGeneration=sheetGeneration;
  const fd = new FormData(form); const airlines = [...form.querySelectorAll('input[name="airline"]:checked')].map(x=>x.value);
  if (!airlines.length) throw new Error('至少選一家航空公司。');
  const returnDate = fd.get('return_date') || null;
  const payload = {case_id:fd.get('case_id')||null,origin:String(fd.get('origin')).toUpperCase(),destination:String(fd.get('destination')).toUpperCase(),depart_date:fd.get('depart_date'),return_date:returnDate,trip_type:returnDate?'round_trip':'one_way',adults:Number(fd.get('adults')),children:Number(fd.get('children')),infants:Number(fd.get('infants')),children_ages:parseAges(fd.get('children_ages')),airline_codes:airlines,nonstop_preferred:fd.get('nonstop')==='on',notes:String(fd.get('notes')||'')};
  const plan = await api('/api/browser/flight-search',{method:'POST',body:JSON.stringify(payload)});
  markFormCommitted(form,'refresh-progress',{kind:'flight',runId:plan.run.id});
  if(state.openclawEnabled) await api(`/api/mom/flight-search/${encodeURIComponent(plan.run.id)}/start`,{method:'POST'});
  showToast(state.openclawEnabled?'查詢已建立。':'查價條件已保存，可隨時錄入實際價格。'); await loadHome(); if(sheetRequestCurrent(submissionGeneration)&&form.isConnected)await openSearchProgress('flight',plan.run.id);
}
async function openHotelSearch(caseId='', transition=null) {
  const sheetToken = transition ?? beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const data = caseId ? await api(`/api/mom/cases/${encodeURIComponent(caseId)}`) : null, c = data?.case;
    const networks = state.hotelNetworks.map(n=>`<option value="${escapeHtml(n.code)}" data-home="${escapeHtml(n.official_home)}">${escapeHtml(n.name)}</option>`).join('');
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet('查飯店', `<form id="hotelForm" class="form-grid"><label><span>案件（選擇後自動帶入需求）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label>
      ${c?`<div class="notice-card">${escapeHtml(c.destination || '目的地待確認')} · ${c.adults} 成人、${c.children} 小孩、${c.infants || 0} 嬰兒</div>`:''}
      <label><span>飯店集團</span><select id="hotelNetworkSelect" name="network"><option value="">自己輸入官方網址</option>${networks}</select></label>
      ${field('飯店名稱','hotel_name','','placeholder="例如 Hilton Tokyo" required')}
      <label><span>官方網站（建議填分館網址）</span><input id="hotelOfficialUrl" name="official_url" type="url" placeholder="https://www.hilton.com/…" required></label>
      <div class="form-grid two">${field('入住','checkin_date',c?.depart_date,'type="date" required')}${field('退房','checkout_date',c?.return_date,'type="date" required')}</div>
      <div class="form-grid two">${field('房間','rooms',1,'type="number" min="1" max="8" required')}${field('成人','adults',c?.adults ?? 2,'type="number" min="1" max="24" required')}</div>
      ${field('每位小孩與嬰兒的年齡（小孩先填，再填嬰兒；以逗號分隔）','children_ages',c?.children_ages?.join(', ') || '', c && c.children+(c.infants||0)>0?'required':'')}
      <label class="checkbox-pill"><input name="breakfast" type="checkbox">需要早餐</label><label class="checkbox-pill"><input name="free_cancel" type="checkbox" checked>優先可免費取消</label>
      <label><span>偏好</span><textarea name="notes" rows="3" placeholder="例如：近車站、安靜、兩張床">${escapeHtml(c?.notes || '')}</textarea></label>
      <div class="notice-card">${state.openclawEnabled?'可查已核准的飯店官網。':'目前可保存條件，或直接錄入供應商提供的房價。'} 第一次使用獨立官網需要管理員確認。</div>
      <button class="primary-button full" type="submit">${state.openclawEnabled?'開始查飯店官網':'保存查價條件'}</button><button class="secondary-button full" type="button" data-action="add-manual" data-kind="hotel" data-case-id="${escapeHtml(caseId)}">＋ 錄入人工查價</button>
      ${caseId?`<button class="secondary-button full" type="button" data-action="edit-case" data-case-id="${escapeHtml(caseId)}">需求有變？先修改案件</button>`:''}</form>`,true,'search',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
async function submitHotelSearch(form) {
  const submissionGeneration=sheetGeneration;
  const fd = new FormData(form);
  const payload = {case_id:fd.get('case_id')||null,hotel_name:fd.get('hotel_name'),official_url:fd.get('official_url'),checkin_date:fd.get('checkin_date'),checkout_date:fd.get('checkout_date'),rooms:Number(fd.get('rooms')),adults:Number(fd.get('adults')),children_ages:parseAges(fd.get('children_ages')) || [],currency_preference:'TWD',breakfast_required:fd.get('breakfast')==='on',free_cancellation_preferred:fd.get('free_cancel')==='on',notes:String(fd.get('notes')||'')};
  const plan = await api('/api/browser/hotel-search',{method:'POST',body:JSON.stringify(payload)});
  markFormCommitted(form,'refresh-progress',{kind:'hotel',runId:plan.run.id});
  if(state.openclawEnabled) await api(`/api/mom/hotel-search/${encodeURIComponent(plan.run.id)}/start`,{method:'POST'});
  showToast(state.openclawEnabled?'查詢已建立。':'查價條件已保存。'); await loadHome(); if(sheetRequestCurrent(submissionGeneration)&&form.isConnected)await openSearchProgress('hotel',plan.run.id);
}
async function openManualOption(caseId='', kind='flight') {
  caseId = caseId || $('#flightForm [name=case_id]')?.value || $('#hotelForm [name=case_id]')?.value || '';
  if (!caseId) {
    showToast('請先選一個案件，方案才會保存到正確的客人。');
    (sheetBody.querySelector('[name=case_id]')||$('#caseSearchInput'))?.focus();
    return;
  }
  const sheetToken = beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const c = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet('錄入供應商方案', `<form id="manualOptionForm" class="form-grid" data-case-id="${escapeHtml(caseId)}">
      <div class="notice-card">${escapeHtml(c.customer_name)} · ${escapeHtml(c.destination || '目的地待確認')}<br>${escapeHtml(c.depart_date || '日期待補')} → ${escapeHtml(c.return_date || '單程／回程待補')}<br>${c.adults} 成人、${c.children} 小孩、${c.infants || 0} 嬰兒</div>
      ${c.children && c.children_ages===null?`<div class="notice-card warn">請先補小孩年齡，才可核對完整價格。<button type="button" class="secondary-button full" data-action="edit-case" data-case-id="${escapeHtml(caseId)}">補齊旅客資料</button></div>`:''}
      <label><span>方案種類</span><select name="kind"><option value="flight" ${kind==='flight'?'selected':''}>機票</option><option value="hotel" ${kind==='hotel'?'selected':''}>飯店</option></select></label>
      ${field('航空／飯店／供應商名稱','supplier_name','','required maxlength="160"')}${field('方案名稱（航班、票種或房型）','title','','required maxlength="240"')}
      <div class="form-grid two">${field('對客參考總價（此案件全部旅客，含已知稅費）','total_amount','','type="number" min="0.01" step="0.01" required')}<label><span>幣別</span><select name="currency"><option>TWD</option><option>JPY</option><option>USD</option><option>EUR</option><option>HKD</option></select></label></div>
      <label><span>方案內容（日期／航班時段、行李或房數／床型／早餐）</span><textarea name="details" rows="4" required maxlength="2400"></textarea></label>
      <label><span>退改／取消條件、額外費用與尚待確認事項</span><textarea name="conditions" rows="3" required maxlength="1600" placeholder="未知的項目請寫待確認，不要假設為免費。"></textarea></label>
      ${field('內部來源紀錄（窗口或 Email 等，不會放進客戶草稿）','source_reference','','required maxlength="500"')}${field('內部來源網址（可留白；不會放進客戶草稿）','source_url','','type="url"')}
      ${field('實際查詢／收到報價時間','observed_at',localDateTime(),'type="datetime-local" required')}${field('供應商報價有效至（不確定可留白）','valid_until','','type="datetime-local"')}
      <label class="checkbox-pill"><input type="checkbox" name="confirmed_for_case" required>我已確認日期與所有旅客符合此案件，且以上是實際查到的總價。</label>
      <p class="muted">這會標示為人工錄入，保存後可比較與選取；不會訂購或保留機位／房間。</p>
      <button class="primary-button full" type="submit">保存這個方案</button></form>`,true,'manual-options',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
async function submitManualOption(form) {
  const submissionGeneration=sheetGeneration;
  const fd = new FormData(form), caseId = form.dataset.caseId;
  const payload = {kind:fd.get('kind'),supplier_name:fd.get('supplier_name'),title:fd.get('title'),total_amount:fd.get('total_amount'),currency:fd.get('currency'),details:fd.get('details'),conditions:fd.get('conditions'),source_reference:fd.get('source_reference'),source_url:fd.get('source_url')||null,observed_at:new Date(fd.get('observed_at')).toISOString(),valid_until:fd.get('valid_until')?new Date(fd.get('valid_until')).toISOString():null,confirmed_for_case:fd.get('confirmed_for_case')==='on'};
  await api(`/api/mom/cases/${encodeURIComponent(caseId)}/options`,{method:'POST',body:JSON.stringify(payload)});
  markFormCommitted(form,'case-options',{caseId});
  showToast('方案已保存，可以比較與選取。'); await loadHome(); if(sheetRequestCurrent(submissionGeneration)&&form.isConnected)await openCaseOptions(caseId);
}
function renderOptionCard(option, caseId, selected=false) {
  const warnings = [...(option.blockers || []), ...(option.warnings || [])];
  const url = option.source_url && /^https?:\/\//i.test(option.source_url) ? `<a href="${escapeHtml(option.source_url)}" target="_blank" rel="noopener noreferrer">查看來源</a>` : '';
  return `<article class="case-card option-card ${selected?'selected-option':''}"><div class="card-sub">${option.kind==='flight'?'機票':'飯店'} · ${option.is_demo?'示範資料':option.source_type==='manual'?'人工錄入':'官網查詢'}${selected?' · 已選取':''}</div><h3>${escapeHtml(option.supplier_name)} · ${escapeHtml(option.title)}</h3><p class="option-price">${optionPrice(option)}</p><p class="preserve-lines">${escapeHtml(option.details)}</p><p class="preserve-lines"><b>條件：</b>${escapeHtml(option.conditions)}</p><div class="card-sub">來源：${escapeHtml(option.source_reference)} ${url}<br>查詢：${escapeHtml(displayTime(option.observed_at))}${option.valid_until?`<br>有效至：${escapeHtml(displayTime(option.valid_until))}`:''}</div>${warnings.length?`<div class="notice-card warn">${warnings.map(w=>escapeHtml(w)).join('<br>')}</div>`:''}${selected?`<button class="secondary-button" type="button" data-action="clear-selection" data-case-id="${escapeHtml(caseId)}" data-kind="${escapeHtml(option.kind)}">取消選取</button>`:`<button class="primary-button" type="button" data-action="select-option" data-case-id="${escapeHtml(caseId)}" data-option-id="${escapeHtml(option.id)}" ${option.usable?'':'disabled'}>${option.usable?'選用這個參考方案':'需要重新確認'}</button>`}</article>`;
}
async function openCaseOptions(caseId) {
  const sheetToken = beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const data = await api(`/api/mom/cases/${encodeURIComponent(caseId)}/options`);
    const selected = new Map(data.selections.map(option=>[option.kind,option.id]));
    const groups = ['flight','hotel'].map(kind=>{
      const rows = data.options.filter(option=>option.kind===kind);
      return rows.length?`<h3>${kind==='flight'?'機票方案':'飯店方案'}</h3>${rows.map(option=>renderOptionCard(option,caseId,selected.get(kind)===option.id)).join('')}`:'';
    }).join('');
    const missing = data.selections.filter(selection=>!data.options.some(option=>option.id===selection.id));
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet(`${data.case.customer_name} · 比較與選方案`, `<div class="notice-card">每次可選一個機票與一個飯店方案。不同幣別分開比較，選取不代表訂購完成。</div><div class="stack"><button class="secondary-button full" type="button" data-action="add-manual" data-case-id="${escapeHtml(caseId)}">＋ 錄入另一個方案</button>${groups || '<div class="empty-state">還沒有實際價格。先錄入供應商提供的方案，或查看官網查詢結果。</div>'}${missing.map(option=>renderOptionCard(option,caseId,true)).join('')}<button class="primary-button full" type="button" data-action="customer-reply" data-case-id="${escapeHtml(caseId)}">${data.can_draft_offer?'整理已選方案回客人':'先整理需求回客人'}</button><button class="secondary-button full" type="button" data-action="open-case" data-case-id="${escapeHtml(caseId)}">回案件</button></div>`,true,'compare',caseId,sheetToken))return;
    return true;
  } catch (err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return; showToast(friendlyError(err)); }
}
async function changeCaseSelection(el,clear=false) {
  if(sheetBody.dataset.saving==='true')return;
  const generation=sheetGeneration;
  const controls=$$('[data-action="select-option"], [data-action="clear-selection"]');
  const disabled=controls.map(c=>c.disabled);
  sheetBody.dataset.saving='true';controls.forEach(c=>{c.disabled=true;});
  try {
    const path=`/api/mom/cases/${encodeURIComponent(el.dataset.caseId)}/selection`;
    await api(clear?`${path}/${el.dataset.kind}`:path,clear?{method:'DELETE'}:{method:'POST',body:JSON.stringify({option_id:el.dataset.optionId})});
    showToast(clear?'已清除參考選案。':'已選定參考方案，尚未訂購。');
    sheetBody.dataset.saving='false';
    await loadHome();
    if(sheetRequestCurrent(generation)&&sheet.open)await openCaseOptions(el.dataset.caseId);
  } catch(err) {if(!(err instanceof ReauthenticationError))showToast(friendlyError(err));}
  finally {sheetBody.dataset.saving='false';controls.forEach((c,i)=>{if(c.isConnected)c.disabled=disabled[i];});}
}
function selectCaseOption(el){return changeCaseSelection(el);}
function clearCaseSelection(el){return changeCaseSelection(el,true);}

async function openSearchProgress(kind,runId,keepScroll=false) {
  if(keepScroll&&sheetGeneration!==renderedSheetGeneration)return;
  const sheetToken = keepScroll ? sheetGeneration : beginSheetRequest();
  if(sheetToken===null)return;
  try {
    const p = await api(`/api/mom/search-progress/${kind}/${encodeURIComponent(runId)}`);
    const detail = await api(kind==='flight'?`/api/browser/runs/${encodeURIComponent(runId)}`:`/api/browser/hotel-runs/${encodeURIComponent(runId)}`);
    let results = '';
    if (p.case_id) {
      const workflow = await api(`/api/mom/cases/${encodeURIComponent(p.case_id)}/options`);
      const rows = workflow.options.filter(option=>option.run_id===runId);
      results = rows.map(option=>renderOptionCard(option,p.case_id,workflow.selections.some(s=>s.id===option.id))).join('');
      if(!rows.length)results='<div class="notice-card">這次還沒有可用的官網方案，可以錄入人工查到的價格。</div>';
    } else {
      results = (detail.comparison?.currency_groups || []).map(group=>`<div class="notice-card"><b>${escapeHtml(group.currency)} 官網候選方案</b>${group.ranked.map(row=>`<p>${escapeHtml(row.airline_name || row.hotel_name)} · ${escapeHtml(row.option.option_id)} · ${escapeHtml(group.currency)} ${Number(row.option.total_amount).toLocaleString()}</p>`).join('')}</div>`).join('') + '<p class="muted">此查詢未綁定案件。請從案件建立查詢，以保存選案與客戶回覆。</p>';
    }
    const start = state.openclawEnabled && !['running','completed'].includes(p.status) ? `<button class="secondary-button full" type="button" data-action="start-search" data-kind="${kind}" data-run-id="${escapeHtml(runId)}">開始／重試自動查詢</button>` : '';
    if (!sheetRequestCurrent(sheetToken)) return;
    if(!openSheet(kind==='flight'?'機票查價進度與結果':'飯店查價進度與結果',renderProgressCard(p)+start+results,!keepScroll,'search',p.case_id || '',sheetToken))return;
    if(p.status==='running')startPolling(kind,runId);
    return true;
  } catch(err) { cancelSheetRequest(sheetToken); if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}
}
function startPolling(kind,runId){const key=`${kind}:${runId}`;if(state.activePollers.has(key))return;const id=setInterval(async()=>{try{const p=await api(`/api/mom/search-progress/${kind}/${encodeURIComponent(runId)}`);if(sheet.open && sheetGeneration===renderedSheetGeneration && sheetBody.querySelector(`[data-run-id="${CSS.escape(runId)}"]`)) await openSearchProgress(kind,runId,true);if(p.status!=='running'){clearInterval(id);state.activePollers.delete(key);loadHome();}}catch{clearInterval(id);state.activePollers.delete(key);}},3500);state.activePollers.set(key,id);}

function openCustomerReply(caseId='') {
  openSheet('幫您整理客戶回覆', `<form id="replyForm" class="form-grid"><label><span>案件（可不選）</span><select name="case_id">${selectedCaseOptions(caseId)}</select></label><label><span>客人說什麼？</span><textarea name="incoming_text" rows="6" placeholder="直接貼客人的 LINE 訊息就好…" required></textarea></label><label><span>語氣</span><select name="tone"><option>專業、親切、簡潔</option><option>比較口語、自然</option><option>正式、穩重</option></select></label><button class="primary-button full" type="submit">先幫我寫草稿</button><p class="muted">只會產生草稿，不會直接傳給客人。</p></form>`,true,'reply');
}

async function submitCustomerReply(form) {
  const submissionGeneration=sheetGeneration;
  const fd=new FormData(form);
  const result=await api('/api/customer-reply',{method:'POST',body:JSON.stringify({case_id:fd.get('case_id')||null,incoming_text:fd.get('incoming_text'),tone:fd.get('tone')})});
  if(!sheetRequestCurrent(submissionGeneration)||!form.isConnected)return;
  state.currentDraft={case_id:fd.get('case_id')||null,text:result.text,source:result.source};
  sheetBody.innerHTML=`<div class="notice-card ok">${result.source==='template'?'已用案件資料與已選方案整理草稿，可直接修改文字。':'已產生回覆草稿。'} 請您核對後再貼給客人。</div><label class="form-grid"><span>回覆草稿（可修改）</span><textarea class="reply-editor" id="replyDraft" data-dirty="true" rows="14">${escapeHtml(result.text)}</textarea></label><button class="primary-button full" type="button" data-action="copy-draft">複製目前草稿</button><div class="feedback-row"><button type="button" data-feedback="accepted">👍 可以直接用</button><button type="button" data-feedback="edited">✏️ 我有修改</button><button type="button" data-feedback="prefer_future">🧠 以後都這樣</button><button type="button" data-feedback="rejected">👎 不要這樣</button></div><p class="muted">回饋先保存成改進紀錄，不會自動改變下次回覆。</p>`;
  $('.sheet').scrollTop=0;
}

async function submitFeedback(type){
  if(!state.currentDraft)return;
  if(type==='accepted'){
    try{await api('/api/mom/skill-feedback',{method:'POST',body:JSON.stringify({skill_key:'customer-reply',feedback_type:type,source:state.currentDraft.source==='template'?'web_template':'mom_web',case_id:state.currentDraft.case_id,draft_text:state.currentDraft.text,final_text:$('#replyDraft')?.value})});showToast('收到，這次草稿可以直接使用。');}catch(err){ if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}
    return;
  }
  const title=type==='edited'?'把最後修改的版本貼給我':type==='prefer_future'?'希望以後保留哪個做法？':'哪一點不要再這樣？';
  const help=type==='edited'?'只要貼您最後真的會傳給客人的版本。':'簡單說一句就好，不需要寫成規則。';
  sheetBody.insertAdjacentHTML('beforeend',`<form id="feedbackDetailForm" class="form-grid notice-card" data-feedback-type="${escapeHtml(type)}"><label><span>${escapeHtml(title)}</span><textarea name="detail" rows="4" placeholder="${escapeHtml(help)}" required></textarea></label><button class="primary-button full" type="submit">送出這次回饋</button></form>`);
  $('#feedbackDetailForm textarea')?.focus();
  if(type==='edited')$('#feedbackDetailForm textarea').value=$('#replyDraft')?.value || '';
}

async function submitFeedbackDetail(form){
  const type=form.dataset.feedbackType; const detail=new FormData(form).get('detail');
  const payload={skill_key:'customer-reply',feedback_type:type,source:state.currentDraft?.source==='template'?'web_template':'mom_web',case_id:state.currentDraft?.case_id||null,draft_text:state.currentDraft?.text||null};
  if(type==='edited') payload.final_text=detail; else payload.note=detail;
  try{await api('/api/mom/skill-feedback',{method:'POST',body:JSON.stringify(payload)});form.remove();showToast('收到，我會把這次經驗留給後續 Skill 改進。');}catch(err){ if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}
}

async function inferIntent(){const text=$('#intentInput').value.trim();if(!text)return showToast('直接說現在發生什麼事就好。');try{const r=await api('/api/mom/intent',{method:'POST',body:JSON.stringify({text})});$('#intentResults').innerHTML=`<div class="notice-card">${escapeHtml(r.text)}</div>`+(r.suggestions||[]).map(s=>`<button class="quick-card" type="button" data-intent-action="${escapeHtml(s.action)}"><span><b>${escapeHtml(s.label)}</b><small>${escapeHtml(s.reason)}</small></span></button>`).join('');}catch(err){ if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}}

function runIntentAction(action){const map={customer_reply:()=>openCustomerReply(),flight_search:()=>openFlightSearch(),hotel_search:()=>openHotelSearch(),new_case:()=>startGuided(false),case_lookup:()=>setView('cases'),itinerary:()=>showToast('行程規劃會綁定案件處理，先選一個案件。'),visa:()=>showToast('簽證與入境資訊會要求權威來源，請先選案件。')};(map[action]||(()=>showToast('先從新客人或案件開始就好。')))();}

async function renderSettings(){if(!state.preferences)return;$('#defaultOrigin').value=state.preferences.default_origin;$('#preferredAirlines').innerHTML=state.airlines.map(a=>`<label class="checkbox-pill"><input type="checkbox" value="${escapeHtml(a.code)}" ${state.preferences.preferred_airlines.includes(a.code)?'checked':''}>${escapeHtml(a.name_zh||a.code)}</label>`).join('');const radio=document.querySelector(`input[name="fontScale"][value="${state.preferences.font_scale}"]`);if(radio)radio.checked=true;}
async function saveSettings(event){event.preventDefault();const preferred=[...$('#preferredAirlines').querySelectorAll('input:checked')].map(x=>x.value);const scale=document.querySelector('input[name="fontScale"]:checked')?.value||'large';try{state.preferences=await api('/api/mom/preferences',{method:'PATCH',body:JSON.stringify({default_origin:$('#defaultOrigin').value,preferred_airlines:preferred,font_scale:scale})});applyFontScale(scale);showToast('設定已儲存。');}catch(err){ if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}}

async function handleNextAction(el) {
  if(['quotes','bookings','tasks','ledger','pretrip'].includes(el.dataset.kind))return extraActions.get('ops-open')?.({dataset:{caseId:el.dataset.caseId,module:el.dataset.kind,recordId:el.dataset.recordId}});
  const kind=el.dataset.kind, caseId=el.dataset.caseId, runId=el.dataset.runId;
  if(kind==='flight_search') return openFlightSearch(caseId);
  if(kind==='hotel_search') return openHotelSearch(caseId);
  if(kind==='flight_run'&&runId) return openSearchProgress('flight',runId);
  if(kind==='hotel_run'&&runId) return openSearchProgress('hotel',runId);
  if(kind==='edit_case') return openEditCase(caseId);
  if(kind==='case_options') return openCaseOptions(caseId);
  if(kind==='customer_reply') return openCustomerReply(caseId);
  return openCase(caseId);
}
async function copyDraft() {
  const text = $('#replyDraft')?.value || state.currentDraft?.text || '';
  try {
    if(!navigator.clipboard) throw new Error('clipboard unavailable');
    await navigator.clipboard.writeText(text);
    showToast('已複製修改後的草稿，請確認後再貼給客人。');
  } catch {
    $('#replyDraft')?.focus(); $('#replyDraft')?.select();
    showToast('請手動複製已選取的草稿文字。');
  }
}
function builtinActionHandlers(el) {
  return {
    'open-settings':()=>setView('settings'), 'refresh-home':loadHome, 'new-case':()=>startGuided(false),
    'customer-reply':()=>openCustomerReply(el.dataset.caseId||''), 'flight-search':()=>openFlightSearch(el.dataset.caseId||''),
    'hotel-search':()=>openHotelSearch(el.dataset.caseId||''), 'open-case':()=>openCase(el.dataset.caseId),
    'edit-case':()=>openEditCase(el.dataset.caseId), 'case-options':()=>openCaseOptions(el.dataset.caseId),
    'add-manual':()=>openManualOption(el.dataset.caseId||'',el.dataset.kind||'flight'),
    'select-option':()=>selectCaseOption(el), 'clear-selection':()=>clearCaseSelection(el),
    'retry-component':()=>loadComponent(el.dataset.component),'retry-home':loadHome,'retry-cases':loadCases,
    'next-action':()=>handleNextAction(el), 'guided-send':()=>sendGuided(), 'guided-back':guidedBack,
    'guided-save':guidedSave, 'guided-reset':guidedReset, 'infer-intent':inferIntent, 'close-sheet':closeSheet,
    'refresh-progress':()=>openSearchProgress(el.dataset.kind,el.dataset.runId), 'copy-draft':copyDraft,
    'start-search':async()=>{const token=sheetGeneration;try {const result=await api(`/api/mom/${el.dataset.kind}-search/${encodeURIComponent(el.dataset.runId)}/start`,{method:'POST'});showToast(result.message||'查詢已開始。');if(sheetRequestCurrent(token))await openSearchProgress(el.dataset.kind,el.dataset.runId);}catch(err){ if (err instanceof ReauthenticationError) return;showToast(friendlyError(err));}},
    'login':async()=>{try{await loadSession();$('#loginDialog').close();if(!state.preferences)await boot();else await loadHome();showToast('已確認登入，可以繼續原本的工作。');}catch(err){if(!(err instanceof ReauthenticationError))showToast(friendlyError(err));}},
    'logout':()=>{sessionStorage.removeItem('travelDeskToken');if(state.auth?.logout_url==='/cdn-cgi/access/logout')location.assign(state.auth.logout_url);},
    'open-token':()=>{ $('#tokenInput').value=state.token; $('#tokenDialog').showModal(); },
    'clear-token':()=>{state.token='';sessionStorage.removeItem('travelDeskToken');$('#tokenInput').value='';showToast('連線密碼已清除。');},
  };
}
function runAction(handler) {
  try {
    const pending=handler(), generation=sheetGeneration;
    Promise.resolve(pending).catch(err=>{cancelSheetRequest(generation);if(!(err instanceof ReauthenticationError))showToast(friendlyError(err));});
  } catch(err) {if(!(err instanceof ReauthenticationError))showToast(friendlyError(err));}
}
function actionFromDataset(el) {
  const action=el.dataset.action;
  return runAction(()=>extraActions.has(action)?extraActions.get(action)(el):builtinActionHandlers(el)[action]?.());
}
document.addEventListener('click',event=>{
  const nav=event.target.closest('[data-nav]');
  if(nav) return nav.dataset.nav==='new'?startGuided(false):setView(nav.dataset.nav);
  const guided=event.target.closest('[data-guided-option]'); if(guided)return sendGuided(guided.dataset.guidedOption);
  const intent=event.target.closest('[data-intent-action]'); if(intent)return runIntentAction(intent.dataset.intentAction);
  const feedback=event.target.closest('[data-feedback]'); if(feedback)return submitFeedback(feedback.dataset.feedback);
  const action=event.target.closest('[data-action]'); if(action)return actionFromDataset(action);
});
document.addEventListener('submit',async event=>{
  const form=event.target;
  const handlers={flightForm:submitFlightSearch,hotelForm:submitHotelSearch,replyForm:submitCustomerReply,feedbackDetailForm:submitFeedbackDetail,caseEditForm:submitCaseEdit,manualOptionForm:submitManualOption};
  const handler=handlers[form.id] || extraForms.get(form.id); if(!handler)return;
  event.preventDefault(); if(form.dataset.busy==='true'||form.dataset.committed==='true')return; form.dataset.busy='true';
  const button=form.querySelector('button[type=submit]'); if(button)button.disabled=true;
  form.querySelector('.form-error')?.remove();
  try {const pending=handler(form);form.inert=true;await pending;} catch(err){ form.inert=false;if (err instanceof ReauthenticationError) return;const message=(form.dataset.committed==='true'?'已保存，但畫面更新失敗。請重新載入，勿重複儲存。 ':'')+friendlyError(err);showToast(message);if(form.isConnected)form.insertAdjacentHTML('beforeend',`<div class="notice-card warn form-error" role="alert" tabindex="-1">${escapeHtml(message)}${form.dataset.committed==='true'?savedFormRefresh(form):''}</div>`);form.querySelector('.form-error')?.focus();}
  finally {
    form.inert=false;form.dataset.busy='false';
    if(button)button.disabled=form.dataset.committed==='true';
    if(form.dataset.committed==='true'&&form.isConnected) {
      // The write has succeeded; a failed follow-up must not invite unsavable edits.
      form.querySelectorAll('input,select,textarea').forEach(el=>{el.disabled=true;});
      if(!form.querySelector('.form-error'))form.insertAdjacentHTML('beforeend',`<div class="notice-card warn form-error" role="status">已保存。以下內容僅供核對，請重新載入已保存紀錄。${savedFormRefresh(form)}</div>`);
    }
  }
});
document.addEventListener('change',event=>{
  if(event.target.id==='hotelNetworkSelect'){const option=event.target.selectedOptions[0];$('#hotelOfficialUrl').value=option?.dataset.home||'';}
  if(event.target.name==='case_id'&&['flightForm','hotelForm'].includes(event.target.form?.id)) {
    const el=event.target, value=el.value;
    // The association changes only when the complete replacement renders.
    el.value=el.dataset.previous;
    const token=beginSheetRequest();
    if(token===null)return;
    runAction(()=>el.form.id==='flightForm'?openFlightSearch(value,token):openHotelSearch(value,token));
  }
});
$('#caseSearchInput').addEventListener('input',renderCases);
$('#settingsForm').addEventListener('submit',saveSettings);
$('#onboardingForm').addEventListener('submit',saveOnboarding);
$('#tokenForm').addEventListener('submit',event=>{event.preventDefault();state.token=$('#tokenInput').value.trim();if(state.token)sessionStorage.setItem('travelDeskToken',state.token);else sessionStorage.removeItem('travelDeskToken');$('#tokenDialog').close();showToast('已套用連線密碼。');boot();});
$('#wizardInput').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();sendGuided();}});

function caseOperationTiles(c, ops) {
  if(!ops)return `<div class="notice-card warn" role="alert">業務紀錄暫時無法讀取。您仍可繼續處理售前工作。<button class="secondary-button" type="button" data-action="open-case" data-case-id="${escapeHtml(c.id)}">重新載入業務紀錄</button></div>`;
  const counts={quotes:ops.quotes.length,tasks:ops.work_items.filter(i=>i.status==='open').length,bookings:ops.bookings.filter(b=>b.status==='confirmed').length,ledger:ops.ledger.filter(e=>e.status!=='voided').length,pretrip:ops.documents.filter(d=>d.required&&(d.status!=='ready'||d.needs_recheck||d.booking_id&&!ops.bookings.some(b=>b.id===d.booking_id&&b.status==='confirmed'&&b.binding_current))).length};
  const labels={quotes:'報價版本',tasks:'期限待辦',bookings:'訂購確認',ledger:'收付款',pretrip:'行前交付'};
  return `<h3>案件工作</h3><div class="operation-tiles">${Object.entries(labels).map(([module,label])=>`<button class="secondary-button" type="button" data-action="ops-open" data-module="${module}" data-case-id="${escapeHtml(c.id)}"><b>${label}</b><small>${module==='pretrip'?`${counts[module]} 項待補文件`:`${counts[module]} 筆紀錄`}</small></button>`).join('')}</div>`;
}
$('#sheetBack').addEventListener('click',()=>runAction(()=>sheetBack?.()));
// closeSheet and cancel invalidate requests synchronously; a queued native close
// event must not invalidate a newer request begun after the dialog closes.
sheet.addEventListener('cancel',event=>{event.preventDefault();closeSheet();});
sheetBody.addEventListener('input',event=>{
  const el=event.target;
  if(el.name==='case_id'&&['flightForm','hotelForm'].includes(el.form?.id))return;
  const owner=el.closest('form')||el;
  owner.dataset.dirty='true';++editEpoch;
});
window.addEventListener('beforeunload',event=>{
  if(sheet.open&&(sheetDirty()||sheetBody.dataset.saving==='true'||sheetBody.querySelector('form[data-busy="true"]'))) {event.preventDefault();event.returnValue='';}
});
const builtInActionNames=new Set(Object.keys(builtinActionHandlers({dataset:{}})));
const builtInFormNames=new Set(['flightForm','hotelForm','replyForm','feedbackDetailForm','caseEditForm','manualOptionForm']);
window.MomApp=Object.freeze({
  api,openSheet,closeSheet,openCase,setSheetBack,beginSheetRequest,cancelSheetRequest,sheetRequestCurrent,loadHome,setView,
  currentSheetGeneration:()=>sheetGeneration,markFormCommitted,
  escapeHtml,field,localDateTime,friendlyError,showToast,ReauthenticationError,
  getCases:()=>state.cases,
  registerAction(name,handler){if(builtInActionNames.has(name)||extraActions.has(name))throw new Error('Duplicate action '+name);extraActions.set(name,handler);},
  registerForm(name,handler){if(builtInFormNames.has(name)||extraForms.has(name))throw new Error('Duplicate form '+name);extraForms.set(name,handler);},
  registerView(name,handler){if(['today','cases','new','assistant','settings'].includes(name)||extraViews.has(name))throw new Error('Duplicate view '+name);extraViews.set(name,handler);},
  registerHomeLoader(handler){homeLoaders.push(handler);},
});
boot();
