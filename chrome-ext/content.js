// TokenPUA Content Script — runs on token.woa.com pages
// 在同源页面上下文中调用 API（Cookie 自动携带）

const BASE_URL = 'https://token.woa.com';

async function fetchApi(path) {
  const resp = await fetch(`${BASE_URL}${path}`, {
    credentials: 'include',
    headers: { 'Accept': 'application/json, text/plain, */*' }
  });
  const body = await resp.text();
  if (!resp.ok || body.startsWith('<')) {
    throw new Error(`HTTP ${resp.status}: ${body.slice(0, 100)}`);
  }
  return JSON.parse(body);
}

async function fetchAll() {
  const todayStr = new Date().toISOString().slice(0, 10);
  const monthStart = todayStr.slice(0, 7) + '-01';

  const [quota, usage, details] = await Promise.all([
    fetchApi(`/api/query-quota?platform=codebuddy`),
    fetchApi(`/api/usage-summary?start_date=${todayStr}&end_date=${todayStr}&dimension=personal&platform=all`),
    fetchApi(`/api/usage-details?start_date=${monthStart}&end_date=${todayStr}&dimension=all&page=1&page_size=50&platform=all`).catch(() => null),
  ]);

  let todayUsed = 0;
  if (usage && usage.data) {
    for (const item of usage.data) {
      todayUsed += parseFloat(String(item.cost || '0').replace(/[¥,]/g, '')) || 0;
    }
  }

  const totalUsed = parseFloat(quota.total_used) || 0;
  const totalQuota = parseFloat(quota.total_quota) || 1000;

  const records = [];
  if (details && details.data) {
    for (const rec of details.data) {
      const cost = parseFloat(String(rec.cost || '0').replace(/[¥,]/g, '')) || 0;
      const totalStr = String(rec.total_tokens || '0').replace(/,/g, '');
      records.push({
        time: (rec.request_time || '').slice(0, 16),
        model: rec.model_name || '-',
        cost,
        total_tokens: parseInt(totalStr) || 0,
      });
    }
  }

  return { quota, usage, details, todayUsed, totalUsed, totalQuota, records, timestamp: Date.now() };
}

// ─── 监听后台请求 ─────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'fetchTokenData') {
    fetchAll()
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true; // 异步响应
  }
});

// 页面加载后自动发一次（如果用户正常访问 token.woa.com 时）
chrome.runtime.sendMessage({ action: 'contentScriptReady' });
