// TokenPUA Chrome Extension — Background Service Worker
const BASE_URL = 'https://token.woa.com';
const REFRESH_INTERVAL = 3; // 分钟
const REMAINING_WD_WARNING = 5;
const HIGH_SPEND_THRESHOLD = 100.0;

// ─── 工作日计算 ─────────────────────────
function countWorkdays(start, end) {
  let d = new Date(start);
  let n = 0;
  while (d <= end) {
    const day = d.getDay();
    if (day >= 1 && day <= 5) n++;
    d.setDate(d.getDate() + 1);
  }
  return n;
}

// ─── Pacing 计算 ─────────────────────────
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

  let icon, text;
  if (ratio > 1.3) { icon = '\u{1F7E5}'; text = '加速'; }
  else if (ratio > 1.1) { icon = '\u{1F7E1}'; text = '稍加速'; }
  else if (ratio > 0.9) { icon = '\u{1F7E2}'; text = '完美'; }
  else if (ratio > 0.7) { icon = '\u{1F7E1}'; text = '可放缓'; }
  else { icon = '\u{1F535}'; text = '省着用'; }

  let warning = null;
  if (remainingWd <= REMAINING_WD_WARNING && (budget - spent) > HIGH_SPEND_THRESHOLD) {
    warning = `还剩 ¥${(budget - spent).toFixed(0)}，仅剩 ${remainingWd} 个工作日`;
  }

  return { spent, budget, pct: spent / budget * 100, dailyQuota, statusIcon: icon, statusText: text, warning, remainingWd, totalDays, monthElapsedPct };
}

// ─── 通过 chrome.cookies API 获取 Cookie 字符串 ───
function buildCookieString() {
  return new Promise((resolve, reject) => {
    // 同时从 token.woa.com 和 .woa.com 读取 cookie
    chrome.cookies.getAll({ domain: 'token.woa.com' }, (tokenCookies) => {
      chrome.cookies.getAll({ domain: '.woa.com' }, (woaCookies) => {
        if (chrome.runtime.lastError) {
          reject(chrome.runtime.lastError);
          return;
        }
        const all = [...(tokenCookies || []), ...(woaCookies || [])];
        // 去重：同名 cookie 取第一个（浏览器按精确域名优先）
        const seen = new Set();
        const pairs = [];
        for (const c of all) {
          // .woa.com 的 cookie 优先 token.woa.com（order: token.woa.com > .woa.com 具体子域 > .woa.com）
          const key = c.name;
          if (seen.has(key)) {
            // 已存在同名 cookie，如果当前是 token.woa.com 的则替换（更精确）
            const idx = pairs.findIndex(p => p.name === key);
            if (idx !== -1 && c.domain === 'token.woa.com') {
              pairs[idx] = c;
            }
            continue;
          }
          seen.add(key);
          pairs.push(c);
        }
        // 按名称拼接成 Cookie 字符串
        const cookieStr = pairs.map(c => `${c.name}=${c.value}`).join('; ');
        resolve(cookieStr);
      });
    });
  });
}

// ─── 数据获取 ───────────────────────────
async function fetchWithCookie(url, cookieStr) {
  const resp = await fetch(url, {
    credentials: 'omit', // 不用默认 cookie，我们手动传递
    headers: { 'Cookie': cookieStr, 'User-Agent': 'TokenPUA/1.0' }
  });
  if (!resp.ok) {
    const body = await resp.text().catch(() => '');
    throw new Error(`HTTP ${resp.status}: ${body.slice(0, 100)}`);
  }
  return resp.json();
}

async function fetchAll() {
  const cookieStr = await buildCookieString();
  if (!cookieStr) {
    throw new Error('未获取到登录 Cookie，请先登录 token.woa.com');
  }

  const todayStr = new Date().toISOString().slice(0, 10);
  const monthStart = todayStr.slice(0, 7) + '-01';

  const [quota, usage, details] = await Promise.all([
    fetchWithCookie(`${BASE_URL}/api/query-quota?platform=codebuddy`, cookieStr),
    fetchWithCookie(`${BASE_URL}/api/usage-summary?start_date=${todayStr}&end_date=${todayStr}&dimension=personal&platform=all`, cookieStr),
    fetchWithCookie(`${BASE_URL}/api/usage-details?start_date=${monthStart}&end_date=${todayStr}&dimension=all&page=1&page_size=50&platform=all`, cookieStr).catch(() => null),
  ]);

  // 计算今日消耗
  let todayUsed = 0;
  if (usage && usage.data) {
    for (const item of usage.data) {
      todayUsed += parseFloat(String(item.cost || '0').replace(/[¥,]/g, '')) || 0;
    }
  }

  const totalUsed = parseFloat(quota.total_used) || 0;
  const totalQuota = parseFloat(quota.total_quota) || 1000;

  // 解析记录
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
        user_input: (rec.user_input || '').slice(0, 100),
      });
    }
  }

  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthEnd = new Date(year, month, totalDays);
  const remainingWd = countWorkdays(today, monthEnd);

  const pacing = calcPacing(totalUsed, totalQuota, remainingWd);

  return { pacing, todayUsed, records, timestamp: Date.now() };
}

// ─── Badge 更新 ─────────────────────────
function updateBadge(data) {
  const pct = Math.round(data.pacing.pct);
  const text = `${pct}%`;
  let color = '#4CAF50';
  if (pct > 90) color = '#F44336';
  else if (pct > 70) color = '#FF9800';

  chrome.action.setBadgeText({ text });
  chrome.action.setBadgeBackgroundColor({ color });
}

// ─── 刷新流程 ───────────────────────────
async function refresh() {
  try {
    const data = await fetchAll();
    await chrome.storage.local.set({ tokenPuaData: data });
    updateBadge(data);
    return true;
  } catch (e) {
    console.error('TokenPUA refresh failed:', e.message);
    return false;
  }
}

// ─── 生命周期 ───────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', { periodInMinutes: REFRESH_INTERVAL });
  refresh();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refresh') refresh();
});
