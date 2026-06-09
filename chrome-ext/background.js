// TokenPUA Chrome Extension — Background Service Worker
const REFRESH_INTERVAL = 3;
const REMAINING_WD_WARNING = 5;
const HIGH_SPEND_THRESHOLD = 100.0;

function countWorkdays(start, end) {
  let d = new Date(start), n = 0;
  while (d <= end) { if (d.getDay() >= 1 && d.getDay() <= 5) n++; d.setDate(d.getDate() + 1); }
  return n;
}

function calcPacing(spent, budget, remainingWd) {
  const today = new Date();
  const year = today.getFullYear(), month = today.getMonth();
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
  if (remainingWd <= REMAINING_WD_WARNING && (budget - spent) > HIGH_SPEND_THRESHOLD) { warning = `还剩 ¥${(budget - spent).toFixed(0)}，仅剩 ${remainingWd} 个工作日`; }
  return { spent, budget, pct: spent / budget * 100, dailyQuota, statusIcon: icon, statusText: text, warning, remainingWd, totalDays, monthElapsedPct };
}

function buildPacedData(raw) {
  const today = new Date();
  const year = today.getFullYear(), month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthEnd = new Date(year, month, totalDays);
  const remainingWd = countWorkdays(today, monthEnd);
  return { pacing: calcPacing(raw.totalUsed, raw.totalQuota, remainingWd), todayUsed: raw.todayUsed, records: raw.records, timestamp: Date.now() };
}

function updateBadge(data) {
  const pct = Math.round(data.pacing.pct);
  let color = '#4CAF50';
  if (pct > 90) color = '#F44336';
  else if (pct > 70) color = '#FF9800';
  chrome.action.setBadgeText({ text: `${pct}%` });
  chrome.action.setBadgeBackgroundColor({ color });
}

// ─── 从 Content Script 接收数据 ──────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // 内容脚本通知：页面已就绪，询问是否需要刷新
  if (msg.action === 'contentScriptReady') {
    // 此时 sender.tab 存在，说明 Content Script 运行在真实页面上
    // 尝试通过它获取数据
    chrome.tabs.sendMessage(sender.tab.id, { action: 'fetchTokenData' }, (response) => {
      if (response?.success) {
        const data = buildPacedData(response.data);
        chrome.storage.local.set({ tokenPuaData: data });
        updateBadge(data);
      }
    });
    return;
  }

  // 内容脚本返回的 fetch 结果
  if (msg.action === 'fetchResult' && msg.data) {
    const data = buildPacedData(msg.data);
    chrome.storage.local.set({ tokenPuaData: data });
    updateBadge(data);
  }
});

// ─── 定时刷新：通过已有标签页拉数据 ──────
async function refresh() {
  const tabs = await chrome.tabs.query({ url: 'https://token.woa.com/*' });
  if (tabs.length === 0) {
    console.warn('TokenPUA: 没有打开的 token.woa.com 页面，跳过刷新');
    return;
  }
  // 向所有打开的 token.woa.com 标签页发送请求
  for (const tab of tabs) {
    try {
      const resp = await chrome.tabs.sendMessage(tab.id, { action: 'fetchTokenData' });
      if (resp?.success) {
        const data = buildPacedData(resp.data);
        await chrome.storage.local.set({ tokenPuaData: data });
        updateBadge(data);
        return; // 成功一次就够了
      }
    } catch (e) {
      // 该标签页可能还没加载完 Content Script，跳过
      continue;
    }
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', { periodInMinutes: REFRESH_INTERVAL });
  refresh();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refresh') refresh();
});
