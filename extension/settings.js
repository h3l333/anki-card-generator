// Shared by popup.js and background.js- both need the same backend/frontend URL
// defaults and read the same chrome.storage.local keys; only popup.js writes them
// (via saveSettings, from the settings form)- background.js only ever reads via
// getSettings.
export const DEFAULT_SETTINGS = {
  backendUrl: "http://localhost:5000",
  frontendUrl: "http://localhost:8080",
};

export async function getSettings() {
  const stored = await chrome.storage.local.get(DEFAULT_SETTINGS);
  return { ...DEFAULT_SETTINGS, ...stored };
}

export async function saveSettings(settings) {
  await chrome.storage.local.set(settings);
}
