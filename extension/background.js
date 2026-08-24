import { getSettings } from "./settings.js";

// Job state lives here (module-level Map) and is mirrored to chrome.storage.session after
// every transition, so a popup reopened after the service worker was recycled can still
// render recent/in-flight jobs (session storage survives a worker restart, unlike the Map).
const jobs = new Map();
const MAX_JOBS = 20;

async function loadJobsFromSession() {
  const { jobs: stored } = await chrome.storage.session.get("jobs");
  if (stored) {
    for (const job of stored) jobs.set(job.id, job);
  }
}
const jobsLoaded = loadJobsFromSession();

async function persistJobs() {
  const list = [...jobs.values()]
    .sort((a, b) => b.startedAt - a.startedAt)
    .slice(0, MAX_JOBS);
  await chrome.storage.session.set({ jobs: list });
}

function broadcastJobUpdate(job) {
  chrome.runtime.sendMessage({ type: "jobUpdate", job }).catch(() => {
    // No popup listening right now - fine, chrome.storage.session is the source of truth
    // a reopened popup reads from.
  });
}

async function setJobState(job, patch) {
  Object.assign(job, patch);
  jobs.set(job.id, job);
  await persistJobs();
  broadcastJobUpdate(job);
}

// Reads a fetch() Response body as newline-delimited JSON, yielding one parsed object per
// line. Can't import frontend/index.js's readNdjsonLines - this runs in the extension's
// service worker, a separate execution context - so this mirrors its approach instead.
async function* readNdjsonLines(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) yield JSON.parse(line);
    }
  }
  const remainder = buffer.trim();
  if (remainder) yield JSON.parse(remainder);
}

function notify(id, title, message) {
  chrome.notifications.create(id, {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title,
    message,
  });
}

async function handleGenerateExport(job) {
  const { backendUrl } = await getSettings();
  await setJobState(job, { state: "generating" });

  let response;
  try {
    response = await fetch(`${backendUrl}/generate/export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ word: job.word, level: job.level }),
    });
  } catch (err) {
    await setJobState(job, { state: "error", detail: `Could not reach the backend: ${err.message}` });
    notify(`${job.id}-gen-error`, "Generation failed", `Could not generate a card for "${job.word}": could not reach the backend.`);
    return;
  }

  if (!response.ok) {
    const detail = `Backend returned HTTP ${response.status}`;
    await setJobState(job, { state: "error", detail });
    notify(`${job.id}-gen-error`, "Generation failed", `Could not generate a card for "${job.word}": ${detail}`);
    return;
  }

  try {
    for await (const event of readNdjsonLines(response)) {
      if (event.event === "heartbeat" || event.event === "retry") {
        await setJobState(job, { state: "generating" });
        continue;
      }
      if (event.event === "error" && event.stage === "generate") {
        await setJobState(job, { state: "error", detail: event.detail });
        notify(`${job.id}-gen-error`, "Generation failed", `Could not generate a card for "${job.word}": ${event.detail}`);
        return;
      }
      if (event.event === "error" && event.stage === "export") {
        await setJobState(job, { state: "export-error", detail: event.detail });
        notify(
          `${job.id}-export-error`,
          "Generated but not exported",
          `"${job.word}" was generated but export to Anki failed: ${event.detail}. Open the web app to retry.`
        );
        return;
      }
      if (event.event === "exported") {
        await setJobState(job, { state: "done" });
        notify(`${job.id}-done`, "Exported to Anki", `"${job.word}" was generated and exported.`);
        return;
      }
    }
    // Stream ended without a terminal event - the service worker likely got suspended or
    // the connection dropped mid-stream (see extension/README.md's MV3 lifecycle note).
    const detail = "Connection closed before generation finished.";
    await setJobState(job, { state: "error", detail });
    notify(`${job.id}-gen-error`, "Generation failed", `"${job.word}": ${detail}`);
  } catch (err) {
    await setJobState(job, { state: "error", detail: err.message });
    notify(`${job.id}-gen-error`, "Generation failed", `"${job.word}": ${err.message}`);
  }
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type === "getState") {
    jobsLoaded.then(() => {
      sendResponse({ jobs: [...jobs.values()].sort((a, b) => b.startedAt - a.startedAt) });
    });
    return true; // keeps the message channel open for the async sendResponse above
  }

  if (message.type === "submitWord") {
    const job = {
      id: message.id,
      word: message.word,
      level: message.level,
      state: "queued",
      detail: null,
      startedAt: Date.now(),
    };
    jobs.set(job.id, job);
    // Fired without awaiting - a second submitWord message can start its own independent
    // fetch() immediately, with no queue or concurrency cap, satisfying the "generate
    // multiple cards without waiting" requirement.
    handleGenerateExport(job);
    return false;
  }

  return false;
});
