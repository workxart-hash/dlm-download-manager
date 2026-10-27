// dlm download-capture service worker (Manifest V3).
// Intercepts downloads Chrome is about to start, cancels them, and hands the
// URL to the native dlm host over native messaging.

const HOST = "com.dlm.native";

async function isEnabled() {
  const { enabled = true } = await chrome.storage.local.get("enabled");
  return enabled;
}

function skip(url) {
  return !url || url.startsWith("blob:") || url.startsWith("data:");
}

function sendToHost(payload) {
  chrome.runtime.sendNativeMessage(HOST, payload, (resp) => {
    if (chrome.runtime.lastError) {
      console.warn("dlm native host error:", chrome.runtime.lastError.message);
    } else {
      console.log("dlm queued:", resp);
    }
  });
}

function capture(url, filename) {
  if (skip(url)) return;
  sendToHost({ type: "download", url, filename: filename || "" });
}

// Intercept browser downloads and redirect them to dlm.
chrome.downloads.onCreated.addListener(async (item) => {
  if (!(await isEnabled())) return;
  const url = item.finalUrl || item.url;
  if (skip(url)) return;
  chrome.downloads.cancel(item.id, () => {
    chrome.downloads.erase({ id: item.id }, () => {});
    const name = item.filename ? item.filename.split(/[\\/]/).pop() : "";
    capture(url, name);
  });
});

// Right-click a link -> "Download with dlm".
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "dlm-download-link",
    title: "Download with dlm",
    contexts: ["link"],
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === "dlm-download-link" && info.linkUrl) {
    capture(info.linkUrl, "");
  }
});
