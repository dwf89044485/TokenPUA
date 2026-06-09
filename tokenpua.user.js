// ==UserScript==
// @name         TokenPUA - 额度看板
// @namespace    https://github.com/dwf89044485/TokenPUA
// @version      1.0.0
// @description  在 token.woa.com 页面显示额度使用进度面板
// @author       josephdeng
// @match        https://token.woa.com/*
// @match        https://token.woa.com
// @match        http://token.woa.com/*
// @match        http://token.woa.com
// @grant        GM_getValue
// @grant        GM_setValue
// @run-at       document-end
// ==/UserScript==

// ============================================================
// Section 1: Constants & Config
// ============================================================

const BASE_URL = 'https://token.woa.com';
const DASHBOARD_URL = 'https://token.woa.com/';

const REFRESH_INTERVAL_MS = 3 * 60 * 1000;
const API_PAGE_SIZE = 50;
const FULL_SCAN_MAX_PAGES = 10;
const RECORDS_CACHE_LIMIT = 200;
const RECORDS_DISPLAY_LIMIT = 45;
const STALE_AFTER_MS = 10 * 60 * 1000;

const MODEL_ALIASES = {
  'DeepSeek': 'DS',
};

const STATUS_THRESHOLDS = [
  { min: 1.3, icon: '\u{1F7E5}', text: '加速',    color: '#F44336' },
  { min: 1.1, icon: '\u{1F7E1}', text: '稍加速',  color: '#FF9800' },
  { min: 0.9, icon: '\u{1F7E2}', text: '完美',    color: '#4CAF50' },
  { min: 0.7, icon: '\u{1F7E1}', text: '可放缓',  color: '#FF9800' },
  { min: 0,   icon: '\u{1F535}', text: '省着用',  color: '#2196F3' },
];

const CACHE_KEY = 'tokenpua_cache';

// ============================================================
// Section 2: Utility Functions
// ============================================================

function fmtDate(d) {
  return d.toISOString().slice(0, 10);
}

function fmtTime(t) {
  const m = String(t.getMonth() + 1).padStart(2, '0');
  const d = String(t.getDate()).padStart(2, '0');
  const h = String(t.getHours()).padStart(2, '0');
  const min = String(t.getMinutes()).padStart(2, '0');
  return `${m}-${d} ${h}:${min}`;
}

function timeAgo(timestamp) {
  const diff = Date.now() - timestamp;
  if (diff < 60000) return '刚刚更新';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前更新`;
  return `${Math.floor(diff / 3600000)}小时前更新`;
}

// ============================================================
// Section 3: API Client (port from Python ApiClient)
// ============================================================

let lastFetchTimestamp = 0;

async function apiGet(path) {
  const resp = await fetch(BASE_URL + path, {
    credentials: 'include',
    headers: { 'User-Agent': 'TokenPUA-Userscript/1.0' }
  });
  const text = await resp.text();
  if (!resp.ok) {
    if (resp.status === 401 || resp.status === 403) throw new Error('AUTH_EXPIRED');
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  if (text.trim().startsWith('<!') || text.trim().startsWith('<html>')) {
    throw new Error('AUTH_EXPIRED');
  }
  return JSON.parse(text);
}

async function fetchQuota() {
  return apiGet('/api/query-quota?platform=codebuddy');
}

async function fetchUsageDetails(startDate, endDate, page) {
  return apiGet(
    `/api/usage-details?start_date=${startDate}&end_date=${endDate}&dimension=all&page=${page}&page_size=${API_PAGE_SIZE}&platform=all`
  );
}

function parseCost(raw) {
  try {
    const s = String(raw || '0').replace(/[¥,]/g, '').trim();
    const n = parseFloat(s);
    return isNaN(n) ? 0 : n;
  } catch (e) {
    return 0;
  }
}

function toDisplayRecord(rec) {
  const recTime = rec.request_time || '';
  const cost = parseCost(rec.cost);
  const tokenStr = String(rec.total_tokens || '0').replace(/,/g, '');
  return {
    time: recTime.slice(0, 16),
    model: rec.model_name || '-',
    cost: cost,
    total_tokens: parseInt(tokenStr) || 0,
    user_input: (rec.user_input || '').slice(0, 100),
  };
}

async function fullScanMonth(monthStart, todayStr) {
  let todayUsed = 0;
  let todayLastTime = '';
  let records = [];
  let recordsLastTime = '';

  for (let page = 1; page <= FULL_SCAN_MAX_PAGES; page++) {
    let data;
    try {
      data = await fetchUsageDetails(monthStart, todayStr, page);
    } catch (e) {
      break;
    }
    const pageList = data && data.data ? data.data : [];
    if (!pageList.length) break;

    for (const rec of pageList) {
      const recTime = rec.request_time || '';
      if (recTime > recordsLastTime) recordsLastTime = recTime;
      if (recTime.startsWith(todayStr)) {
        todayUsed += parseCost(rec.cost);
        if (recTime > todayLastTime) todayLastTime = recTime;
      }
      records.push(toDisplayRecord(rec));
    }
    if (pageList.length < API_PAGE_SIZE) break;
  }

  records.sort((a, b) => b.time.localeCompare(a.time));
  records = records.slice(0, RECORDS_CACHE_LIMIT);
  return { todayUsed, todayLastTime, records, recordsLastTime };
}

// ============================================================
// Section 4: Pacing Algorithm (port from Python calc_pacing)
// ============================================================

function countWorkdays(start, end) {
  let d = new Date(start), n = 0;
  while (d <= end) {
    if (d.getDay() >= 1 && d.getDay() <= 5) n++;
    d.setDate(d.getDate() + 1);
  }
  return n;
}

function calcPacing(spent, budget, remainingWd) {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthElapsedPct = (today.getDate() / totalDays) * 100;

  const dailyQuota = (budget - spent) / Math.max(remainingWd, 1);

  const monthStart = new Date(year, month, 1);
  const monthEnd = new Date(year, month + 1, 0);
  const totalWd = countWorkdays(monthStart, monthEnd);
  const elapsedWd = countWorkdays(monthStart, today);

  const idealDaily = budget / Math.max(totalWd, 1);
  const actualDaily = spent / Math.max(elapsedWd, 1);
  const ratio = idealDaily >= 0.01 ? actualDaily / idealDaily : 999;

  let statusInfo = { icon: '\u{1F535}', text: '省着用', color: '#2196F3' };
  for (const th of STATUS_THRESHOLDS) {
    if (ratio > th.min) { statusInfo = th; break; }
  }

  let warning = null;
  const remaining = budget - spent;
  if (remainingWd <= 5 && remaining > 100) {
    warning = `还剩 ¥${remaining.toFixed(0)}，仅剩 ${remainingWd} 个工作日`;
  }

  return {
    spent, budget, pct: spent / budget * 100, dailyQuota,
    statusIcon: statusInfo.icon, statusText: statusInfo.text,
    statusColor: statusInfo.color, warning,
    remainingWd, totalDays, monthElapsedPct,
    elapsedWd, totalWd, actualDaily, idealDaily, ratio
  };
}

// ============================================================
// Section 5: Data Orchestrator (port from Python main())
// ============================================================

async function fetchAllData() {
  console.log('TokenPUA: fetching all data...');
  // 1. Fetch quota
  const quota = await fetchQuota();
  const totalUsed = parseFloat(quota.total_used) || 0;
  const totalQuota = parseFloat(quota.total_quota) || 1000;

  // 2. Usage details with cache merge logic
  const today = new Date();
  const todayStr = fmtDate(today);
  const monthStart = todayStr.slice(0, 7) + '-01';
  const currentMonth = todayStr.slice(0, 7);

  const cache = await GM_getValue(CACHE_KEY, null);
  let todayUsed, todayLastTime, records, recordsLastTime;

  if (!cache || cache.month !== currentMonth || cache.today_used === undefined) {
    // Full scan (new month or no cache)
    const result = await fullScanMonth(monthStart, todayStr);
    todayUsed = result.todayUsed;
    todayLastTime = result.todayLastTime;
    records = result.records;
    recordsLastTime = result.recordsLastTime;
  } else {
    // Incremental update
    todayUsed = cache.today_used;
    todayLastTime = cache.today_last_time || '';
    records = [...(cache.records || [])];
    recordsLastTime = cache.records_last_time || '';

    // Cross-day reset
    if (todayStr !== cache.today_date) {
      todayUsed = 0;
      todayLastTime = '';
    }

    // Fetch page 1 for new records
    try {
      const page1 = await fetchUsageDetails(monthStart, todayStr, 1);
      let newCosts = 0;
      let page1MaxTime = todayLastTime;
      let newRecords = [];

      if (page1 && Array.isArray(page1.data)) {
        for (const rec of page1.data) {
          const recTime = rec.request_time || '';
          if (recTime.startsWith(todayStr) && recTime > todayLastTime) {
            newCosts += parseCost(rec.cost);
          }
          if (recTime > cache.records_last_time) {
            newRecords.push(toDisplayRecord(rec));
          }
          if (recTime > page1MaxTime) {
            page1MaxTime = recTime;
          }
        }
        // Deduplicate and prepend new records
        if (newRecords.length) {
          const existingTimes = new Set(records.map(r => r.time));
          newRecords = newRecords.filter(r => !existingTimes.has(r.time));
          records = [...newRecords, ...records].slice(0, RECORDS_CACHE_LIMIT);
          for (const r of newRecords) {
            if (r.time > recordsLastTime) recordsLastTime = r.time;
          }
        }
        todayUsed += newCosts;
        if (page1MaxTime > todayLastTime) todayLastTime = page1MaxTime;
      }
    } catch (e) {
      // Incremental fetch failed, keep cached data
      console.warn('TokenPUA: incremental fetch failed:', e.message);
    }
  }

  // 3. Save cache
  lastFetchTimestamp = Date.now();
  await GM_setValue(CACHE_KEY, {
    time: fmtTime(new Date()),
    spent: totalUsed,
    today_date: todayStr,
    today_used: todayUsed,
    today_last_time: todayLastTime,
    month: currentMonth,
    records: records,
    records_last_time: recordsLastTime,
    timestamp: lastFetchTimestamp,
  });

  // 4. Calculate remaining workdays and pacing
  const totalDays = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const monthEnd = new Date(today.getFullYear(), today.getMonth(), totalDays);
  const remainingWd = countWorkdays(today, monthEnd);
  const pacing = calcPacing(totalUsed, totalQuota, remainingWd);

  return { pacing, todayUsed, records: records.slice(0, RECORDS_DISPLAY_LIMIT), timestamp: lastFetchTimestamp };
}

// ============================================================
// Section 6: UI Renderer
// ============================================================

// Progress bar helper
function renderBar(pct, color) {
  const c = color || (pct > 90 ? '#F44336' : pct > 70 ? '#FF9800' : '#4CAF50');
  return `<div class="tpua-bar-track"><div class="tpua-bar-fill" style="width:${Math.min(pct, 100)}%;background:${c}"></div></div>`;
}

function costClass(cost) {
  if (cost > 100) return 'tpua-cost-high';
  if (cost > 50) return 'tpua-cost-med';
  if (cost > 20) return 'tpua-cost-warn';
  if (cost < 0.0005) return 'tpua-cost-dim';
  return '';
}

function renderCollapsed(pacing) {
  const { statusIcon, statusText, spent, budget } = pacing;
  return `<div class="tpua-collapsed-inner" onclick="document.getElementById('tpua-panel').classList.replace('collapsed','expanded')">
    ${statusIcon} <span class="tpua-collapsed-amount">¥${spent.toFixed(0)}/¥${budget.toFixed(0)}</span> · ${statusText}
    <span class="tpua-toggle-icon">▲</span>
  </div>`;
}

function renderExpanded(pacing, todayUsed, records, timestamp) {
  const { statusIcon, statusText, statusColor, spent, budget, pct, dailyQuota,
          remainingWd, totalDays, monthElapsedPct, warning } = pacing;
  const now = new Date();
  const dayPct = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;
  const dayQuotaPct = dailyQuota > 0 ? (todayUsed / dailyQuota) * 100 : 0;
  const remaining = budget - spent;

  let html = '';

  // Header
  html += `<div class="tpua-header">
    <div class="tpua-status" style="color:${statusColor}">${statusIcon} ¥${spent.toFixed(0)}/¥${budget.toFixed(0)} · ${statusText}</div>
    <div class="tpua-header-actions">
      <span class="tpua-header-btn" onclick="document.getElementById('tpua-panel').classList.replace('expanded','collapsed')">▼</span>
      <span class="tpua-header-btn" onclick="document.getElementById('tpua-panel').remove()">×</span>
    </div>
  </div>`;

  // Month progress
  html += `<div class="tpua-section-title">月进度</div>`;
  html += `<div class="tpua-bar-row">
    <span class="tpua-bar-label">额度</span>
    ${renderBar(pct)}
    <span class="tpua-bar-num">${pct.toFixed(0)}%  ¥${spent.toFixed(0)}/¥${budget.toFixed(0)}</span>
  </div>`;
  html += `<div class="tpua-bar-row">
    <span class="tpua-bar-label">时间</span>
    ${renderBar(monthElapsedPct, '#8888cc')}
    <span class="tpua-bar-num">${monthElapsedPct.toFixed(0)}%  ${now.getDate()}/${totalDays}天</span>
  </div>`;

  // Day progress
  html += `<div class="tpua-section-title">日进度</div>`;
  html += `<div class="tpua-bar-row">
    <span class="tpua-bar-label">额度</span>
    ${renderBar(Math.min(dayQuotaPct, 100))}
    <span class="tpua-bar-num">${Math.min(dayQuotaPct, 100).toFixed(0)}%  ¥${todayUsed.toFixed(1)}/¥${dailyQuota.toFixed(0)}</span>
  </div>`;
  html += `<div class="tpua-bar-row">
    <span class="tpua-bar-label">时间</span>
    ${renderBar(dayPct, '#8888cc')}
    <span class="tpua-bar-num">${dayPct.toFixed(0)}%  ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}/24:00</span>
  </div>`;

  // Detail cards
  html += `<div class="tpua-cards">
    <div class="tpua-card">
      <div class="tpua-card-val">¥${dailyQuota.toFixed(0)}</div>
      <div class="tpua-card-label">目标日均</div>
    </div>
    <div class="tpua-card">
      <div class="tpua-card-val">${remainingWd}</div>
      <div class="tpua-card-label">剩余工作日</div>
    </div>
    <div class="tpua-card">
      <div class="tpua-card-val">¥${remaining.toFixed(0)}</div>
      <div class="tpua-card-label">剩余总额</div>
    </div>
    <div class="tpua-card">
      <div class="tpua-card-val">¥${todayUsed.toFixed(1)}</div>
      <div class="tpua-card-label">今日已用</div>
    </div>
  </div>`;

  // Warning
  if (warning) {
    html += `<div class="tpua-warning">⚠️ ${warning}</div>`;
  }

  // Records table
  if (records && records.length > 0) {
    html += `<div class="tpua-section-title">近期消费记录</div>`;
    html += `<div class="tpua-records">`;
    for (const rec of records) {
      let model = rec.model;
      for (const [prefix, alias] of Object.entries(MODEL_ALIASES)) {
        if (model.startsWith(prefix)) { model = alias + model.slice(prefix.length); break; }
      }
      if (model.startsWith('Claude-')) model = model.slice(7);
      model = model.length > 18 ? model.slice(0, 18) : model;

      const timeStr = rec.time.length >= 16 ? rec.time.slice(11, 16) : rec.time;
      const costStr = `¥${rec.cost.toFixed(3)}`;
      const tokenStr = rec.total_tokens.toLocaleString();
      const cls = costClass(rec.cost);

      html += `<div class="tpua-record-row">
        <span>${timeStr}  ${costStr}</span>
        <span class="${cls}">${model}  ${tokenStr}</span>
      </div>`;
    }
    html += `</div>`;
  }

  // Footer
  html += `<div class="tpua-footer">
    <span class="tpua-refresh-btn" onclick="window.__tpuaRefresh()">🔄 刷新（${timeAgo(timestamp)}）</span>
    <a href="${DASHBOARD_URL}" class="tpua-dashboard-link">打开看板 →</a>
  </div>`;

  return html;
}

function renderLoading() {
  return `<div class="tpua-collapsed-inner" style="justify-content:center">
    <span class="tpua-spinner"></span> 加载中...
  </div>`;
}

function renderError(msg) {
  let html = '';
  if (msg === 'AUTH_EXPIRED') {
    html = `<div class="tpua-error">⚠️ 需要登录<div class="tpua-error-sub">请先登录 token.woa.com</div></div>`;
  } else {
    html = `<div class="tpua-error">⚠️ ${msg}</div>`;
  }
  return html;
}

async function renderCachedFallback() {
  const cache = await GM_getValue(CACHE_KEY, null);
  const panel = document.getElementById('tpua-panel');
  if (!cache || !panel || cache.spent === undefined) return;

  const now = new Date();
  const totalDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const monthEnd = new Date(now.getFullYear(), now.getMonth(), totalDays);
  const remainingWd = countWorkdays(now, monthEnd) || 10;
  const budget = cache.spent > 0 ? Math.max(cache.spent / 0.5, 1000) : 1000;
  const pacing = calcPacing(cache.spent, budget, remainingWd);

  panel.innerHTML = `<div class="tpua-error-bar">⚠️ 网络错误，显示缓存数据</div>` +
    renderExpanded(pacing, cache.today_used || 0, (cache.records || []).slice(0, RECORDS_DISPLAY_LIMIT), cache.timestamp || Date.now());
  panel.classList.replace('collapsed', 'expanded');
}

// ============================================================
// Section 7: Refresh Controller
// ============================================================

let refreshTimer = null;

function startAutoRefresh() {
  stopAutoRefresh();
  refreshTimer = setInterval(refreshData, REFRESH_INTERVAL_MS);
}

function stopAutoRefresh() {
  if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
}

async function refreshData() {
  console.log('TokenPUA: refresh started');
  const panel = document.getElementById('tpua-panel');
  if (!panel) return;

  try {
    panel.dataset.state = 'loading';
    if (panel.classList.contains('expanded')) {
      panel.innerHTML = renderLoading();
    }

    const data = await fetchAllData();
    panel.dataset.state = 'loaded';

    if (data.pacing.budget <= 0) {
      data.pacing.budget = 1000;
      data.pacing.pct = data.pacing.spent / 1000 * 100;
    }

    if (panel.classList.contains('collapsed')) {
      panel.innerHTML = renderCollapsed(data.pacing);
    } else {
      panel.innerHTML = renderExpanded(data.pacing, data.todayUsed, data.records, data.timestamp);
    }
  } catch (e) {
    panel.dataset.state = 'error';
    if (e.message === 'AUTH_EXPIRED') {
      panel.innerHTML = renderError('AUTH_EXPIRED');
    } else {
      console.error('TokenPUA fetch error:', e);
      panel.innerHTML = renderError(e.message);
      renderCachedFallback();
    }
  }
}

// ============================================================
// Section 8: UI Injection
// ============================================================

function injectPanel() {
  if (document.getElementById('tpua-panel')) return;

  if (!document.body) {
    console.error('TokenPUA: document.body not ready, aborting injection');
    return;
  }

  const panel = document.createElement('div');
  panel.id = 'tpua-panel';
  panel.className = 'collapsed';
  panel.dataset.state = 'init';
  panel.innerHTML = renderLoading();

  document.body.appendChild(panel);
  console.log('TokenPUA: panel injected into DOM');

  // Global refresh function (accessible from onclick)
  window.__tpuaRefresh = refreshData;
}

// ============================================================
// Section 9: CSS
// ============================================================

const PANEL_CSS = `
#tpua-panel {
  position: fixed;
  bottom: 16px;
  right: 16px;
  z-index: 2147483647;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  font-size: 13px;
  color: #e0e0e0;
  background: rgba(26, 26, 46, 0.95);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  user-select: none;
  max-height: 80vh;
  overflow: hidden;
}

#tpua-panel.collapsed {
  width: auto;
  height: 40px;
}

#tpua-panel.expanded {
  width: 380px;
  max-height: 80vh;
  overflow-y: auto;
}

/* Collapsed bar */
.tpua-collapsed-inner {
  display: flex;
  align-items: center;
  height: 40px;
  padding: 0 14px;
  gap: 6px;
  cursor: pointer;
  white-space: nowrap;
}
.tpua-collapsed-amount {
  font-weight: 600;
}
.tpua-toggle-icon {
  font-size: 10px;
  opacity: 0.5;
  margin-left: 4px;
}

/* Header */
.tpua-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.tpua-status {
  font-weight: 600;
  font-size: 13px;
}
.tpua-header-actions {
  display: flex;
  gap: 8px;
}
.tpua-header-btn {
  cursor: pointer;
  opacity: 0.5;
  font-size: 14px;
  padding: 2px 4px;
  border-radius: 4px;
}
.tpua-header-btn:hover {
  opacity: 1;
  background: rgba(255,255,255,0.1);
}

/* Sections */
.tpua-section-title {
  padding: 10px 16px 4px;
  font-size: 11px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

/* Bar rows */
.tpua-bar-row {
  display: flex;
  align-items: center;
  padding: 4px 16px;
  gap: 10px;
}
.tpua-bar-label {
  width: 32px;
  font-size: 11px;
  color: #888;
  text-align: right;
  flex-shrink: 0;
}
.tpua-bar-track {
  flex: 1;
  height: 14px;
  background: rgba(255,255,255,0.06);
  border-radius: 7px;
  overflow: hidden;
}
.tpua-bar-fill {
  height: 100%;
  border-radius: 7px;
  transition: width 0.4s ease;
}
.tpua-bar-num {
  font-size: 11px;
  color: #aaa;
  white-space: nowrap;
  min-width: 90px;
  text-align: left;
}

/* Cards grid */
.tpua-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px 16px 6px;
}
.tpua-card {
  background: rgba(255,255,255,0.04);
  border-radius: 8px;
  padding: 10px 12px;
  text-align: center;
}
.tpua-card-val {
  font-size: 16px;
  font-weight: 700;
}
.tpua-card-label {
  font-size: 10px;
  color: #888;
  margin-top: 2px;
}

/* Warning */
.tpua-warning {
  margin: 8px 16px;
  padding: 8px 12px;
  background: rgba(255,107,107,0.1);
  border: 1px solid rgba(255,107,107,0.2);
  border-radius: 6px;
  font-size: 11px;
  color: #FF6B6B;
}

/* Records table */
.tpua-records {
  max-height: 320px;
  overflow-y: auto;
  padding: 0 16px 8px;
}
.tpua-record-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 11px;
  font-family: Menlo, Monaco, monospace;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.tpua-record-row:last-child {
  border-bottom: none;
}

.tpua-cost-high  { color: #cc3333; }
.tpua-cost-med   { color: #e05530; }
.tpua-cost-warn  { color: #c09030; }
.tpua-cost-dim   { color: #666; }

/* Footer */
.tpua-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px 14px;
  border-top: 1px solid rgba(255,255,255,0.06);
  font-size: 11px;
}
.tpua-refresh-btn {
  cursor: pointer;
  color: #aaa;
}
.tpua-refresh-btn:hover {
  color: #fff;
}
.tpua-dashboard-link {
  color: #888;
  text-decoration: none;
}
.tpua-dashboard-link:hover {
  color: #4CAF50;
}

/* Error states */
.tpua-error {
  padding: 10px 16px;
  color: #FF6B6B;
  font-size: 12px;
  text-align: center;
}
.tpua-error-sub {
  margin-top: 4px;
  font-size: 11px;
  color: #888;
}
.tpua-error-bar {
  padding: 8px 16px;
  font-size: 12px;
  color: #FF9800;
  text-align: center;
}

/* Scrollbar */
.tpua-records::-webkit-scrollbar { width: 4px; }
.tpua-records::-webkit-scrollbar-track { background: transparent; }
.tpua-records::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
#tpua-panel::-webkit-scrollbar { width: 4px; }
#tpua-panel::-webkit-scrollbar-track { background: transparent; }
#tpua-panel::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }

/* Loading spinner */
@keyframes tpua-spin {
  to { transform: rotate(360deg); }
}
.tpua-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.1);
  border-top-color: #4CAF50;
  border-radius: 50%;
  animation: tpua-spin 0.6s linear infinite;
  margin-right: 6px;
}
`;

function injectStyles() {
  try {
    // Prefer GM_addStyle for proper sandboxing
    if (typeof GM_addStyle !== 'undefined') {
      GM_addStyle(PANEL_CSS);
      console.log('TokenPUA: styles injected via GM_addStyle');
      return;
    }
  } catch (e) {
    console.warn('TokenPUA: GM_addStyle threw, falling back to <style> element', e);
  }
  // Manual fallback
  const style = document.createElement('style');
  style.id = 'tpua-styles';
  style.textContent = PANEL_CSS;
  (document.head || document.documentElement).appendChild(style);
  console.log('TokenPUA: styles injected via <style> element');
}

// ============================================================
// Section 10: Initialization
// ============================================================

async function init() {
  injectStyles();
  console.log('TokenPUA: init started');

  injectPanel();
  const panel = document.getElementById('tpua-panel');
  if (!panel) {
    console.error('TokenPUA: failed to create panel');
    return;
  }

  // Show loading
  panel.innerHTML = renderLoading();
  panel.classList.add('collapsed');

  // Try to show cached data immediately
  const cache = await GM_getValue(CACHE_KEY, null);
  if (cache && cache.spent !== undefined && cache.today_used === undefined) {
    // Old cache format (no today_used) - skip
  } else if (cache && cache.spent !== undefined) {
    const now = new Date();
    const totalDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const monthEnd = new Date(now.getFullYear(), now.getMonth(), totalDays);
    const remainingWd = countWorkdays(now, monthEnd);
    const pacing = calcPacing(cache.spent, cache.spent > 0 ? (cache.spent / 0.5) : 1000, remainingWd || 10);
    // If budget in cache is unknown, estimate from existing data
    if (!cache.budget) {
      pacing.budget = cache.spent > 0 ? Math.max(cache.spent * 1.5, 1000) : 1000;
      pacing.pct = pacing.spent / pacing.budget * 100;
    }
    panel.innerHTML = renderCollapsed(pacing);
  }

  // Start first fetch (will update UI when done)
  try {
    await refreshData();
  } catch (e) {
    console.error('TokenPUA initial fetch failed:', e);
    if (e.message === 'AUTH_EXPIRED') {
      panel.innerHTML = renderError('AUTH_EXPIRED');
    }
  }

  // Start auto-refresh
  startAutoRefresh();

  // Pause on tab hidden, resume on visible
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopAutoRefresh();
    } else {
      refreshData();
      startAutoRefresh();
    }
  });
}

// ============================================================
// Entry Point
// ============================================================

(function() {
  'use strict';
  console.log('TokenPUA: script loaded, scheduling init...');
  setTimeout(init, 800);
})();
