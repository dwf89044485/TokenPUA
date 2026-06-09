// TokenPUA Chrome Extension — Popup
const MODEL_ALIASES = { 'DeepSeek': 'DS' };

function timeAgo(timestamp) {
  const diff = Date.now() - timestamp;
  if (diff < 60000) return '刚刚更新';
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前更新`;
  return `${Math.floor(diff / 3600000)}小时前更新`;
}

function ansiBar(pct) {
  let color;
  if (pct > 90) color = '#F44336';
  else if (pct > 70) color = '#FF9800';
  else color = '#4CAF50';
  return `<div class="bar-track"><div class="bar-fill" style="width:${Math.min(pct, 100)}%;background:${color}"></div></div>`;
}

function formatCost(cost) {
  if (cost > 100) return 'high';
  if (cost > 50) return 'medium';
  if (cost < 0.0005) return 'low';
  return '';
}

function render(data) {
  const { pacing, todayUsed, records, timestamp, stale } = data;
  const { spent, budget, pct, dailyQuota, statusIcon, statusText, warning, remainingWd, totalDays, monthElapsedPct } = pacing;
  const now = new Date();
  const dayPct = ((now.getHours() * 60 + now.getMinutes()) / 1440) * 100;
  const dayQuotaPct = (todayUsed / dailyQuota) * 100;

  let html = '';

  // Header with stale warning
  const staleNotice = stale ? ' ⚠️ 数据可能已过期' : '';
  html += `<div class="header">
    <div class="status">${statusIcon} ¥${spent.toFixed(0)}/¥${budget.toFixed(0)} · ${statusText}${staleNotice}</div>
    <div class="time-label">${timeAgo(timestamp)}</div>
  </div>`;

  // Month progress
  html += `<div class="section-title">月进度</div>`;
  html += `<div class="bar-container">
    <div class="bar-label">额度</div>
    ${ansiBar(pct)}
    <div class="bar-text">${pct.toFixed(0)}%  ¥${spent.toFixed(0)}/¥${budget.toFixed(0)}</div>
  </div>`;
  html += `<div class="bar-container">
    <div class="bar-label">时间</div>
    ${ansiBar(monthElapsedPct)}
    <div class="bar-text">${monthElapsedPct.toFixed(0)}%  ${now.getDate()}/${totalDays}天</div>
  </div>`;

  // Day progress
  html += `<div class="section-title">日进度</div>`;
  html += `<div class="bar-container">
    <div class="bar-label">额度</div>
    ${ansiBar(Math.min(dayQuotaPct, 100))}
    <div class="bar-text">${Math.min(dayQuotaPct, 100).toFixed(0)}%  ¥${todayUsed.toFixed(1)}/¥${dailyQuota.toFixed(0)}</div>
  </div>`;
  html += `<div class="bar-container">
    <div class="bar-label">时间</div>
    ${ansiBar(dayPct)}
    <div class="bar-text">${dayPct.toFixed(0)}%  ${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}/24:00</div>
  </div>`;

  // Details grid
  html += `<div class="details-grid">
    <div class="detail-card">
      <div class="value">¥${dailyQuota.toFixed(0)}</div>
      <div class="label">目标日均消耗</div>
    </div>
    <div class="detail-card">
      <div class="value">${remainingWd}</div>
      <div class="label">剩余工作日</div>
    </div>
    <div class="detail-card">
      <div class="value">¥${(budget - spent).toFixed(0)}</div>
      <div class="label">剩余总额</div>
    </div>
    <div class="detail-card">
      <div class="value">¥${todayUsed.toFixed(1)}</div>
      <div class="label">今日已用</div>
    </div>
  </div>`;

  // Warning
  if (warning) {
    html += `<div class="warning">⚠️ ${warning}</div>`;
  }

  // Records
  if (data.records && data.records.length > 0) {
    html += `<div class="section-title">近期消费记录</div>`;
    html += `<div class="records-table">`;
    for (const rec of data.records) {
      let model = rec.model;
      for (const [prefix, alias] of Object.entries(MODEL_ALIASES)) {
        if (model.startsWith(prefix)) { model = alias + model.slice(prefix.length); break; }
      }
      if (model.startsWith('Claude-')) model = model.slice(7);
      model = model.slice(0, 18);

      const timeStr = rec.time.length >= 16 ? rec.time.slice(11, 16) : rec.time;
      const costStr = `¥${rec.cost.toFixed(3)}`;
      const tokenStr = rec.total_tokens.toLocaleString();
      const costClass = formatCost(rec.cost);

      html += `<div class="record-row">
        <span>${timeStr}  ${costStr}</span>
        <span class="cost ${costClass}">${model}  ${tokenStr}</span>
      </div>`;
    }
    html += `</div>`;
  }

  document.getElementById('app').innerHTML = html;
}

function showError(msg) {
  document.getElementById('app').innerHTML = `
    <div class="error-state">
      <div class="emoji">⚠️</div>
      <div>${msg}</div>
    </div>`;
}

// 从 storage 读取数据 + 错误
chrome.storage.local.get(['tokenPuaData', 'tokenPuaError'], (result) => {
  if (result.tokenPuaError) {
    showError('错误: ' + result.tokenPuaError);
  } else if (result.tokenPuaData) {
    render(result.tokenPuaData);
  } else {
    showError('暂无数据，请确保已登录 token.woa.com 并等待自动刷新');
  }
});

// 监听数据更新
chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && changes.tokenPuaData) {
    render(changes.tokenPuaData.newValue);
  }
});
