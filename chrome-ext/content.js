// TokenPUA Content Script — injects fetch logic into MAIN world
// Content Script 的 fetch() 的 Origin 是 chrome-extension://...，
// 只有在页面 MAIN world 中执行 fetch 才能拿到正确 Origin

function injectMainWorldFetch() {
  if (document.getElementById('__tpua_script')) return;

  const script = document.createElement('script');
  script.id = '__tpua_script';
  script.textContent = `
(function() {
  const BASE = 'https://token.woa.com';
  window.__tpuaFetch = async function() {
    try {
      const today = new Date().toISOString().slice(0, 10);
      const ms = today.slice(0, 7) + '-01';

      const q = await fetch(BASE + '/api/query-quota?platform=codebuddy', { credentials: 'include' });
      if (!q.ok) throw new Error('quota: ' + q.status);
      const quota = await q.json();

      const u = await fetch(BASE + '/api/usage-summary?start_date=' + today + '&end_date=' + today + '&dimension=personal&platform=all', { credentials: 'include' });
      if (!u.ok) throw new Error('usage: ' + u.status);
      const usage = await u.json();

      let d = null;
      try {
        const dr = await fetch(BASE + '/api/usage-details?start_date=' + ms + '&end_date=' + today + '&dimension=all&page=1&page_size=50&platform=all', { credentials: 'include' });
        if (dr.ok) d = await dr.json();
      } catch(e) {}

      let todayUsed = 0;
      if (usage && usage.data) {
        for (const item of usage.data) {
          todayUsed += parseFloat(String(item.cost || '0').replace(/[¥,]/g, '')) || 0;
        }
      }

      const totalUsed = parseFloat(quota.total_used) || 0;
      const totalQuota = parseFloat(quota.total_quota) || 1000;

      const records = [];
      if (d && d.data) {
        for (const rec of d.data) {
          const cost = parseFloat(String(rec.cost || '0').replace(/[¥,]/g, '')) || 0;
          const ts = String(rec.total_tokens || '0').replace(/,/g, '');
          records.push({ time: (rec.request_time || '').slice(0, 16), model: rec.model_name || '-', cost, total_tokens: parseInt(ts) || 0 });
        }
      }

      window.dispatchEvent(new CustomEvent('__tpua_result', { detail: JSON.stringify({ success: true, data: { totalUsed, totalQuota, todayUsed, records, timestamp: Date.now() } }) }));
    } catch(e) {
      window.dispatchEvent(new CustomEvent('__tpua_result', { detail: JSON.stringify({ success: false, error: e.message }) }));
    }
  };
})();
`;
  document.documentElement.appendChild(script);
}

// ─── 监听 MAIN world 事件 ────────────────
window.addEventListener('__tpua_result', (e) => {
  const result = JSON.parse(e.detail);
  // 通知后台
  chrome.runtime.sendMessage({ action: 'fetchResult', ...result });
});

// ─── 消息处理（后台请求 fetch）────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'fetchTokenData') {
    injectMainWorldFetch();
    // 在 MAIN world 中执行 fetch
    const s = document.createElement('script');
    s.textContent = 'window.__tpuaFetch()';
    document.documentElement.appendChild(s);
    sendResponse({ success: true, msg: 'fetch started' });
  }
});

// 页面加载后初始化
injectMainWorldFetch();
chrome.runtime.sendMessage({ action: 'contentScriptReady' });
