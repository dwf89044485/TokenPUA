// TokenPUA MAIN world — runs in page context, has correct Origin
const BASE = 'https://token.woa.com';

let isFetching = false;

async function fetchAll() {
  if (isFetching) return;
  isFetching = true;
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
    } catch (e) {}

    let todayUsed = 0;
    if (usage && usage.data) {
      for (const item of usage.data) {
        todayUsed += parseFloat(String(item.cost || '0').replace(/[¥,]/g, '')) || 0;
      }
    }

    const records = [];
    if (d && d.data) {
      for (const rec of d.data) {
        const cost = parseFloat(String(rec.cost || '0').replace(/[¥,]/g, '')) || 0;
        const ts = String(rec.total_tokens || '0').replace(/,/g, '');
        records.push({ time: (rec.request_time || '').slice(0, 16), model: rec.model_name || '-', cost, total_tokens: parseInt(ts) || 0 });
      }
    }

    window.postMessage({
      source: '__tpua_fetch',
      success: true,
      data: {
        totalUsed: parseFloat(quota.total_used) || 0,
        totalQuota: parseFloat(quota.total_quota) || 1000,
        todayUsed,
        records,
        timestamp: Date.now(),
      }
    }, '*');
  } catch (e) {
    window.postMessage({ source: '__tpua_fetch', success: false, error: e.message }, '*');
  } finally {
    isFetching = false;
  }
}

// Listen for requests from bridge
window.addEventListener('message', (e) => {
  if (e.data && e.data.source === '__tpua_bridge' && e.data.action === 'fetch') {
    fetchAll();
  }
});

// Auto-fetch on page load
fetchAll();
