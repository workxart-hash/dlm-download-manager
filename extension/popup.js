const HOST = "com.dlm.native";
const cb = document.getElementById("enabled");
const status = document.getElementById("status");

chrome.storage.local.get("enabled").then(({ enabled = true }) => {
  cb.checked = enabled;
});

cb.addEventListener("change", () => {
  chrome.storage.local.set({ enabled: cb.checked });
});

document.getElementById("ping").addEventListener("click", () => {
  chrome.runtime.sendNativeMessage(HOST, { type: "ping" }, (resp) => {
    if (chrome.runtime.lastError) {
      status.textContent = "error: " + chrome.runtime.lastError.message;
    } else {
      status.textContent = "host ok, v" + (resp && resp.version);
    }
  });
});
