import { getSettings, saveSettings } from "./settings.js";

const form = document.getElementById("submitForm");
const wordInput = document.getElementById("wordInput");
const levelSelect = document.getElementById("levelSelect");
const statusList = document.getElementById("statusList");
const webAppLink = document.getElementById("webAppLink");
const backendUrlInput = document.getElementById("backendUrlInput");
const frontendUrlInput = document.getElementById("frontendUrlInput");
const settingsSaveBtn = document.getElementById("settingsSaveBtn");
const settingsStatus = document.getElementById("settingsStatus");

const STATE_LABELS = {
  queued: "queued",
  generating: "generating…",
  done: "done",
  error: "error",
  "export-error": "not exported",
};

function renderJobs(jobs) {
  statusList.innerHTML = "";
  if (!jobs || jobs.length === 0) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "No submissions yet.";
    statusList.appendChild(empty);
    return;
  }
  for (const job of jobs) {
    const li = document.createElement("li");
    li.dataset.jobId = job.id;

    const wordSpan = document.createElement("span");
    wordSpan.className = "word";
    wordSpan.textContent = job.word;
    wordSpan.title = job.detail ? `${job.word}: ${job.detail}` : job.word;

    const badge = document.createElement("span");
    badge.className = `badge ${job.state}`;
    badge.textContent = STATE_LABELS[job.state] || job.state;

    li.appendChild(wordSpan);
    li.appendChild(badge);
    statusList.appendChild(li);
  }
}

async function loadInitialState() {
  const settings = await getSettings();
  webAppLink.href = settings.frontendUrl;
  backendUrlInput.value = settings.backendUrl;
  frontendUrlInput.value = settings.frontendUrl;

  const response = await chrome.runtime.sendMessage({ type: "getState" });
  renderJobs(response?.jobs || []);
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === "jobUpdate") {
    chrome.runtime.sendMessage({ type: "getState" }).then((response) => {
      renderJobs(response?.jobs || []);
    });
  }
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const word = wordInput.value.trim();
  if (!word) return;

  const job = {
    type: "submitWord",
    id: crypto.randomUUID(),
    word,
    level: levelSelect.value,
  };
  chrome.runtime.sendMessage(job);

  // Clear immediately so the next word can be pasted right away - generation/export runs
  // in the background service worker without blocking this input.
  wordInput.value = "";
  wordInput.focus();
  loadInitialState();
});

settingsSaveBtn.addEventListener("click", async () => {
  const current = await getSettings();
  const backendUrl = backendUrlInput.value.trim() || current.backendUrl;
  const frontendUrl = frontendUrlInput.value.trim() || current.frontendUrl;
  await saveSettings({ backendUrl, frontendUrl });
  backendUrlInput.value = backendUrl;
  frontendUrlInput.value = frontendUrl;
  webAppLink.href = frontendUrl;
  settingsStatus.textContent = "Saved.";
  setTimeout(() => { settingsStatus.textContent = ""; }, 2000);
});

loadInitialState();
