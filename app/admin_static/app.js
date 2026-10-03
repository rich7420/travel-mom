const sessionId = localStorage.getItem('travelSession') || ('web-' + crypto.randomUUID());
localStorage.setItem('travelSession', sessionId);
const modal = document.getElementById('modal');
let airlineRegistry = [];
let lastFlightTaskIds = [];
let lastFlightRunId = null;
let hotelNetworks = [];
let authMode = null;
let lastHotelRunId = null;
let lastHotelTaskIds = [];
let lastHotelSearchDraft = null;

function showAdminLogin() {
  const dialog=document.getElementById('adminLoginDialog');
  if(!dialog.open)dialog.showModal();
}
document.getElementById('adminLoginDialog').addEventListener('cancel', event => event.preventDefault());
document.getElementById('adminRelogin').addEventListener('click',()=>location.reload());

class ReauthenticationError extends Error {
  constructor() { super('login session expired'); this.name = 'ReauthenticationError'; }
}
// Inline async actions without a local catch still show the dedicated login dialog.
window.addEventListener('unhandledrejection', event => {
  if (event.reason instanceof ReauthenticationError) event.preventDefault();
});

async function api(path, opts = {}, retriedAuth = false) {
  const token = authMode !== 'token' ? '' : sessionStorage.getItem('travelDeskAdminToken') || '';
  const headers = {'Content-Type': 'application/json', ...(opts.headers || {})};
  if (token) headers['X-Travel-Desk-Admin-Token'] = token;
  const response = await fetch(path, {...opts, headers, redirect:'manual'});
  if (response.type === 'opaqueredirect' || response.status === 0 || (response.status === 401 && authMode === 'cloudflare')) {
    showAdminLogin();
    throw new ReauthenticationError();
  }

  if (response.status === 401 && !retriedAuth) {
    const error = await response.clone().json().catch(()=>({}));
    if (error.auth_mode === 'cloudflare') {
      showAdminLogin();
      throw new ReauthenticationError();
    }
    const supplied = window.prompt('這是管理員工作台，請輸入存取碼：');
    if (supplied) {
      sessionStorage.setItem('travelDeskAdminToken', supplied);
      return api(path, opts, true);
    }
  }

  if (!response.ok) {
    const raw = await response.text();
    try {
      const parsed = JSON.parse(raw);
      throw new Error(parsed.detail || raw);
    } catch (error) { if (error instanceof ReauthenticationError) return;
      if (error instanceof SyntaxError) throw new Error(raw);
      throw error;
    }
  }
  return response.json();
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function jsArg(value) {
  // Safe inside single-quoted inline handlers. Browser/model output is untrusted.
  return JSON.stringify(String(value ?? ''))
    .replace(/&/g, '\\u0026')
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/'/g, '\\u0027');
}

function fmtAmount(currency, amount) {
  if (amount === null || amount === undefined) return '未取得';
  return `${esc(currency || '')} ${Number(amount).toLocaleString()}`;
}

function openModal(title, html) {
  document.getElementById('modalTitle').textContent = title;
  document.getElementById('modalBody').innerHTML = html;
  modal.showModal();
}

async function health() {
  const session = await api('/api/auth/session');
  authMode = session.mode;
  if (authMode === 'cloudflare') {sessionStorage.removeItem('travelDeskAdminToken');sessionStorage.removeItem('travelDeskToken');}
  const state = await api('/health');
  const mode = state.openclaw_enabled ? '自動查詢已設定' : '網頁工作模式';
  document.getElementById('health').textContent = mode;
}

async function loadAirlines() {
  const data = await api('/api/airlines');
  airlineRegistry = data.airlines || [];
}

async function loadHotelNetworks() {
  const data = await api('/api/hotels/networks');
  hotelNetworks = data.networks || [];
}

async function loadCases() {
  const rows = await api('/api/cases');
  document.getElementById('caseList').innerHTML = rows.length ? rows.map(c => `
    <div class="case">
      <h3>${esc(c.customer_name)} · ${esc(c.destination || '目的地未定')}</h3>
      <div class="meta">${esc(c.depart_date || '日期未定')} → ${esc(c.return_date || '未定')} · ${c.adults + c.children} 人 · ${esc(c.status)}</div>
      <p>${esc(c.notes || '')}</p>
      <button onclick='caseDetail(${jsArg(c.id)})' >打開案件</button>
    </div>`).join('') : '<div class="muted">還沒有案件。</div>';
}

async function caseDetail(id) {
  const [trip, runs, hotelRuns] = await Promise.all([
    api('/api/cases/' + id),
    api('/api/browser/runs?case_id=' + encodeURIComponent(id)),
    api('/api/browser/hotel-runs?case_id=' + encodeURIComponent(id)),
  ]);
  const runCards = (runs || []).slice(0, 5).map(run => `
    <div class="task-card">
      <b>${esc(run.request.origin)} → ${esc(run.request.destination)}</b>
      <div class="meta">${esc(run.request.depart_date)}～${esc(run.request.return_date || '單程')} · ${esc(run.status)} · ${run.task_ids.length} 家航空</div>
      <button onclick='showSearchRun(${jsArg(run.id)})' >繼續這次查票</button>
    </div>`).join('') || '<p class="muted">這個案件還沒有官網查票紀錄。</p>';
  const hotelCards = (hotelRuns || []).slice(0, 5).map(run => `
    <div class="task-card">
      <b>${esc(run.request.hotel_name)}</b>
      <div class="meta">${esc(run.request.checkin_date)}～${esc(run.request.checkout_date)} · ${esc(run.status)} · ${run.request.rooms} 房</div>
      <button onclick='showHotelRun(${jsArg(run.id)})' >繼續這次查房</button>
    </div>`).join('') || '<p class="muted">這個案件還沒有官網查房紀錄。</p>';
  openModal(`${trip.customer_name} · ${trip.destination || '旅行'}`, `
    <div class="case-summary">
      <div><b>日期</b><span>${esc(trip.depart_date || '未定')} → ${esc(trip.return_date || '未定')}</span></div>
      <div><b>人數</b><span>${trip.adults + trip.children} 人</span></div>
      <div><b>狀態</b><span>${esc(trip.status)}</span></div>
    </div>
    <div class="task-actions">
      <button class="primary" onclick='openOfficialFlightSearch(${jsArg(id)},${jsArg(trip.origin || 'TPE')},"",${jsArg(trip.depart_date || '')},${jsArg(trip.return_date || '')},${trip.adults},${trip.children})' >✈️ 官方航空查票</button>
      <button onclick='openOfficialHotelSearch(${jsArg(id)},"", "", ${jsArg(trip.depart_date || '')}, ${jsArg(trip.return_date || '')}, 1, ${trip.adults}, [])' >🏨 官方飯店查房</button>
    </div>
    <h3>查票紀錄</h3>${runCards}
    <h3>查房紀錄</h3>${hotelCards}`);
}

async function loadRadar() {
  const rows = await api('/api/radar');
  document.getElementById('radarList').innerHTML = rows.length ? rows.map(item => `
    <div class="item">
      <span class="severity ${item.severity}">● ${esc(item.severity)}</span>
      <b>${esc(item.title)}</b>
      <div>${esc(item.detail)}</div>
    </div>`).join('') : '目前沒有急件。';
}

async function startGuided() {
  const answer = await api(`/api/guided/${sessionId}/start`, {method: 'POST'});
  renderGuided(answer);
  document.getElementById('guidedInput').focus();
}

function renderGuided(answer) {
  document.getElementById('guidedText').textContent = answer.text;
  document.getElementById('guidedOptions').innerHTML = (answer.options || []).map(option =>
    `<button onclick='chooseGuided(${jsArg(option)})'>${esc(option)}</button>`
  ).join('');
  if (answer.case_id) Promise.all([loadCases(), loadRadar()]);
}

async function chooseGuided(text) {
  document.getElementById('guidedInput').value = text;
  await sendGuided();
}

async function sendGuided() {
  const input = document.getElementById('guidedInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  const answer = await api(`/api/guided/${sessionId}/reply`, {
    method: 'POST', body: JSON.stringify({text}),
  });
  renderGuided(answer);
}

async function showDemo(kind) {
  const data = await api(kind === 'flights' ? '/api/demo/flights' : '/api/demo/hotels');
  openModal(`${kind === 'flights' ? '機票' : '飯店'} Demo shortlist`, `
    <p><b>⚠ ${esc(data.warning)}</b></p>
    ${(data.results || []).map((result, index) => `
      <div class="result">
        <h3>${index + 1}. ${esc(result.option.airline || result.option.name)}</h3>
        <div class="score">推薦分數 ${result.score}</div>
        <div>${esc((result.reasons || []).join(' · '))}</div>
        <pre>${esc(JSON.stringify(result.option, null, 2))}</pre>
      </div>`).join('')}`);
}

async function openAgent() {
  openModal('旅行助理', `
    <div class="compose"><input id="agentInput" placeholder="例如：客人嫌東京行程太趕，怎麼回？"><button onclick="askAgent()">問</button></div>
    <div id="agentOut" class="assistant" style="margin-top:12px">這裡會透過 OpenClaw Gateway；未啟用時會安全降級。</div>`);
}

async function askAgent() {
  const message = document.getElementById('agentInput').value;
  document.getElementById('agentOut').textContent = '處理中…';
  const result = await api('/api/agent/ask', {
    method: 'POST', body: JSON.stringify({message, session_user: sessionId}),
  });
  document.getElementById('agentOut').textContent = result.text;
}

async function openOfficialFlightSearch(caseId = '', origin = 'TPE', destination = '', depart = '', ret = '', adults = 1, children = 0) {
  if (!airlineRegistry.length) await loadAirlines();
  const airlines = airlineRegistry.map(airline => `
    <label class="airline-choice">
      <input type="checkbox" name="airline" value="${airline.code}" checked>
      <span>${airline.code} · ${esc(airline.name_zh)}</span>
    </label>`).join('');
  openModal('✈️ 官方航空查票', `
    <p class="ok-note">建立一筆可恢復的 Search Run，再依序查華航、國泰、星宇、華信、阿聯酋、ANA 官方網站。只搜尋到價格與條件，付款與開票不自動。</p>
    <div class="form-grid">
      <div class="field"><label>行程</label><select id="fsTripType" onchange="toggleReturnDate()"><option value="round_trip">來回</option><option value="one_way">單程</option></select></div>
      <div class="field"><label>艙等</label><select id="fsCabin"><option value="economy">經濟艙</option><option value="premium_economy">豪華經濟艙</option><option value="business">商務艙</option><option value="first">頭等艙</option></select></div>
      <div class="field"><label>出發機場 IATA</label><input id="fsOrigin" value="${esc(origin || 'TPE')}" maxlength="3"></div>
      <div class="field"><label>目的地機場 IATA</label><input id="fsDestination" value="${esc(destination)}" placeholder="NRT" maxlength="3"></div>
      <div class="field"><label>出發日</label><input id="fsDepart" type="date" value="${esc(depart)}"></div>
      <div class="field" id="fsReturnField"><label>回程日</label><input id="fsReturn" type="date" value="${esc(ret)}"></div>
      <div class="field"><label>成人</label><input id="fsAdults" type="number" min="1" max="20" value="${adults}"></div>
      <div class="field"><label>兒童</label><input id="fsChildren" type="number" min="0" max="20" value="${children}"></div>
      <div class="field"><label>嬰兒（不佔位 POC）</label><input id="fsInfants" type="number" min="0" max="20" value="0"></div>
      <div class="field"><label>總預算 TWD（可空白）</label><input id="fsBudget" type="number" min="0" step="100" placeholder="例如 50000"></div>
      <div class="field full"><label>航空公司</label><div class="airline-picker">${airlines}</div></div>
      <div class="field full"><label class="inline-check"><input id="fsNonstop" type="checkbox"> 直飛優先</label></div>
      <div class="field full"><label>偏好 / 備註</label><textarea id="fsNotes" rows="2" placeholder="例如：早去晚回、一定要托運行李"></textarea></div>
    </div>
    <input id="fsCaseId" type="hidden" value="${esc(caseId)}">
    <p><button class="primary" onclick="submitOfficialFlightSearch()">建立官網搜尋</button></p>
    <div id="flightTaskOut"></div>`);
}

function toggleReturnDate() {
  const oneWay = document.getElementById('fsTripType')?.value === 'one_way';
  const field = document.getElementById('fsReturnField');
  const input = document.getElementById('fsReturn');
  if (field) field.style.display = oneWay ? 'none' : '';
  if (input) input.required = !oneWay;
}

async function submitOfficialFlightSearch() {
  const output = document.getElementById('flightTaskOut');
  const codes = [...document.querySelectorAll('input[name="airline"]:checked')].map(node => node.value);
  const payload = {
    case_id: document.getElementById('fsCaseId').value || null,
    airline_codes: codes,
    origin: document.getElementById('fsOrigin').value.trim().toUpperCase(),
    destination: document.getElementById('fsDestination').value.trim().toUpperCase(),
    depart_date: document.getElementById('fsDepart').value,
    return_date: document.getElementById('fsTripType').value === 'one_way' ? null : document.getElementById('fsReturn').value,
    trip_type: document.getElementById('fsTripType').value,
    adults: Number(document.getElementById('fsAdults').value),
    children: Number(document.getElementById('fsChildren').value),
    infants: Number(document.getElementById('fsInfants').value),
    cabin: document.getElementById('fsCabin').value,
    nonstop_preferred: document.getElementById('fsNonstop').checked,
    max_total_twd: document.getElementById('fsBudget').value ? Number(document.getElementById('fsBudget').value) : null,
    notes: document.getElementById('fsNotes').value,
  };
  const missingReturn = payload.trip_type === 'round_trip' && !payload.return_date;
  if (!payload.destination || !payload.depart_date || missingReturn || !codes.length) {
    output.innerHTML = '<p class="danger-note">請填目的地、必要日期，並至少選一家航空公司。</p>';
    return;
  }
  output.innerHTML = '<p class="muted">建立 Search Run 中…</p>';
  try {
    const plan = await api('/api/browser/flight-search', {method: 'POST', body: JSON.stringify(payload)});
    output.innerHTML = renderTaskPlan(plan);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    output.innerHTML = `<p class="danger-note">${esc(error.message)}</p>`;
  }
}

function renderTaskPlan(plan) {
  let html = '';
  lastFlightTaskIds = (plan.tasks || []).map(task => task.id);
  lastFlightRunId = plan.run?.id || null;
  if (plan.run) {
    html += `<div class="run-banner"><b>Search Run</b><span>${esc(plan.run.id)}</span><span class="pill">${esc(plan.run.status)}</span></div>`;
  }
  if ((plan.manual_handoffs || []).length) {
    html += `<div class="manual task-card"><b>需要人工處理</b>${plan.manual_handoffs.map(item => `<div>${esc(item.airline_code)} ${esc(item.airline_name)}：${esc(item.reason)}</div>`).join('')}</div>`;
  }
  if ((plan.unsupported_airlines || []).length) {
    html += `<div class="danger-note">尚未支援：${esc(plan.unsupported_airlines.join(', '))}</div>`;
  }
  if (lastFlightTaskIds.length) {
    html += `<div class="task-actions"><button class="primary" onclick="runAllFlightTasks()">依序執行全部</button> <button onclick="compareFlightTasks()">比較已完成結果</button></div>`;
  }
  html += (plan.tasks || []).map(task => taskCard(task)).join('');
  return html || '<p class="muted">沒有建立任何 task。</p>';
}

function taskCard(task) {
  return `<div class="task-card" id="task-${task.id}">
    <b>${esc(task.provider_code || task.kind)} · ${esc(task.kind)}</b>
    <div class="task-status">${esc(task.status)} · ${esc(task.review_state)}</div>
    <div class="meta">${esc(task.source_url)}<br>${esc(task.id)}</div>
    <p><button onclick='runBrowserTask(${jsArg(task.id)})' >用 OpenClaw 執行</button> <button onclick='showBrowserTask(${jsArg(task.id)})' >查看</button></p>
  </div>`;
}

async function runAllFlightTasks() {
  if (!lastFlightTaskIds.length) return;
  const output = document.getElementById('flightTaskOut');
  output?.insertAdjacentHTML('afterbegin', '<p id="batchProgress" class="muted">正在依序操作官網；共用 browser profile，所以刻意不平行跑。</p>');
  try {
    const path = lastFlightRunId ? `/api/browser/runs/${lastFlightRunId}/run` : '/api/browser/flight-search/run-batch';
    const options = lastFlightRunId ? {method: 'POST'} : {method: 'POST', body: JSON.stringify({task_ids: lastFlightTaskIds})};
    const result = await api(path, options);
    (result.results || []).forEach(task => {
      const element = document.getElementById('task-' + task.id);
      if (element?.querySelector('.task-status')) element.querySelector('.task-status').textContent = `${task.status || 'unknown'} · ${task.review_state || ''}`;
    });
    renderFlightComparison(result.comparison);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    const progress = document.getElementById('batchProgress');
    if (progress) progress.outerHTML = `<p class="danger-note">${esc(error.message)}</p>`;
  }
}

async function compareFlightTasks() {
  if (!lastFlightTaskIds.length) return;
  const comparison = await api('/api/browser/flight-search/compare', {
    method: 'POST', body: JSON.stringify({task_ids: lastFlightTaskIds}),
  });
  renderFlightComparison(comparison);
}

function renderFlightComparison(comparison) {
  const groups = comparison.currency_groups || [];
  let html = `<p class="danger-note">${esc(comparison.warning || '')}</p>`;
  if (comparison.mixed_currency) html += '<p class="manual">⚠️ 不同幣別分開排序，不偷偷換匯。</p>';
  if (!groups.length) html += '<p class="muted">還沒有通過 schema、航線日期與官方網域驗證的結果。</p>';
  for (const group of groups) {
    html += `<h3>${esc(group.currency)} 比較</h3>`;
    html += (group.ranked || []).map((row, index) => {
      const option = row.option;
      const segments = (option.segments || []).map(segment => `${esc(segment.flight_number)} ${esc(segment.origin)}→${esc(segment.destination)}`).join(' / ');
      return `<div class="result option-card">
        <div class="rank">${index + 1}</div>
        <h3>${esc(row.airline_code)} · ${esc(row.airline_name)}</h3>
        <div class="score">比較分數 ${esc(row.score)} · ${fmtAmount(group.currency, option.total_amount)}</div>
        <div>${esc((row.reasons || []).join(' · '))}</div>
        <div class="meta">${segments}<br>票價：${esc(option.fare_family || '未確認')} · 行李：${esc(option.checked_baggage)}<br>查詢時間 ${esc(row.observed_at)}</div>
        <p><button class="primary" onclick='selectAndRevalidate(${jsArg(row.task_id)},${jsArg(option.option_id)})' >選這個並重新驗價</button></p>
      </div>`;
    }).join('');
  }
  const taskStates = (comparison.task_states || []).filter(item => item.state !== 'ready');
  if (taskStates.length) html += `<details><summary>尚未納入比較的任務 (${taskStates.length})</summary><pre>${esc(JSON.stringify(taskStates, null, 2))}</pre></details>`;
  openModal('✈️ 官方航空比較', html);
}

async function selectAndRevalidate(searchTaskId, optionId) {
  try {
    const task = await api('/api/browser/revalidate', {
      method: 'POST', body: JSON.stringify({search_task_id: searchTaskId, option_id: optionId}),
    });
    openModal('重新驗價已建立', `
      <p class="ok-note">系統已鎖定原航班組合，重新進官方網站查相同航班、日期、票價產品與條件。</p>
      ${taskCard(task)}
      <p><button class="primary" onclick='runRevalidation(${jsArg(task.id)})' >現在執行重新驗價</button></p>`);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('無法重新驗價', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

async function runRevalidation(taskId) {
  openModal('重新驗價', '<p class="muted">正在重新進入官方網站確認…</p>');
  try {
    await api(`/api/browser/tasks/${taskId}/run`, {method: 'POST'});
    await showRevalidation(taskId);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('重新驗價需要處理', `<p class="danger-note">${esc(error.message)}</p><p><button onclick='showBrowserTask(${jsArg(taskId)})' >查看任務</button></p>`);
  }
}

async function showRevalidation(taskId) {
  const summary = await api(`/api/browser/revalidate/${taskId}/summary`);
  const changed = summary.requires_human_acceptance;
  const blockers = (summary.blockers || []).map(value => `<li>${esc(value)}</li>`).join('');
  const warnings = (summary.warnings || []).map(value => `<li>${esc(value)}</li>`).join('');
  openModal('重新驗價結果', `
    <div class="summary-hero ${summary.status === 'unchanged' ? 'good' : 'attention'}">
      <b>${esc(summary.airline_code)} · ${esc(summary.status)}</b>
      <span>${fmtAmount(summary.currency, summary.original_amount)} → ${fmtAmount(summary.currency, summary.current_amount)}</span>
      <span>差額 ${summary.delta_amount == null ? '未取得' : Number(summary.delta_amount).toLocaleString()}</span>
    </div>
    ${blockers ? `<h3>阻擋項目</h3><ul class="blocked-list">${blockers}</ul>` : ''}
    ${warnings ? `<h3>需要注意</h3><ul>${warnings}</ul>` : ''}
    ${changed ? `<label class="accept-box"><input id="acceptPriceChange" type="checkbox"> 我已看過並接受目前的價格／條件變動</label>` : ''}
    <p><button class="primary" onclick='runPreflight(${jsArg(taskId)}, ${changed ? 'true' : 'false'})' >建立付款前檢查</button></p>`);
}

async function runPreflight(taskId, acceptanceRequired) {
  const accepted = acceptanceRequired ? Boolean(document.getElementById('acceptPriceChange')?.checked) : false;
  try {
    const result = await api('/api/booking/preflight', {
      method: 'POST', body: JSON.stringify({revalidation_task_id: taskId, accept_price_change: accepted}),
    });
    renderPreflight(result);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('付款前檢查失敗', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

function renderPreflight(result) {
  const checklist = (result.checklist || []).map(item => `
    <div class="check-row ${esc(item.status)}">
      <span class="check-icon">${item.status === 'ok' ? '✓' : item.status === 'warning' ? '!' : '×'}</span>
      <div><b>${esc(item.label)}</b><div>${esc(item.detail)}</div></div>
    </div>`).join('');
  const blockers = (result.blockers || []).map(value => `<li>${esc(value)}</li>`).join('');
  const warnings = (result.warnings || []).map(value => `<li>${esc(value)}</li>`).join('');
  openModal(result.ready ? '可以交給媽媽完成付款' : '還不能進付款', `
    <p class="${result.ready ? 'ok-note' : 'danger-note'}">${esc(result.next_action)}</p>
    <div class="checklist">${checklist}</div>
    ${blockers ? `<h3>必須先處理</h3><ul class="blocked-list">${blockers}</ul>` : ''}
    ${warnings ? `<h3>付款前再看一次</h3><ul>${warnings}</ul>` : ''}
    <p class="manual">Travel Desk 不會看到信用卡/CVV，也不會按下最終付款、開票或繞過 OTP/3DS/CAPTCHA。</p>`);
}


function hotelNetworkOptions() {
  const options = hotelNetworks.map(network =>
    `<option value="${esc(network.official_home)}" data-name="${esc(network.name)}">${esc(network.name)}</option>`
  ).join('');
  return `<option value="">自訂／獨立飯店官網</option>${options}`;
}

async function openOfficialHotelSearch(caseId = '', hotelName = '', officialUrl = '', checkin = '', checkout = '', rooms = 1, adults = 2, childrenAges = []) {
  if (!hotelNetworks.length) await loadHotelNetworks();
  const childText = Array.isArray(childrenAges) ? childrenAges.join(',') : '';
  openModal('🏨 官方飯店查房', `
    <p class="ok-note">先選已知飯店官網，再讓 Browser Copilot 讀取真正的房型、總住宿價、稅費、取消規則、早餐與付款時點。未知獨立飯店必須先由人類確認 official site；OTA 不可冒充官網。</p>
    <div class="form-grid">
      <div class="field full"><label>常用飯店集團（可選）</label><select id="hsNetwork" onchange="applyHotelNetwork()">${hotelNetworkOptions()}</select></div>
      <div class="field full"><label>飯店名稱</label><input id="hsName" value="${esc(hotelName)}" placeholder="例如 Hilton Tokyo"></div>
      <div class="field full"><label>官方網站 URL</label><input id="hsUrl" value="${esc(officialUrl)}" placeholder="https://www.hilton.com/..."></div>
      <div class="field"><label>入住日</label><input id="hsCheckin" type="date" value="${esc(checkin)}"></div>
      <div class="field"><label>退房日</label><input id="hsCheckout" type="date" value="${esc(checkout)}"></div>
      <div class="field"><label>房間數</label><input id="hsRooms" type="number" min="1" max="8" value="${Number(rooms) || 1}"></div>
      <div class="field"><label>成人</label><input id="hsAdults" type="number" min="1" max="24" value="${Number(adults) || 2}"></div>
      <div class="field full"><label>兒童年齡（逗號分隔，可空白）</label><input id="hsChildren" value="${esc(childText)}" placeholder="例如 6,10"></div>
      <div class="field"><label>希望顯示幣別</label><input id="hsCurrency" maxlength="3" value="TWD"></div>
      <div class="field"><label>總住宿預算 TWD（可空白）</label><input id="hsBudget" type="number" min="0" step="100" placeholder="例如 30000"></div>
      <div class="field"><label>最低星級（參考）</label><select id="hsStars"><option value="">不限制</option><option value="3">3 星</option><option value="4">4 星</option><option value="5">5 星</option></select></div>
      <div class="field"><label>偏好</label><label class="inline-check"><input id="hsBreakfast" type="checkbox"> 需要早餐</label><label class="inline-check"><input id="hsFreeCancel" type="checkbox" checked> 優先可免費取消</label></div>
      <div class="field full"><label>備註</label><textarea id="hsNotes" rows="2" placeholder="例如：近車站、不要吸菸房、兩張單人床優先"></textarea></div>
    </div>
    <input id="hsCaseId" type="hidden" value="${esc(caseId)}">
    <p><button class="primary" onclick="submitOfficialHotelSearch()">建立官方查房</button></p>
    <div id="hotelTaskOut"></div>`);

  if (officialUrl) {
    const network = hotelNetworks.find(row => officialUrl.includes(new URL(row.official_home).hostname.replace(/^www\./, '')));
    if (network) document.getElementById('hsNetwork').value = network.official_home;
  }
}

function applyHotelNetwork() {
  const select = document.getElementById('hsNetwork');
  const url = select?.value || '';
  if (!url) return;
  document.getElementById('hsUrl').value = url;
  const option = select.options[select.selectedIndex];
  const currentName = document.getElementById('hsName').value.trim();
  if (!currentName && option?.dataset?.name) document.getElementById('hsName').value = option.dataset.name;
}

function parseChildAges(raw) {
  if (!raw.trim()) return [];
  const values = raw.split(',').map(value => Number(value.trim())).filter(value => Number.isFinite(value));
  if (values.some(age => age < 0 || age > 17)) throw new Error('兒童年齡必須介於 0–17 歲。');
  return values;
}

function collectHotelSearchPayload() {
  return {
    case_id: document.getElementById('hsCaseId').value || null,
    hotel_name: document.getElementById('hsName').value.trim(),
    official_url: document.getElementById('hsUrl').value.trim(),
    checkin_date: document.getElementById('hsCheckin').value,
    checkout_date: document.getElementById('hsCheckout').value,
    rooms: Number(document.getElementById('hsRooms').value),
    adults: Number(document.getElementById('hsAdults').value),
    children_ages: parseChildAges(document.getElementById('hsChildren').value),
    currency_preference: document.getElementById('hsCurrency').value.trim().toUpperCase() || 'TWD',
    max_total_twd: document.getElementById('hsBudget').value ? Number(document.getElementById('hsBudget').value) : null,
    min_stars: document.getElementById('hsStars').value ? Number(document.getElementById('hsStars').value) : null,
    breakfast_required: document.getElementById('hsBreakfast').checked,
    free_cancellation_preferred: document.getElementById('hsFreeCancel').checked,
    notes: document.getElementById('hsNotes').value,
  };
}

async function submitOfficialHotelSearch() {
  const output = document.getElementById('hotelTaskOut');
  try {
    const payload = collectHotelSearchPayload();
    lastHotelSearchDraft = payload;
    if (!payload.hotel_name || !payload.official_url || !payload.checkin_date || !payload.checkout_date) {
      throw new Error('請填飯店名稱、官方網站、入住日與退房日。');
    }
    output.innerHTML = '<p class="muted">建立 Hotel Search Run 中…</p>';
    const plan = await api('/api/browser/hotel-search', {method: 'POST', body: JSON.stringify(payload)});
    output.innerHTML = renderHotelTaskPlan(plan);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    const canAttest = String(error.message).includes('尚未信任') && lastHotelSearchDraft?.official_url;
    output.innerHTML = `<p class="danger-note">${esc(error.message)}</p>${canAttest ? `
      <div class="attestation-card">
        <b>這是獨立飯店嗎？</b>
        <p>只有你已經人工確認「網址確實是飯店自己營運的官方網站」時才核准。Booking.com、Agoda、Expedia 等 OTA 不能核准成 official site。</p>
        <label class="accept-box"><input id="hsHumanVerified" type="checkbox"> 我已人工確認這是 ${esc(lastHotelSearchDraft.hotel_name)} 的官方網站</label>
        <div class="field"><label>查證來源／備註（建議填）</label><input id="hsEvidence" placeholder="例如飯店 Google Business / 官方社群連回此網域"></div>
        <p><button onclick="approveHotelSiteAndRetry()">核准這個網域並重試</button></p>
      </div>` : ''}`;
  }
}

async function approveHotelSiteAndRetry() {
  if (!document.getElementById('hsHumanVerified')?.checked) {
    alert('請先人工確認官方網站。');
    return;
  }
  const payload = lastHotelSearchDraft;
  if (!payload) return;
  const evidence = document.getElementById('hsEvidence')?.value.trim() || null;
  try {
    await api('/api/hotels/site-grants', {
      method: 'POST',
      body: JSON.stringify({
        hotel_name: payload.hotel_name,
        official_url: payload.official_url,
        trust_source: 'human',
        evidence_url: evidence && /^https:\/\//i.test(evidence) ? evidence : null,
        notes: evidence && !/^https:\/\//i.test(evidence) ? evidence : 'Human verified before browser automation.',
      }),
    });
    const plan = await api('/api/browser/hotel-search', {method: 'POST', body: JSON.stringify(payload)});
    const output = document.getElementById('hotelTaskOut');
    if (output) output.innerHTML = `<p class="ok-note">已保存 human-approved site grant。</p>${renderHotelTaskPlan(plan)}`;
  } catch (error) { if (error instanceof ReauthenticationError) return;
    const output = document.getElementById('hotelTaskOut');
    if (output) output.innerHTML = `<p class="danger-note">${esc(error.message)}</p>`;
  }
}

function renderHotelTaskPlan(plan) {
  lastHotelRunId = plan.run?.id || null;
  lastHotelTaskIds = plan.task ? [plan.task.id] : [];
  return `
    <div class="run-banner"><b>Hotel Search Run</b><span>${esc(plan.run?.id || '')}</span><span class="pill">${esc(plan.run?.status || '')}</span></div>
    <div class="task-actions"><button class="primary" onclick="runHotelTasks()">用 OpenClaw 查房</button> <button onclick="compareHotelTasks()">比較已完成房型</button></div>
    ${plan.task ? taskCard(plan.task) : '<p class="muted">沒有建立 task。</p>'}`;
}

async function runHotelTasks() {
  if (!lastHotelRunId) return;
  openModal('🏨 官方飯店查房', '<p class="muted">正在官方飯店網站查房。若遇到登入、CAPTCHA、付款或不可信跳轉會停止。</p>');
  try {
    const result = await api(`/api/browser/hotel-runs/${lastHotelRunId}/run`, {method: 'POST'});
    renderHotelComparison(result.comparison);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('查房需要處理', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

async function compareHotelTasks() {
  if (!lastHotelTaskIds.length) return;
  const comparison = await api('/api/browser/hotel-search/compare', {
    method: 'POST', body: JSON.stringify({task_ids: lastHotelTaskIds}),
  });
  renderHotelComparison(comparison);
}

function renderHotelComparison(comparison) {
  const groups = comparison.currency_groups || [];
  let html = `<p class="danger-note">${esc(comparison.warning || '')}</p>`;
  if (comparison.mixed_currency) html += '<p class="manual">⚠️ 不同幣別分開比較，不偷偷換匯。</p>';
  if (!groups.length) html += '<p class="muted">還沒有通過官網來源與住宿條件驗證的房型。</p>';
  for (const group of groups) {
    html += `<h3>${esc(group.currency)} 房型比較</h3>`;
    html += (group.ranked || []).map((row, index) => {
      const option = row.option;
      const cancellation = option.refundable === true
        ? `可取消 · ${esc(option.cancellation_deadline_local || '期限未確認')}`
        : option.refundable === false ? '不可退款/取消' : '取消規則未確認';
      const breakfast = option.breakfast_included === true ? '含早餐' : option.breakfast_included === false ? '不含早餐' : '早餐未確認';
      return `<div class="result option-card">
        <div class="rank">${index + 1}</div>
        <h3>${esc(row.hotel_name)}</h3>
        <div class="score">比較分數 ${esc(row.score)} · ${fmtAmount(group.currency, option.total_amount)}</div>
        <div>${esc((row.reasons || []).join(' · '))}</div>
        <div class="hotel-facts">
          <span>🛏 ${esc(option.room_name || '房型未命名')}</span>
          <span>${esc(option.bed_type || '床型未確認')}</span>
          <span>${esc(option.rate_name || 'Rate 未命名')}</span>
          <span>${cancellation}</span>
          <span>${breakfast}</span>
          <span>付款：${esc(option.payment_timing || 'unknown')}</span>
        </div>
        <div class="meta">Base ${fmtAmount(group.currency, option.base_amount)} · Tax/fees ${fmtAmount(group.currency, option.taxes_and_fees)} · Property fee ${fmtAmount(group.currency, option.mandatory_property_fees)}<br>查詢時間 ${esc(row.observed_at)}</div>
        <p><button class="primary" onclick='selectHotelAndRevalidate(${jsArg(row.task_id)},${jsArg(option.option_id)})'>選這個並重新驗價</button></p>
      </div>`;
    }).join('');
  }
  const states = (comparison.task_states || []).filter(item => item.state !== 'ready');
  if (states.length) html += `<details><summary>尚未納入比較的任務 (${states.length})</summary><pre>${esc(JSON.stringify(states, null, 2))}</pre></details>`;
  openModal('🏨 官方飯店房型比較', html);
}

async function selectHotelAndRevalidate(searchTaskId, optionId) {
  try {
    const task = await api('/api/browser/hotel-revalidate', {
      method: 'POST', body: JSON.stringify({search_task_id: searchTaskId, option_id: optionId}),
    });
    openModal('飯店重新驗價已建立', `
      <p class="ok-note">已鎖定同一飯店、房型、床型與 rate plan。下一步只重新確認最新總價、稅費、早餐與取消條件。</p>
      ${taskCard(task)}
      <p><button class="primary" onclick='runHotelRevalidation(${jsArg(task.id)})'>現在重新驗價</button></p>`);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('無法建立飯店重新驗價', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

async function runHotelRevalidation(taskId) {
  openModal('飯店重新驗價', '<p class="muted">正在回到官方網站確認同一房型與 rate plan…</p>');
  try {
    await api(`/api/browser/tasks/${taskId}/run`, {method: 'POST'});
    await showHotelRevalidation(taskId);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('飯店重新驗價需要處理', `<p class="danger-note">${esc(error.message)}</p><p><button onclick='showBrowserTask(${jsArg(taskId)})'>查看任務</button></p>`);
  }
}

async function showHotelRevalidation(taskId) {
  const summary = await api(`/api/browser/hotel-revalidate/${taskId}/summary`);
  const changed = summary.requires_human_acceptance;
  const blockers = (summary.blockers || []).map(value => `<li>${esc(value)}</li>`).join('');
  const warnings = (summary.warnings || []).map(value => `<li>${esc(value)}</li>`).join('');
  openModal('飯店重新驗價結果', `
    <div class="summary-hero ${summary.status === 'unchanged' ? 'good' : 'attention'}">
      <b>${esc(summary.hotel_name)} · ${esc(summary.status)}</b>
      <span>${fmtAmount(summary.currency, summary.original_amount)} → ${fmtAmount(summary.currency, summary.current_amount)}</span>
      <span>差額 ${summary.delta_amount == null ? '未取得' : Number(summary.delta_amount).toLocaleString()}</span>
    </div>
    ${blockers ? `<h3>阻擋項目</h3><ul class="blocked-list">${blockers}</ul>` : ''}
    ${warnings ? `<h3>需要注意</h3><ul>${warnings}</ul>` : ''}
    ${changed ? '<label class="accept-box"><input id="acceptHotelChange" type="checkbox"> 我已看過並接受目前的住宿價格／條件變動</label>' : ''}
    <p><button class="primary" onclick='runHotelPreflight(${jsArg(taskId)}, ${changed ? 'true' : 'false'})'>建立訂房付款前檢查</button></p>`);
}

async function runHotelPreflight(taskId, acceptanceRequired) {
  const accepted = acceptanceRequired ? Boolean(document.getElementById('acceptHotelChange')?.checked) : false;
  try {
    const result = await api('/api/hotel-booking/preflight', {
      method: 'POST', body: JSON.stringify({revalidation_task_id: taskId, accept_price_or_terms_change: accepted}),
    });
    renderHotelPreflight(result);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    openModal('訂房付款前檢查失敗', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

function renderHotelPreflight(result) {
  const checklist = (result.checklist || []).map(item => `
    <div class="check-row ${esc(item.status)}">
      <span class="check-icon">${item.status === 'ok' ? '✓' : item.status === 'warning' ? '!' : '×'}</span>
      <div><b>${esc(item.label)}</b><div>${esc(item.detail)}</div></div>
    </div>`).join('');
  const blockers = (result.blockers || []).map(value => `<li>${esc(value)}</li>`).join('');
  const warnings = (result.warnings || []).map(value => `<li>${esc(value)}</li>`).join('');
  openModal(result.ready ? '可以交給媽媽完成飯店付款' : '還不能進飯店付款', `
    <p class="${result.ready ? 'ok-note' : 'danger-note'}">${esc(result.next_action)}</p>
    <div class="checklist">${checklist}</div>
    ${blockers ? `<h3>必須先處理</h3><ul class="blocked-list">${blockers}</ul>` : ''}
    ${warnings ? `<h3>付款前再看一次</h3><ul>${warnings}</ul>` : ''}
    <p class="manual">Travel Desk 不輸入信用卡/CVV、不處理 OTP/3DS，也不按下飯店官網的最終訂房提交。</p>`);
}


async function showHotelTrust() {
  const [networkData, grants] = await Promise.all([
    api('/api/hotels/networks'),
    api('/api/hotels/site-grants'),
  ]);
  const networkRows = (networkData.networks || []).map(row => `
    <div class="trust-row builtin">
      <div><b>${esc(row.name)}</b><div class="meta">${esc((row.allowed_domains || []).join(', '))}</div></div>
      <span class="pill">內建</span>
    </div>`).join('');
  const grantRows = (grants || []).map(row => `
    <div class="trust-row ${esc(row.status)}">
      <div><b>${esc(row.hotel_name)}</b><div class="meta">${esc(row.domain)} · ${esc(row.trust_source)} · ${esc(row.status)}</div><small>${esc(row.notes || '')}</small></div>
      ${row.status === 'approved' ? `<button onclick='revokeHotelGrant(${jsArg(row.id)})'>撤銷</button>` : '<span class="pill warn">已撤銷</span>'}
    </div>`).join('') || '<p class="muted">尚未核准任何獨立飯店官網。</p>';
  openModal('🔐 飯店官網信任', `
    <p class="ok-note">內建飯店集團只允許固定 official domains；獨立飯店必須經人工 attestation。OTA / 搜尋平台無法被登記成 official site。</p>
    <h3>內建飯店集團</h3><div class="trust-list">${networkRows}</div>
    <h3>人工核准的獨立飯店</h3><div class="trust-list">${grantRows}</div>`);
}

async function revokeHotelGrant(grantId) {
  if (!confirm('確定撤銷這個飯店官網的 Browser 信任？之後新任務會被拒絕。')) return;
  try {
    await api(`/api/hotels/site-grants/${grantId}/revoke`, {method: 'POST'});
    await showHotelTrust();
  } catch (error) { if (error instanceof ReauthenticationError) return;
    alert(error.message);
  }
}

async function showHotelRuns() {
  const runs = await api('/api/browser/hotel-runs');
  openModal('訂房紀錄', runs.length ? runs.map(run => `
    <div class="task-card">
      <b>${esc(run.request.hotel_name)}</b>
      <div>${esc(run.request.checkin_date)}～${esc(run.request.checkout_date)} · ${run.request.rooms} 房 · ${run.request.adults} 成人</div>
      <div class="meta">${esc(run.id)} · ${esc(run.status)}</div>
      <button onclick='showHotelRun(${jsArg(run.id)})'>打開</button>
    </div>`).join('') : '<p class="muted">尚無 Hotel Search Run。</p>');
}

async function showHotelRun(runId) {
  const data = await api(`/api/browser/hotel-runs/${runId}`);
  lastHotelRunId = data.run.id;
  lastHotelTaskIds = data.run.task_ids || [];
  let html = `<div class="run-banner"><b>${esc(data.run.request.hotel_name)}</b><span>${esc(data.run.request.checkin_date)}～${esc(data.run.request.checkout_date)}</span><span class="pill">${esc(data.run.status)}</span></div>`;
  html += '<div class="task-actions"><button class="primary" onclick="runHotelTasks()">繼續執行</button> <button onclick="compareHotelTasks()">查看比較</button></div>';
  html += (data.tasks || []).map(task => taskCard(task)).join('');
  openModal('Hotel Search Run', html);
}

async function runBrowserTask(id) {
  const element = document.getElementById('task-' + id);
  if (element?.querySelector('.task-status')) element.querySelector('.task-status').textContent = 'running…';
  try {
    const task = await api(`/api/browser/tasks/${id}/run`, {method: 'POST'});
    if (element?.querySelector('.task-status')) element.querySelector('.task-status').textContent = `${task.status} · ${task.review_state}`;
    if (task.expected_schema === 'flight-revalidation-v1') await showRevalidation(id);
    else if (task.expected_schema === 'hotel-revalidation-v1') await showHotelRevalidation(id);
    else showTaskResult(task, []);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    if (element) element.insertAdjacentHTML('beforeend', `<p class="danger-note">${esc(error.message)}</p>`);
  }
}

async function showBrowserTask(id) {
  const [task, attempts] = await Promise.all([
    api(`/api/browser/tasks/${id}`),
    api(`/api/browser/tasks/${id}/attempts`),
  ]);
  showTaskResult(task, attempts);
}

function showTaskResult(task, attempts) {
  const attemptHtml = (attempts || []).map(attempt => `
    <div class="attempt-row">
      <b>#${attempt.attempt_no} · ${esc(attempt.source)}</b>
      <span>${esc(attempt.outcome)} / ${esc(attempt.result_status || '-')} · ${attempt.duration_ms ?? '-'} ms</span>
      ${(attempt.validation_errors || []).length ? `<div class="danger-note">${esc(attempt.validation_errors.join('；'))}</div>` : ''}
    </div>`).join('') || '<p class="muted">還沒有執行紀錄。</p>';
  openModal(`${task.provider_code || ''} Browser Task`, `
    <p><b>Status:</b> ${esc(task.status)} · <b>Review:</b> ${esc(task.review_state)}</p>
    <p class="danger-note">通過結構驗證仍不等於可以直接對客報價；成交前一定要重新驗價與人工核對。</p>
    <details open><summary>結果</summary><pre>${esc(JSON.stringify(task.result_json || task.result_text || {}, null, 2))}</pre></details>
    <h3>執行紀錄</h3>${attemptHtml}
    <details class="lab-tools"><summary>開發者：貼入 Browser Lab JSON</summary>
      <textarea id="ingestRaw" rows="10" placeholder="貼入 OpenClaw 回傳的 JSON"></textarea>
      <p><button onclick='ingestTaskResult(${jsArg(task.id)})' >驗證並寫入</button></p>
    </details>`);
}

async function ingestTaskResult(taskId) {
  const raw = document.getElementById('ingestRaw').value;
  try {
    await api(`/api/browser/tasks/${taskId}/ingest`, {method: 'POST', body: JSON.stringify({raw_text: raw})});
    await showBrowserTask(taskId);
  } catch (error) { if (error instanceof ReauthenticationError) return;
    alert(error.message);
  }
}

async function showBrowserQueue() {
  const rows = await api('/api/browser/tasks');
  openModal('Browser 任務佇列', rows.length ? rows.map(task => `
    <div class="task-card">
      <b>${esc(task.provider_code || task.kind)} · ${esc(task.kind)}</b>
      <div class="meta">${esc(task.id)} · ${esc(task.status)} · ${esc(task.review_state)}</div>
      <button onclick='showBrowserTask(${jsArg(task.id)})' >查看</button>
    </div>`).join('') : '<p class="muted">尚無 Browser task。</p>');
}

async function showSearchRuns() {
  const runs = await api('/api/browser/runs');
  openModal('查票紀錄', runs.length ? runs.map(run => `
    <div class="task-card">
      <b>${esc(run.request.origin)} → ${esc(run.request.destination)}</b>
      <div>${esc(run.request.depart_date)}～${esc(run.request.return_date || '單程')} · ${run.request.adults + run.request.children} 人</div>
      <div class="meta">${esc(run.id)} · ${esc(run.status)} · ${run.task_ids.length} 個搜尋任務</div>
      <button onclick='showSearchRun(${jsArg(run.id)})' >打開</button>
    </div>`).join('') : '<p class="muted">尚無 Search Run。</p>');
}

async function showSearchRun(runId) {
  const data = await api(`/api/browser/runs/${runId}`);
  lastFlightRunId = data.run.id;
  lastFlightTaskIds = data.run.task_ids || [];
  let html = `<div class="run-banner"><b>${esc(data.run.request.origin)} → ${esc(data.run.request.destination)}</b><span>${esc(data.run.status)}</span></div>`;
  html += `<div class="task-actions"><button class="primary" onclick="runAllFlightTasks()">繼續執行</button> <button onclick="compareFlightTasks()">查看比較</button></div>`;
  html += (data.tasks || []).map(task => taskCard(task)).join('');
  openModal('Search Run', html);
}

async function showBrowserLab() {
  const report = await api('/api/browser/lab/summary');
  const providers = (report.providers || []).map(row => `
    <div class="metric-card">
      <b>${esc(row.provider_label || row.airline_code)} <small>· ${esc(row.provider_type || "airline")}</small></b>
      <span>Tasks ${row.tasks_total}</span>
      <span>Attempts ${row.attempts_total}</span>
      <span>結構通過 ${row.contract_validation_rate == null ? '-' : Math.round(row.contract_validation_rate * 100) + '%'}</span>
      <span>可用結果 ${row.usable_success_rate == null ? '-' : Math.round(row.usable_success_rate * 100) + '%'}</span>
      <small>Flight search ${row.search_tasks || 0} / hotel search ${row.hotel_search_tasks || 0} · OpenClaw ${row.openclaw_attempts} · 離線貼入 ${row.lab_ingest_attempts} · 人工終止 ${row.manual_terminal_tasks} · 驗證錯誤 ${row.validation_error_attempts} · 結果狀態 ${esc(JSON.stringify(row.result_statuses || {}))}</small>
    </div>`).join('') || '<p class="muted">還沒有 Browser Lab 資料。</p>';
  openModal('Browser Lab', `
    <p class="ok-note">這裡量測每家航空官網的成功率、人工介入與 validator 問題。離線貼入結果只測 schema；真正價值要看 OpenClaw 實機 attempts。</p>
    <div class="metrics-grid">${providers}</div>
    <p class="meta">總任務 ${report.tasks_total} · 總 attempts ${report.attempts_total} · 結構通過 ${report.overall_contract_validation_rate == null ? '-' : Math.round(report.overall_contract_validation_rate * 100) + '%'} · 可用結果 ${report.overall_usable_success_rate == null ? '-' : Math.round(report.overall_usable_success_rate * 100) + '%'}</p>`);
}

async function showReadiness() {
  const report = await api('/api/system/readiness');
  const checks = (report.checks || []).map(check => `
    <div class="check-row ${esc(check.status)}">
      <span class="check-icon">${check.status === 'ok' ? '✓' : check.status === 'warning' ? '!' : '×'}</span>
      <div><b>${esc(check.label)}</b><div>${esc(check.detail)}</div><small>${esc(check.scope)}</small></div>
    </div>`).join('');
  openModal('系統準備度', `
    <div class="readiness-flags">
      <span class="pill ${report.offline_poc_ready ? '' : 'warn'}">離線 POC ${report.offline_poc_ready ? 'Ready' : 'Blocked'}</span>
      <span class="pill ${report.live_browser_lab_configured ? '' : 'warn'}">Browser Lab ${report.live_browser_lab_configured ? 'Configured' : '未完成'}</span>
      <span class="pill ${report.mom_line_pilot_configured ? '' : 'warn'}">媽媽 LINE ${report.mom_line_pilot_configured ? 'Configured' : '未完成'}</span>
    </div>
    <div class="checklist">${checks}</div>
    <p class="manual">${esc(report.disclaimer)}</p>`);
}

health().then(()=>Promise.all([loadAirlines(), loadHotelNetworks(), loadCases(), loadRadar()])).catch(error=>{if(error instanceof ReauthenticationError)return;document.getElementById('health').textContent=error.message || '暫時無法連線';});
