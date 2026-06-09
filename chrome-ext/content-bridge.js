// TokenPUA ISOLATED world bridge — chrome.* API access, message relay
// Listens for: 1) postMessage from MAIN world, 2) chrome.runtime from background

// MAIN world → bridge → background
window.addEventListener('message', (e) => {
  if (e.data && e.data.source === '__tpua_fetch') {
    chrome.runtime.sendMessage({ action: 'fetchResult', ...e.data });
  }
});

// bridge → MAIN world
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'fetchTokenData') {
    window.postMessage({ source: '__tpua_bridge', action: 'fetch' }, '*');
    sendResponse({ success: true });
  }
});

// Notify background we're ready
chrome.runtime.sendMessage({ action: 'contentScriptReady' });
