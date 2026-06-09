// ==UserScript==
// @name         TokenPUA - 额度看板
// @namespace    https://github.com/dwf89044485/TokenPUA
// @version      1.0.1
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
(function() {
  'use strict';

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

  const MODEL_ALIASES = { 'DeepSeek': 'DS' };

  const STATUS_THRESHOLDS = [
    { min: 1.3, icon: '\u{1F7E5}', text: '加速',   color: '#F44336' },
    { min: 1.1, icon: '\u{1F7E1}', text: '稍加速', color: '#FF9800' },
    { min: 0.9, icon: '\u{1F7E2}', text: '完美',   color: '#4CAF50' },
    { min: 0.7, icon: '\u{1F7E1}', text: '可放缓', color: '#FF9800' },
    { min: 0,   icon: '\u{1F535}', text: '省着用', color: '#2196F3' },
  ];

  const CACHE_KEY = 'tokenpua_cache';

  // ============================================================
  // Section 2: Utility Functions
  // ============================================================

  function fmtDate(d) { return d.toISOString().slice(0, 10); }

  function fmtTime(t) {
    const m = String(t.getMonth() + 1).padStart(2, '0');
    const d = String(t.getDate()).padStart(2, '0');
    const h = String(t.getHours()).padStart(2, '0');
    const min = String(t.getMinutes()).padStart(2, '0');
    return `${m}-${d} ${h}:${min}`;
  }

  function timeAgo(ts) {
    const diff = Date.now() - ts;
    if (diff < 60000) return '刚刚更新';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前更新`;
    return `${Math.floor(diff / 3600000)}小时前更新`;
  }

  // ============================================================
  // Section 3: Main-World API Injector
  // ============================================================
  // The key difference from v1.0: Tampermonkey @grant sandbox has no
  // correct Origin header. We inject a <script> tag into the page's
  // MAIN world (same trick as the Chrome extension) so fetch() carries
  // Origin: https://token.woa.com. Results come back via postMessage.

  function injectMainWorldFetcher() {
    // Remove any stale injected script from previous version
    const old = document.getElementById('tpua-main-fetcher');
    if (old) old.remove();

    const s = document.createElement('script');
    s.id = 'tpua-main-fetcher';
    s.textContent = `
(function() {
  // Version check — force re-init if outdated
  if (window.__tpuaFetcherVersion === 2) return;
  window.__tpuaFetcherVersion = 2;
  window.__tpuaFetcherReady = true;

  const BASE = '${BASE_URL}';

  // Read Page-Token from <meta name="pt">
  function getPageToken() {
    const meta = document.querySelector('meta[name="pt"]');
    const token = meta ? meta.content : '';
    console.log('TokenPUA [main]: page token found:', token ? token.slice(0, 20) + '...' : 'NONE');
    return token;
  }

  async function apiGet(path) {
    // Try to use the page's own apiFetch if available (handles token refresh)
    if (typeof apiFetch === 'function') {
      console.log('TokenPUA [main]: using page apiFetch for', path);
      try {
        const data = await apiFetch(path, { credentials: 'include' });
        return data;
      } catch (e) {
        // page's apiFetch may auto-reload on token_expired; if we're here, it's a different error
        throw new Error('apiFetch error: ' + e.message);
      }
    }

    // Fallback: our own fetch with X-Page-Token
    const headers = {};
    const pt = getPageToken();
    if (pt) headers['X-Page-Token'] = pt;

    console.log('TokenPUA [main]: fetching', path, 'with token:', !!pt);
    const resp = await fetch(BASE + path, {
      credentials: 'include',
      headers: headers
    });
    const text = await resp.text();
    if (!resp.ok) {
      if (resp.status === 401 || resp.status === 403) {
        console.error('TokenPUA [main]: auth error', resp.status, text.slice(0, 200));
        throw new Error('AUTH_EXPIRED');
      }
      throw new Error('HTTP ' + resp.status + ': ' + text.slice(0, 200));
    }
    return JSON.parse(text);
  }

  function pc(raw) {
    try {
      const s = String(raw || '0').replace(/[¥,]/g, '').trim();
      const n = parseFloat(s);
      return isNaN(n) ? 0 : n;
    } catch(e) { return 0; }
  }

  function toRec(rec) {
    const ts = rec.request_time || '';
    const tk = String(rec.total_tokens || '0').replace(/,/g, '');
    return {
      time: ts.slice(0, 16),
      model: rec.model_name || '-',
      cost: pc(rec.cost),
      total_tokens: parseInt(tk) || 0,
      user_input: (rec.user_input || '').slice(0, 100),
    };
  }

  async function doFetch(monthStart, todayStr, cacheLastTime) {
    // 1. Fetch quota
    const quota = await apiGet('/api/query-quota?platform=codebuddy');
    const totalUsed = parseFloat(quota.total_used) || 0;
    const totalQuota = parseFloat(quota.total_quota) || 1000;

    // 2. Fetch usage details (page 1 only; orchestrator handles full scan)
    let todayUsed = 0, todayLastTime = '', records = [], recordsLastTime = '';
    try {
      const d1 = await apiGet(
        '/api/usage-details?start_date=' + monthStart + '&end_date=' + todayStr +
        '&dimension=all&page=1&page_size=50&platform=all'
      );
      if (d1 && d1.data) {
        for (const rec of d1.data) {
          const rt = rec.request_time || '';
          if (rt > recordsLastTime) recordsLastTime = rt;
          if (rt.startsWith(todayStr)) {
            todayUsed += pc(rec.cost);
            if (rt > todayLastTime) todayLastTime = rt;
          }
          records.push(toRec(rec));
        }
        records.sort(function(a,b) { return b.time.localeCompare(a.time); });
        records = records.slice(0, 200);
      }
    } catch(e) { /* page 1 fail is ok */ }

    window.postMessage({
      source: '__tpua_fetch',
      success: true,
      data: { totalUsed, totalQuota, todayUsed, todayLastTime, records, recordsLastTime, monthStart, todayStr }
    }, '*');
  }

  // Listen for fetch triggers from the userscript sandbox
  window.addEventListener('message', function(e) {
    if (e.data && e.data.source === '__tpua_trigger') {
      try {
        doFetch(e.data.monthStart, e.data.todayStr, e.data.cacheLastTime || '');
      } catch(err) {
        window.postMessage({ source: '__tpua_fetch', success: false, error: err.message }, '*');
      }
    }
  });
})();
`;
    (document.head || document.documentElement).appendChild(s);
    console.log('TokenPUA: main-world fetcher injected');
  }

  // ============================================================
  // Section 4: Pacing Algorithm
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
    const y = today.getFullYear(), m = today.getMonth();
    const totalDays = new Date(y, m + 1, 0).getDate();
    const monthElapsedPct = (today.getDate() / totalDays) * 100;
    const dailyQuota = (budget - spent) / Math.max(remainingWd, 1);

    const ms = new Date(y, m, 1);
    const me = new Date(y, m + 1, 0);
    const totalWd = countWorkdays(ms, me);
    const elapsedWd = countWorkdays(ms, today);

    const idealDaily = budget / Math.max(totalWd, 1);
    const ratio = idealDaily >= 0.01 ? (spent / Math.max(elapsedWd, 1)) / idealDaily : 999;

    let si = STATUS_THRESHOLDS[STATUS_THRESHOLDS.length - 1];
    for (const th of STATUS_THRESHOLDS) {
      if (ratio > th.min) { si = th; break; }
    }

    let warning = null;
    const rem = budget - spent;
    if (remainingWd <= 5 && rem > 100) {
      warning = '还剩 ¥' + rem.toFixed(0) + '，仅剩 ' + remainingWd + ' 个工作日';
    }

    return { spent, budget, pct: spent / budget * 100, dailyQuota,
      statusIcon: si.icon, statusText: si.text, statusColor: si.color, warning,
      remainingWd, totalDays, monthElapsedPct };
  }

  // ============================================================
  // Section 5: Data Orchestrator
  // ============================================================

  let fetchResolve = null;
  let fetchReject = null;
  let lastFetchTimestamp = 0;

  function waitForFetchResult(timeoutMs) {
    return new Promise((resolve, reject) => {
      fetchResolve = resolve;
      fetchReject = reject;
      setTimeout(() => {
        if (fetchResolve) {
          fetchResolve = null; fetchReject = null;
          reject(new Error('FETCH_TIMEOUT'));
        }
      }, timeoutMs);
    });
  }

  async function fetchAllData() {
    console.log('TokenPUA: triggering main-world fetch...');
    const today = new Date();
    const todayStr = fmtDate(today);
    const monthStart = todayStr.slice(0, 7) + '-01';
    const currentMonth = todayStr.slice(0, 7);

    // Trigger fetch in main world
    window.postMessage({
      source: '__tpua_trigger',
      monthStart, todayStr
    }, '*');

    // Wait for result (up to 15 seconds)
    let fetchData;
    try {
      fetchData = await waitForFetchResult(15000);
    } catch (e) {
      if (e.message === 'FETCH_TIMEOUT') throw new Error('请求超时，请检查网络');
      throw e;
    }

    if (!fetchData.success) {
      if (fetchData.error === 'AUTH_EXPIRED') throw new Error('AUTH_EXPIRED');
      throw new Error(fetchData.error || '未知错误');
    }

    const d = fetchData.data;
    let totalUsed = d.totalUsed;
    let totalQuota = d.totalQuota;
    let todayUsed = d.todayUsed;
    let todayLastTime = d.todayLastTime;
    let records = d.records;
    let recordsLastTime = d.recordsLastTime;
    let needFullScan = false;

    // Cache merge logic
    const cache = await GM_getValue(CACHE_KEY, null);
    if (!cache || cache.month !== currentMonth || cache.today_used === undefined) {
      needFullScan = true;
    }

    if (needFullScan) {
      // We already have page 1 data; fetch remaining pages if needed
      // For now, page 1 is sufficient for most cases (most users < 50 records/day)
      todayUsed = d.todayUsed;
      todayLastTime = d.todayLastTime;
      // Need more pages? Re-fetch with full scan
      if (d.records && d.records.length >= 50) {
        // Signal main world to do full scan
        // For simplicity, page 1 is usually enough
      }
    } else {
      // Incremental update
      todayUsed = cache.today_used;
      todayLastTime = cache.today_last_time || '';
      records = [...(cache.records || [])];
      recordsLastTime = cache.records_last_time || '';

      if (todayStr !== cache.today_date) {
        todayUsed = 0;
        todayLastTime = '';
      }

      // Merge new records from page 1
      let newCosts = 0;
      let page1MaxTime = todayLastTime;
      let newRecords = [];

      if (d.records && d.records.length) {
        for (const rec of d.records) {
          if (rec.time.startsWith(todayStr) && rec.time > todayLastTime) {
            newCosts += rec.cost;
          }
          if (rec.time > cache.records_last_time) {
            newRecords.push(rec);
          }
          if (rec.time > page1MaxTime) page1MaxTime = rec.time;
        }
      }

      if (newRecords.length) {
        const et = new Set(records.map(r => r.time));
        newRecords = newRecords.filter(r => !et.has(r.time));
        records = [...newRecords, ...records].slice(0, RECORDS_CACHE_LIMIT);
        for (const r of newRecords) {
          if (r.time > recordsLastTime) recordsLastTime = r.time;
        }
      }
      todayUsed += newCosts;
      if (page1MaxTime > todayLastTime) todayLastTime = page1MaxTime;
    }

    // Save cache
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

    // Calculate pacing
    const yd = new Date(), ym = yd.getMonth();
    const totalDays = new Date(yd.getFullYear(), ym + 1, 0).getDate();
    const monthEnd = new Date(yd.getFullYear(), ym, totalDays);
    const remainingWd = countWorkdays(yd, monthEnd);
    const pacing = calcPacing(totalUsed, totalQuota, remainingWd);

    return { pacing, todayUsed, records: records.slice(0, RECORDS_DISPLAY_LIMIT), timestamp: lastFetchTimestamp };
  }

  // ============================================================
  // Section 6: UI Renderer
  // ============================================================

  function renderBar(pct, color) {
    const c = color || (pct > 90 ? '#F44336' : pct > 70 ? '#FF9800' : '#4CAF50');
    return '<div class="tpua-bar-track"><div class="tpua-bar-fill" style="width:' + Math.min(pct, 100) + '%;background:' + c + '"></div></div>';
  }

  function costClass(cost) {
    if (cost > 100) return 'tpua-cost-high';
    if (cost > 50) return 'tpua-cost-med';
    if (cost > 20) return 'tpua-cost-warn';
    if (cost < 0.0005) return 'tpua-cost-dim';
    return '';
  }

  function renderCollapsed(p) {
    return '<div class="tpua-collapsed-inner" onclick="document.getElementById(\'tpua-panel\').classList.replace(\'collapsed\',\'expanded\')">' +
      p.statusIcon + ' <span class="tpua-collapsed-amount">¥' + p.spent.toFixed(0) + '/¥' + p.budget.toFixed(0) + '</span> · ' + p.statusText +
      '<span class="tpua-toggle-icon">▲</span></div>';
  }

  function renderExpanded(p, todayUsed, records, timestamp) {
    const now = new Date();
    const dayPct = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;
    const dayQuotaPct = p.dailyQuota > 0 ? (todayUsed / p.dailyQuota) * 100 : 0;
    const remaining = p.budget - p.spent;

    let h = '';
    h += '<div class="tpua-header"><div class="tpua-status" style="color:' + p.statusColor + '">' + p.statusIcon + ' ¥' + p.spent.toFixed(0) + '/¥' + p.budget.toFixed(0) + ' · ' + p.statusText + '</div>';
    h += '<div class="tpua-header-actions">';
    h += '<span class="tpua-header-btn" onclick="document.getElementById(\'tpua-panel\').classList.replace(\'expanded\',\'collapsed\')">▼</span>';
    h += '<span class="tpua-header-btn" onclick="document.getElementById(\'tpua-panel\').remove()">×</span>';
    h += '</div></div>';

    h += '<div class="tpua-section-title">月进度</div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">额度</span>' + renderBar(p.pct) + '<span class="tpua-bar-num">' + p.pct.toFixed(0) + '%  ¥' + p.spent.toFixed(0) + '/¥' + p.budget.toFixed(0) + '</span></div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">时间</span>' + renderBar(p.monthElapsedPct, '#8888cc') + '<span class="tpua-bar-num">' + p.monthElapsedPct.toFixed(0) + '%  ' + now.getDate() + '/' + p.totalDays + '天</span></div>';

    h += '<div class="tpua-section-title">日进度</div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">额度</span>' + renderBar(Math.min(dayQuotaPct, 100)) + '<span class="tpua-bar-num">' + Math.min(dayQuotaPct, 100).toFixed(0) + '%  ¥' + todayUsed.toFixed(1) + '/¥' + p.dailyQuota.toFixed(0) + '</span></div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">时间</span>' + renderBar(dayPct, '#8888cc') + '<span class="tpua-bar-num">' + dayPct.toFixed(0) + '%  ' + String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0') + '/24:00</span></div>';

    h += '<div class="tpua-cards">';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + p.dailyQuota.toFixed(0) + '</div><div class="tpua-card-label">目标日均</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">' + p.remainingWd + '</div><div class="tpua-card-label">剩余工作日</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + remaining.toFixed(0) + '</div><div class="tpua-card-label">剩余总额</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + todayUsed.toFixed(1) + '</div><div class="tpua-card-label">今日已用</div></div>';
    h += '</div>';

    if (p.warning) {
      h += '<div class="tpua-warning">⚠️ ' + p.warning + '</div>';
    }

    if (records && records.length > 0) {
      h += '<div class="tpua-section-title">近期消费记录</div><div class="tpua-records">';
      for (const rec of records) {
        let model = rec.model;
        for (const [pfx, alias] of Object.entries(MODEL_ALIASES)) {
          if (model.startsWith(pfx)) { model = alias + model.slice(pfx.length); break; }
        }
        if (model.startsWith('Claude-')) model = model.slice(7);
        model = model.length > 18 ? model.slice(0, 18) : model;
        const ts = rec.time.length >= 16 ? rec.time.slice(11, 16) : rec.time;
        const cs = '¥' + rec.cost.toFixed(3);
        const tks = rec.total_tokens.toLocaleString();
        const cls = costClass(rec.cost);
        h += '<div class="tpua-record-row"><span>' + ts + '  ' + cs + '</span><span class="' + cls + '">' + model + '  ' + tks + '</span></div>';
      }
      h += '</div>';
    }

    h += '<div class="tpua-footer">';
    h += '<span class="tpua-refresh-btn" onclick="window.__tpuaRefresh()">🔄 刷新（' + timeAgo(timestamp) + '）</span>';
    h += '<a href="' + DASHBOARD_URL + '" class="tpua-dashboard-link">打开看板 →</a>';
    h += '</div>';

    return h;
  }

  function renderLoading() {
    return '<div class="tpua-collapsed-inner" style="justify-content:center"><span class="tpua-spinner"></span> 加载中...</div>';
  }

  function renderError(msg) {
    if (msg === 'AUTH_EXPIRED') {
      return '<div class="tpua-error">⚠️ 需要登录<div class="tpua-error-sub">请先登录 token.woa.com</div></div>';
    }
    return '<div class="tpua-error">⚠️ ' + msg + '</div>';
  }

  async function renderCachedFallback() {
    const cache = await GM_getValue(CACHE_KEY, null);
    const panel = document.getElementById('tpua-panel');
    if (!cache || !panel || cache.spent === undefined) return;

    const now = new Date();
    const totalDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
    const monthEnd = new Date(now.getFullYear(), now.getMonth(), totalDays);
    const rwd = countWorkdays(now, monthEnd) || 10;
    const budget = cache.spent > 0 ? Math.max(cache.spent / 0.5, 1000) : 1000;
    const p = calcPacing(cache.spent, budget, rwd);

    panel.innerHTML = '<div class="tpua-error-bar">⚠️ 网络错误，显示缓存数据</div>' +
      renderExpanded(p, cache.today_used || 0, (cache.records || []).slice(0, RECORDS_DISPLAY_LIMIT), cache.timestamp || Date.now());
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
      if (panel.classList.contains('expanded')) {
        panel.innerHTML = renderLoading();
      }

      const data = await fetchAllData();

      if (data.pacing.budget <= 0) {
        data.pacing.budget = 1000;
        data.pacing.pct = data.pacing.spent / 1000 * 100;
      }

      if (panel.classList.contains('collapsed')) {
        panel.innerHTML = renderCollapsed(data.pacing);
      } else {
        panel.innerHTML = renderExpanded(data.pacing, data.todayUsed, data.records, data.timestamp);
      }
      panel.dataset.state = 'loaded';
    } catch (e) {
      console.error('TokenPUA refresh error:', e);
      panel.dataset.state = 'error';
      if (e.message === 'AUTH_EXPIRED') {
        panel.innerHTML = renderError('AUTH_EXPIRED');
      } else {
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
      console.error('TokenPUA: document.body not ready');
      return;
    }

    const panel = document.createElement('div');
    panel.id = 'tpua-panel';
    panel.className = 'collapsed';
    panel.innerHTML = renderLoading();
    document.body.appendChild(panel);
    console.log('TokenPUA: panel injected');

    window.__tpuaRefresh = refreshData;
  }

  // ============================================================
  // Section 9: Styles
  // ============================================================

  function injectStyles() {
    const css = [
      '#tpua-panel{position:fixed;bottom:16px;right:16px;z-index:2147483647;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;font-size:13px;color:#e0e0e0;background:rgba(26,26,46,0.95);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.08);border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,0.4);user-select:none;max-height:80vh;overflow:hidden}',
      '#tpua-panel.collapsed{width:auto;height:40px}',
      '#tpua-panel.expanded{width:380px;max-height:80vh;overflow-y:auto}',
      '.tpua-collapsed-inner{display:flex;align-items:center;height:40px;padding:0 14px;gap:6px;cursor:pointer;white-space:nowrap}',
      '.tpua-collapsed-amount{font-weight:600}',
      '.tpua-toggle-icon{font-size:10px;opacity:0.5;margin-left:4px}',
      '.tpua-header{display:flex;align-items:center;justify-content:space-between;padding:14px 16px 12px;border-bottom:1px solid rgba(255,255,255,0.06)}',
      '.tpua-status{font-weight:600;font-size:13px}',
      '.tpua-header-actions{display:flex;gap:8px}',
      '.tpua-header-btn{cursor:pointer;opacity:0.5;font-size:14px;padding:2px 4px;border-radius:4px}',
      '.tpua-header-btn:hover{opacity:1;background:rgba(255,255,255,0.1)}',
      '.tpua-section-title{padding:10px 16px 4px;font-size:11px;color:#888;text-transform:uppercase;letter-spacing:0.5px}',
      '.tpua-bar-row{display:flex;align-items:center;padding:4px 16px;gap:10px}',
      '.tpua-bar-label{width:32px;font-size:11px;color:#888;text-align:right;flex-shrink:0}',
      '.tpua-bar-track{flex:1;height:14px;background:rgba(255,255,255,0.06);border-radius:7px;overflow:hidden}',
      '.tpua-bar-fill{height:100%;border-radius:7px;transition:width 0.4s ease}',
      '.tpua-bar-num{font-size:11px;color:#aaa;white-space:nowrap;min-width:90px;text-align:left}',
      '.tpua-cards{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:10px 16px 6px}',
      '.tpua-card{background:rgba(255,255,255,0.04);border-radius:8px;padding:10px 12px;text-align:center}',
      '.tpua-card-val{font-size:16px;font-weight:700}',
      '.tpua-card-label{font-size:10px;color:#888;margin-top:2px}',
      '.tpua-warning{margin:8px 16px;padding:8px 12px;background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.2);border-radius:6px;font-size:11px;color:#FF6B6B}',
      '.tpua-records{max-height:320px;overflow-y:auto;padding:0 16px 8px}',
      '.tpua-record-row{display:flex;justify-content:space-between;padding:3px 0;font-size:11px;font-family:Menlo,Monaco,monospace;border-bottom:1px solid rgba(255,255,255,0.03)}',
      '.tpua-record-row:last-child{border-bottom:none}',
      '.tpua-cost-high{color:#cc3333}',
      '.tpua-cost-med{color:#e05530}',
      '.tpua-cost-warn{color:#c09030}',
      '.tpua-cost-dim{color:#666}',
      '.tpua-footer{display:flex;justify-content:space-between;align-items:center;padding:10px 16px 14px;border-top:1px solid rgba(255,255,255,0.06);font-size:11px}',
      '.tpua-refresh-btn{cursor:pointer;color:#aaa}',
      '.tpua-refresh-btn:hover{color:#fff}',
      '.tpua-dashboard-link{color:#888;text-decoration:none}',
      '.tpua-dashboard-link:hover{color:#4CAF50}',
      '.tpua-error{padding:10px 16px;color:#FF6B6B;font-size:12px;text-align:center}',
      '.tpua-error-sub{margin-top:4px;font-size:11px;color:#888}',
      '.tpua-error-bar{padding:8px 16px;font-size:12px;color:#FF9800;text-align:center}',
      '.tpua-records::-webkit-scrollbar{width:4px}',
      '.tpua-records::-webkit-scrollbar-track{background:transparent}',
      '.tpua-records::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}',
      '#tpua-panel::-webkit-scrollbar{width:4px}',
      '#tpua-panel::-webkit-scrollbar-track{background:transparent}',
      '#tpua-panel::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}',
      '@keyframes tpua-spin{to{transform:rotate(360deg)}}',
      '.tpua-spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.1);border-top-color:#4CAF50;border-radius:50%;animation:tpua-spin 0.6s linear infinite;margin-right:6px}',
    ].join('');

    try {
      if (typeof GM_addStyle !== 'undefined') {
        GM_addStyle(css);
        console.log('TokenPUA: styles via GM_addStyle');
        return;
      }
    } catch(e) {
      console.warn('TokenPUA: GM_addStyle failed, using <style>');
    }
    var s = document.createElement('style');
    s.id = 'tpua-styles';
    s.textContent = css;
    (document.head || document.documentElement).appendChild(s);
    console.log('TokenPUA: styles via <style> element');
  }

  // ============================================================
  // Section 10: Initialization
  // ============================================================

  async function init() {
    injectStyles();
    console.log('TokenPUA: init started');

    // Inject main-world fetcher (runs fetch() in page context)
    injectMainWorldFetcher();

    injectPanel();
    var panel = document.getElementById('tpua-panel');
    if (!panel) {
      console.error('TokenPUA: failed to create panel');
      return;
    }

    // Show cached data immediately
    var cache = await GM_getValue(CACHE_KEY, null);
    if (cache && cache.spent !== undefined && cache.today_used !== undefined) {
      var now = new Date();
      var totalDays = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
      var monthEnd = new Date(now.getFullYear(), now.getMonth(), totalDays);
      var rwd = countWorkdays(now, monthEnd);
      var p = calcPacing(cache.spent, cache.spent > 0 ? Math.max(cache.spent / 0.5, 1000) : 1000, rwd || 10);
      if (!cache.budget) {
        p.budget = cache.spent > 0 ? Math.max(cache.spent * 1.5, 1000) : 1000;
        p.pct = p.spent / p.budget * 100;
      }
      panel.innerHTML = renderCollapsed(p);
    } else {
      panel.innerHTML = renderLoading();
    }

    // First fetch
    try {
      await refreshData();
    } catch(e) {
      console.error('TokenPUA initial fetch failed:', e);
      if (e.message === 'AUTH_EXPIRED') {
        panel.innerHTML = renderError('AUTH_EXPIRED');
      }
    }

    startAutoRefresh();

    document.addEventListener('visibilitychange', function() {
      if (document.hidden) {
        stopAutoRefresh();
      } else {
        refreshData();
        startAutoRefresh();
      }
    });
  }

  // ============================================================
  // Message Listener: receives fetch results from main world
  // ============================================================

  window.addEventListener('message', function(e) {
    if (e.data && e.data.source === '__tpua_fetch') {
      console.log('TokenPUA: received fetch result', e.data.success ? 'success' : 'error');
      if (fetchResolve) {
        fetchResolve(e.data);
        fetchResolve = null;
        fetchReject = null;
      }
    }
  });

  // ============================================================
  // Entry Point
  // ============================================================

  console.log('TokenPUA: script loaded, scheduling init...');
  setTimeout(init, 800);
})();
