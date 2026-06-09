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
    // Use our own fetch with X-Page-Token header
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

  async function doFetch(monthStart, todayStr) {
    // 1. Fetch quota
    const quota = await apiGet('/api/query-quota?platform=codebuddy');
    const totalUsed = parseFloat(quota.total_used) || 0;
    const totalQuota = parseFloat(quota.total_quota) || 1000;

    // 2. Fetch today's usage summary (accurate aggregated total)
    let todayUsed = 0;
    try {
      const s1 = await apiGet(
        '/api/usage-summary?start_date=' + todayStr + '&end_date=' + todayStr +
        '&dimension=personal&platform=all'
      );
      if (s1 && s1.data) {
        for (const item of s1.data) {
          todayUsed += pc(item.cost);
        }
      }
    } catch(e) { /* summary fail is ok */ }

    window.postMessage({
      source: '__tpua_fetch',
      success: true,
      data: { totalUsed, totalQuota, todayUsed }
    }, '*');
  }

  // Listen for fetch triggers from the userscript sandbox
  window.addEventListener('message', function(e) {
    if (e.data && e.data.source === '__tpua_trigger') {
      try {
        doFetch(e.data.monthStart, e.data.todayStr);
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

    // Trigger fetch in main world
    window.postMessage({
      source: '__tpua_trigger',
      monthStart: todayStr.slice(0, 7) + '-01',
      todayStr
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
    const totalUsed = d.totalUsed;
    const totalQuota = d.totalQuota || 1000;
    const todayUsed = d.todayUsed;

    // Save cache (only needed for quick initial display on page reload)
    lastFetchTimestamp = Date.now();
    await GM_setValue(CACHE_KEY, {
      time: fmtTime(new Date()),
      spent: totalUsed,
      today_date: todayStr,
      today_used: todayUsed,
      month: todayStr.slice(0, 7),
      timestamp: lastFetchTimestamp,
    });

    // Calculate pacing
    const yd = new Date(), ym = yd.getMonth();
    const totalDays = new Date(yd.getFullYear(), ym + 1, 0).getDate();
    const monthEnd = new Date(yd.getFullYear(), ym, totalDays);
    const remainingWd = countWorkdays(yd, monthEnd);
    console.log('TokenPUA: today=' + fmtDate(yd) + ' monthEnd=' + fmtDate(monthEnd) + ' remainingWd=' + remainingWd);
    const pacing = calcPacing(totalUsed, totalQuota, remainingWd);

    return { pacing, todayUsed, timestamp: lastFetchTimestamp };
  }

  // ============================================================
  // Section 6: UI Renderer
  // ============================================================

  function renderBar(pct, color) {
    const c = color || (pct > 90 ? '#F44336' : pct > 70 ? '#FF9800' : '#4CAF50');
    return '<div class="tpua-bar-track"><div class="tpua-bar-fill" style="width:' + Math.min(pct, 100) + '%;background:' + c + '"></div></div>';
  }

  // 今日消耗速度 vs 时间进度 — 生成顶部提示语
  function getSpeedMessage(dayQuotaPct, dayPct, todayUsed, dailyQuota) {
    var ratio = dayPct > 1 ? dayQuotaPct / dayPct : dayQuotaPct;
    var msg, color;
    if (dayQuotaPct >= 200) {
      msg = '🚀 Token消耗坐上火箭了！';
      color = '#D32F2F';
    } else if (ratio > 1.5) {
      msg = '🔥 Token消耗速度太快了！';
      color = '#F44336';
    } else if (ratio > 1.0) {
      msg = '⚠️ Token消耗速度有点快，悠着点儿';
      color = '#FF9800';
    } else if (ratio > 0.7) {
      msg = '👍 今日额度还很宽裕，敞开用';
      color = '#4CAF50';
    } else if (ratio > 0.4) {
      msg = '💪 今日额度太宽裕了，敞开用！';
      color = '#2196F3';
    } else {
      msg = '🎉 Token不用留着过年吗？';
      color = '#9C27B0';
    }
    return {
      text: msg + '　　|　　今日已用' + dayQuotaPct.toFixed(0) + '%',
      color: color
    };
  }

  function renderExpanded(p, todayUsed, timestamp) {
    const now = new Date();
    const dayPct = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;
    const dayQuotaPct = p.dailyQuota > 0 ? (todayUsed / p.dailyQuota) * 100 : 0;
    const remaining = p.budget - p.spent;
    const speedMsg = getSpeedMessage(dayQuotaPct, dayPct, todayUsed, p.dailyQuota);

    // ── Header row ──
    var h = '<div class="tpua-header">' +
      '<div class="tpua-status" style="color:' + speedMsg.color + '">' +
        speedMsg.text +
      '</div>' +
      '<div class="tpua-header-actions">' +
        '<span class="tpua-refresh-inline" onclick="window.__tpuaRefresh()">🔄 ' + timeAgo(timestamp) + '</span>' +
        '<span class="tpua-header-btn" onclick="document.getElementById(\'tpua-panel\').remove()">×</span>' +
      '</div>' +
    '</div>';

    // ── Body: 3 blocks in a horizontal row ──
    h += '<div class="tpua-body">';

    // Block 1: 4 cards in a horizontal row
    h += '<div class="tpua-block">';
    h += '<div class="tpua-cards-row">';
    h += '<div class="tpua-card"><div class="tpua-card-val">' + p.remainingWd + '天</div><div class="tpua-card-label">剩余工作日</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + todayUsed.toFixed(1) + '</div><div class="tpua-card-label">今日已用</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + p.dailyQuota.toFixed(0) + '</div><div class="tpua-card-label">日额度</div></div>';
    h += '<div class="tpua-card"><div class="tpua-card-val">¥' + remaining.toFixed(0) + '</div><div class="tpua-card-label">剩余总额</div></div>';
    h += '</div>'; // cards-row
    h += '</div>'; // block 1

    // Block 2: day progress
    h += '<div class="tpua-block tpua-block-progress">';
    h += '<div class="tpua-section-title">日进度</div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">额度</span>' + renderBar(Math.min(dayQuotaPct, 100)) + '<span class="tpua-bar-num">' + dayQuotaPct.toFixed(0) + '%  ¥' + todayUsed.toFixed(1) + '/¥' + p.dailyQuota.toFixed(0) + '</span></div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">时间</span>' + renderBar(dayPct, '#8888cc') + '<span class="tpua-bar-num">' + dayPct.toFixed(0) + '%  ' + String(now.getHours()).padStart(2,'0') + ':' + String(now.getMinutes()).padStart(2,'0') + '/24:00</span></div>';
    h += '</div>'; // block 2

    // Block 3: month progress
    h += '<div class="tpua-block tpua-block-progress">';
    h += '<div class="tpua-section-title">月进度</div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">额度</span>' + renderBar(p.pct) + '<span class="tpua-bar-num">' + p.pct.toFixed(0) + '%  ¥' + p.spent.toFixed(0) + '/¥' + p.budget.toFixed(0) + '</span></div>';
    h += '<div class="tpua-bar-row"><span class="tpua-bar-label">时间</span>' + renderBar(p.monthElapsedPct, '#8888cc') + '<span class="tpua-bar-num">' + p.monthElapsedPct.toFixed(0) + '%  ' + now.getDate() + '/' + p.totalDays + '天</span></div>';
    h += '</div>'; // block 3

    h += '</div>'; // body

    // ── Warning (if any) ──
    if (p.warning) {
      h += '<div class="tpua-warning">⚠️ ' + p.warning + '</div>';
    }

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
      renderExpanded(p, cache.today_used || 0, cache.timestamp || Date.now());
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
      const data = await fetchAllData();

      if (data.pacing.budget <= 0) {
        data.pacing.budget = 1000;
        data.pacing.pct = data.pacing.spent / 1000 * 100;
      }

      panel.innerHTML = renderExpanded(data.pacing, data.todayUsed, data.timestamp);
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
    panel.innerHTML = '加载中...';
    document.body.appendChild(panel);
    console.log('TokenPUA: panel injected');

    window.__tpuaRefresh = refreshData;
  }

  // ============================================================
  // Section 9: Styles
  // ============================================================

  function injectStyles() {
    const css = [
      '#tpua-panel{position:fixed;top:90px;left:10px;right:10px;z-index:2147483647;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;font-size:15px;color:#e0e0e0;background:rgba(26,26,46,0.95);backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.08);border-radius:10px;box-shadow:0 8px 32px rgba(0,0,0,0.4);user-select:none;max-width:1200px;margin:0 auto}',
      '#tpua-panel .tpua-header{display:flex;align-items:center;justify-content:space-between;padding:12px 18px;border-bottom:1px solid rgba(255,255,255,0.06)}',
      '#tpua-panel .tpua-status{font-weight:600;font-size:18px}',
      '#tpua-panel .tpua-header-actions{display:flex;align-items:center;gap:12px}',
      '#tpua-panel .tpua-refresh-inline{cursor:pointer;font-size:14px;color:#aaa}',
      '#tpua-panel .tpua-refresh-inline:hover{color:#fff}',
      '#tpua-panel .tpua-header-btn{cursor:pointer;opacity:0.5;font-size:20px;padding:0 6px;border-radius:4px}',
      '#tpua-panel .tpua-header-btn:hover{opacity:1;background:rgba(255,255,255,0.1)}',
      '#tpua-panel .tpua-body{display:flex;flex-direction:row;gap:0;align-items:stretch}',
      '#tpua-panel .tpua-block{padding:14px 18px;display:flex;flex-direction:column;justify-content:center;flex:1;min-width:0}',
      '#tpua-panel .tpua-block-progress{align-items:stretch}',
      '#tpua-panel .tpua-block-progress .tpua-section-title{width:100%}',
      '#tpua-panel .tpua-block-progress .tpua-bar-row{width:100%}',
      '#tpua-panel .tpua-block+.tpua-block{border-left:1px solid rgba(255,255,255,0.06)}',
      '#tpua-panel .tpua-cards-row{display:flex;flex-direction:row;gap:8px;justify-content:center;width:100%}',
      '#tpua-panel .tpua-card{background:rgba(255,255,255,0.04);border-radius:6px;padding:12px 16px;text-align:center;flex:1;min-width:0;white-space:nowrap}',
      '#tpua-panel .tpua-card-val{font-size:17px;font-weight:700}',
      '#tpua-panel .tpua-card-label{font-size:14px;color:#888;margin-top:3px}',
      '#tpua-panel .tpua-section-title{padding:0 0 10px;font-size:13px;color:#888;text-transform:uppercase;letter-spacing:0.5px}',
      '#tpua-panel .tpua-bar-row{display:flex;align-items:center;padding:4px 0;gap:10px}',
      '#tpua-panel .tpua-bar-label{width:36px;font-size:14px;color:#888;text-align:right;flex-shrink:0}',
      '#tpua-panel .tpua-bar-track{flex:1;height:16px;background:rgba(255,255,255,0.06);border-radius:8px;overflow:hidden}',
      '#tpua-panel .tpua-bar-fill{height:100%;border-radius:8px;transition:width 0.4s ease}',
      '#tpua-panel .tpua-bar-num{font-size:14px;color:#aaa;white-space:nowrap;min-width:110px;text-align:left;padding-left:6px}',
      '#tpua-panel .tpua-warning{margin:0 16px 10px;padding:8px 12px;background:rgba(255,107,107,0.1);border:1px solid rgba(255,107,107,0.2);border-radius:6px;font-size:12px;color:#FF6B6B}',
      '#tpua-panel .tpua-error{padding:12px 16px;color:#FF6B6B;font-size:14px;text-align:center}',
      '#tpua-panel .tpua-error-sub{margin-top:4px;font-size:13px;color:#888}',
      '#tpua-panel .tpua-error-bar{padding:8px 16px;font-size:13px;color:#FF9800;text-align:center}',
      '#tpua-panel::-webkit-scrollbar{width:4px}',
      '#tpua-panel::-webkit-scrollbar-track{background:transparent}',
      '#tpua-panel::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:2px}',
      '@keyframes tpua-spin{to{transform:rotate(360deg)}}',
      '#tpua-panel .tpua-spinner{display:inline-block;width:14px;height:14px;border:2px solid rgba(255,255,255,0.1);border-top-color:#4CAF50;border-radius:50%;animation:tpua-spin 0.6s linear infinite;margin-right:6px}',
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
      var rwd = countWorkdays(now, monthEnd) || 10;
      var p = calcPacing(cache.spent, cache.spent > 0 ? Math.max(cache.spent / 0.5, 1000) : 1000, rwd);
      if (!cache.budget) {
        p.budget = cache.spent > 0 ? Math.max(cache.spent * 1.5, 1000) : 1000;
        p.pct = p.spent / p.budget * 100;
      }
      panel.innerHTML = renderExpanded(p, cache.today_used || 0, cache.timestamp || Date.now());
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
