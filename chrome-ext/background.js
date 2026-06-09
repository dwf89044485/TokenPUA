// TokenPUA Chrome Extension — Background Service Worker
const REFRESH_INTERVAL = 3;
const REMAINING_WD_WARNING = 5;
const HIGH_SPEND_THRESHOLD = 100.0;
const STALE_AFTER_MS = 10 * 60 * 1000; // 10分钟无更新视为过期

function countWorkdays(start, end) {
  let d = new Date(start), n = 0;
  while (d <= end) { if (d.getDay() >= 1 && d.getDay() <= 5) n++; d.setDate(d.getDate() + 1); }
  return n;
}

function calcPacing(spent, budget, remainingWd) {
  const today = new Date(), year = today.getFullYear(), month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthElapsedPct = (today.getDate() / totalDays) * 100;
  const dailyQuota = (budget - spent) / Math.max(remainingWd, 1);
  const monthStart = new Date(year, month, 1), monthEnd = new Date(year, month + 1, 0);
  const totalWd = countWorkdays(monthStart, monthEnd);
  // 已用工作日：从月初到今天（含今日）
  const elapsedWd = countWorkdays(monthStart, today);
  const idealDaily = budget / Math.max(totalWd, 1);
  const ratio = idealDaily >= 0.01 ? (spent / Math.max(elapsedWd, 1)) / idealDaily : 999;
  let icon, text;
  if (ratio > 1.3) { icon = '\u{1F7E5}'; text = '加速'; }
  else if (ratio > 1.1) { icon = '\u{1F7E1}'; text = '稍加速'; }
  else if (ratio > 0.9) { icon = '\u{1F7E2}'; text = '完美'; }
  else if (ratio > 0.7) { icon = '\u{1F7E1}'; text = '可放缓'; }
  else { icon = '\u{1F535}'; text = '省着用'; }
  let warning = null;
  if (remainingWd <= REMAINING_WD_WARNING && (budget - spent) > HIGH_SPEND_THRESHOLD)
    warning = `还剩 ¥${(budget - spent).toFixed(0)}，仅剩 ${remainingWd} 个工作日`;
  return { spent, budget, pct: spent / budget * 100, dailyQuota, statusIcon: icon, statusText: text, warning, remainingWd, totalDays, monthElapsedPct };
}

function buildPacedData(raw) {
  const today = new Date(), year = today.getFullYear(), month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  // remainingWd: 从明天到月底（不含今日，今日已在 elapsedWd 中）
  const tomorrow = new Date(today.getFullYear(), today.getMonth(), today.getDate() + 1);
  const monthEnd = new Date(year, month, totalDays);
  const remainingWd = countWorkdays(tomorrow, monthEnd);
  const stale = Date.now() - raw.timestamp > STALE_AFTER_MS;
  return {
    pacing: calcPacing(raw.totalUsed, raw.totalQuota, remainingWd),
    todayUsed: raw.todayUsed, records: raw.records, timestamp: raw.timestamp, stale
  };
}

function updateBadge(data) {
  const pct = Math.round(data.pacing.pct);
  let color = '#4CAF50';
  if (pct > 90) color = '#F44336';
  else if (pct > 70) color = '#FF9800';
  chrome.action.setBadgeText({ text: `${pct}%` });
  chrome.action.setBadgeBackgroundColor({ color });
}

// ─── 接收 Content Script 结果 ────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'fetchResult') {
    if (msg.success && msg.data) {
      const data = buildPacedData(msg.data);
      chrome.storage.local.set({ tokenPuaData: data, tokenPuaError: null });
      updateBadge(data);
    } else {
      chrome.storage.local.set({ tokenPuaError: msg.error || '未知错误' });
    }
    return;
  }
  if (msg.action === 'contentScriptReady' && sender.tab) {
    chrome.tabs.sendMessage(sender.tab.id, { action: 'fetchTokenData' }).catch(() => {});
  }
});

// ─── 定时刷新 ───────────────────────────
async function refresh() {
  try {
    const tabs = await chrome.tabs.query({ url: 'https://token.woa.com/*' });
    if (tabs.length === 0) return;
    for (const tab of tabs) {
      try {
        await chrome.tabs.sendMessage(tab.id, { action: 'fetchTokenData' });
        return;
      } catch (e) { continue; }
    }
  } catch (e) {
    console.error('TokenPUA refresh:', e.message);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', { periodInMinutes: REFRESH_INTERVAL });
  refresh();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refresh') refresh();
});
