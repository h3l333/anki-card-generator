# Anki Tool v2 - Quick Export (Chrome extension)

Paste a single Japanese word into the popup and it's generated and exported to Anki automatically - no review/edit step. For editing generated cards, resolving duplicates, or batch generation, use the main web app (`frontend/`); the popup links to it.

## Setup

1. Start the backend and Anki (with AnkiConnect) as indicated in the project root README.
2. Go to `chrome://extensions`, enable Developer mode, click "Load unpacked", and select this `extension/` directory.
3. Open the popup, paste a word, and submit. It clears immediately so you can paste another word right away - each submission generates and exports independently in the background.

Default backend URL is `http://localhost:5000`, default web app URL is `http://localhost:8080`, both editable in the popup's Settings section. Changing either past these defaults also requires editing `manifest.json`'s `host_permissions` and reloading the extension.

## How it works

The popup sends each submitted word to the background service worker (`background.js`), which calls the backend's `POST /generate/export` endpoint - a single combined generate+export call added specifically for this extension (see `backend/main.py`). Multiple words can be in flight at once; each is its own independent request, not queued behind the others. A Chrome desktop notification fires when a card finishes exporting, or if generation/export fails.

If a card generates successfully but AnkiConnect export fails (e.g. Anki isn't running), the word is still saved to Postgres - reopening the web app and generating the same word will hit its duplicate-word path, letting you export it manually from there.

## Known limitation: service worker lifecycle

Chrome can suspend an idle MV3 service worker after roughly 30 seconds of inactivity. It's untested whether the periodic heartbeat lines in the `/generate/export` response stream are enough to keep the worker alive for the full duration of a slow generation. If the worker is killed mid-stream, that job will appear stuck ("generating…") with no notification, and whether the word already reached AnkiConnect depends on the exact timing. If this turns out to be a real problem in practice, a `chrome.alarms`-based keepalive is the fix - not implemented yet since it wasn't confirmed necessary.
