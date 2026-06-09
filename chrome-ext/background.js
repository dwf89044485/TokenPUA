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

// ─── 数据获取 ───────────────────────────
async function fetchAll() {
  const todayStr = new Date().toISOString().slice(0, 10);
  const monthStart = todayStr.slice(0, 7) + '-01';

  // 并行请求
  const [quotaRes, usageRes] = await Promise.all([
    fetch(`${BASE_URL}/api/query-quota?platform=codebuddy`, { credentials: 'include' }),
    fetch(`${BASE_URL}/api/usage-summary?start_date=${todayStr}&end_date=${todayStr}&dimension=personal&platform=all`, { credentials: 'include' }),
  ]);

  if (!quotaRes.ok || !usageRes.ok) {
    const e1 = await quotaRes.text().catch(() => '');
    const e2 = await usageRes.text().catch(() => '');
    throw new Error(`API error: quota=${quotaRes.status} usage=${usageRes.status}`);
  }

  const quota = await quotaRes.json();
  const usage = await usageRes.json();

  // 计算今日消耗
  let todayUsed = 0;
  if (usage && usage.data) {
    for (const item of usage.data) {
      const cost = parseFloat(String(item.cost || '0').replace(/[¥,]/g, '')) || 0;
      todayUsed += cost;
    }
  }

  const totalUsed = parseFloat(quota.total_used) || 0;
  const totalQuota = parseFloat(quota.total_quota) || 1000;

  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthEnd = new Date(year, month, totalDays);
  const remainingWd = countWorkdays(today, monthEnd);

  const pacing = calcPacing(totalUsed, totalQuota, remainingWd);

  return { pacing, todayUsed, timestamp: Date.now() };
}

// ─── Badge 更新 ─────────────────────────
function updateBadge(data) {
  const pct = Math.round(data.pacing.pct);
  const text = `${pct}%`;
  let color = '#4CAF50'; // 绿
  if (pct > 90) color = '#F44336'; // 红
  else if (pct > 70) color = '#FF9800'; // 橙

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
    console.error('TokenPUA refresh failed:', e);
    // 保留旧数据，不更新 badge
    return false;
  }
}

// ─── 生命周期 ───────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', { periodInMinutes: REFRESH_INTERVAL });
  refresh(); // 立即刷新一次
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refresh') refresh();
});
