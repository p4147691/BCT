const TARGET = "https://chatgpt.com/";
const MAX_AGE_MS = 2000;
const candidates = new Map();

function isBlankNewTab(url) {
  return !url ||
    url === "about:blank" ||
    url === "chrome://newtab/" ||
    url === "chrome://new-tab-page/";
}

async function inspect(tabId) {
  const started = candidates.get(tabId);
  if (!started) return;
  if (Date.now() - started > MAX_AGE_MS) {
    candidates.delete(tabId);
    return;
  }

  try {
    const tab = await chrome.tabs.get(tabId);
    const url = tab.pendingUrl || tab.url || "";

    if (isBlankNewTab(url)) {
      if (url) {
        candidates.delete(tabId);
        await chrome.tabs.update(tabId, { url: TARGET });
        return;
      }
    } else {
      candidates.delete(tabId);
      return;
    }
  } catch {
    candidates.delete(tabId);
    return;
  }
}

chrome.tabs.onCreated.addListener((tab) => {
  if (!tab.active || tab.id == null) return;
  candidates.set(tab.id, Date.now());
  inspect(tab.id);
  setTimeout(() => inspect(tab.id), 100);
  setTimeout(() => inspect(tab.id), 300);
  setTimeout(() => inspect(tab.id), 700);
  setTimeout(() => inspect(tab.id), 1500);
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!candidates.has(tabId)) return;
  if (changeInfo.url || changeInfo.status) inspect(tabId);
});

chrome.tabs.onRemoved.addListener((tabId) => {
  candidates.delete(tabId);
});