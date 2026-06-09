// TokenPUA Chrome Extension — Background Service Worker
const REFRESH_INTERVAL = 3; // 分钟
const TOKEN_URL = 'https://token.woa.com/';
const REMAINING_WD_WARNING = 5;
const HIGH_SPEND_THRESHOLD = 100.0;
const TAB_TIMEOUT = 15000; // 隐藏标签页最长等待

// ─── 工作日计算 ─────────────────────────
function countWorkdays(start, end) {
  let d = new Date(start);
  let n = 0;
  while (d <= end) {
    if (d.getDay() >= 1 && d.getDay() <= 5) n++;
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

function buildPacedData(raw) {
  const today = new Date();
  const year = today.getFullYear();
  const month = today.getMonth();
  const totalDays = new Date(year, month + 1, 0).getDate();
  const monthEnd = new Date(year, month, totalDays);
  const remainingWd = countWorkdays(today, monthEnd);
  const pacing = calcPacing(raw.totalUsed, raw.totalQuota, remainingWd);
  return { pacing, todayUsed: raw.todayUsed, records: raw.records, timestamp: Date.now() };
}

// ─── Badge 更新 ─────────────────────────
function updateBadge(data) {
  const pct = Math.round(data.pacing.pct);
  let color = '#4CAF50';
  if (pct > 90) color = '#F44336';
  else if (pct > 70) color = '#FF9800';
  chrome.action.setBadgeText({ text: `${pct}%` });
  chrome.action.setBadgeBackgroundColor({ color });
}

// ─── 通过隐藏标签页获取数据 ─────────────
let pendingTabId = null;

async function fetchViaHiddenTab() {
  // 先检查有没有已经打开的 token.woa.com 标签页
  const tabs = await chrome.tabs.query({ url: 'https://token.woa.com/*' });
  if (tabs.length > 0) {
    // 已有标签页，直接发消息给它
    return sendMessageToTab(tabs[0].id);
  }

  // 创建一个隐藏标签页
  const tab = await chrome.tabs.create({
    url: TOKEN_URL,
    active: false,  // 不会跳到该标签页
  });
  pendingTabId = tab.id;

  try {
    return await sendMessageToTab(tab.id);
  } finally {
    // 如果是我们创建的标签页，关闭它
    if (pendingTabId === tab.id) {
      try { chrome.tabs.remove(tab.id); } catch (e) {}
      pendingTabId = null;
    }
  }
}

function sendMessageToTab(tabId) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error('Content script 无响应（超时）'));
    }, TAB_TIMEOUT);

    chrome.tabs.sendMessage(tabId, { action: 'fetchTokenData' }, (response) => {
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (!response || !response.success) {
        reject(new Error(response?.error || '未知错误'));
        return;
      }
      resolve(response.data);
    });
  });
}

// ─── 内容脚本就绪通知（用户正常访问时触发）──
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg.action === 'contentScriptReady' && sender.tab) {
    // 用户正常打开 token.woa.com，立即刷新一次数据
    chrome.tabs.sendMessage(sender.tab.id, { action: 'fetchTokenData' }, (response) => {
      if (response?.success) {
        const data = buildPacedData(response.data);
        chrome.storage.local.set({ tokenPuaData: data });
        updateBadge(data);
      }
    });
  }
});

// ─── 定时刷新 ───────────────────────────
async function refresh() {
  try {
    const raw = await fetchViaHiddenTab();
    const data = buildPacedData(raw);
    await chrome.storage.local.set({ tokenPuaData: data });
    updateBadge(data);
  } catch (e) {
    console.error('TokenPUA refresh failed:', e.message);
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create('refresh', { periodInMinutes: REFRESH_INTERVAL });
  refresh();
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'refresh') refresh();
});
