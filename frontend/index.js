// Backend address- the Python FastAPI service (backend/main.py), run separately via
// `uvicorn backend.main:app --port 5000` (see README "Usage"). This frontend is plain
// static HTML/JS with no build step, so this is just a hardcoded constant rather than
// something injected by a bundler- change it here directly if the backend ever runs on
// a different host/port.
const BACKEND_URL = "http://localhost:5000";

// Grabbing every element this script touches once, up front, by its id in index.html-
// each of these assumes the matching id actually exists in the page (it does, see
// index.html), so there's no null-check here before using any of them below.
const wordInput = document.getElementById("wordInput");
const generateBtn = document.getElementById("generateBtn");
const statusBox = document.getElementById("statusBox");
const cardBox = document.getElementById("cardBox");
const exportBtn = document.getElementById("exportBtn");
const rejectBtn = document.getElementById("rejectBtn");
const accentPicker = document.getElementById("accentPicker");
const fontPicker = document.getElementById("fontPicker");

// `fields` maps this project's ExportRequest field names (backend/models.py) to the
// actual <input>/<textarea> elements in index.html's card form. Note the keys here-
// definition, example, jlpt- rather than definition_ja, example_sentence, jlpt_level.
// This object is the frontend half of the field-name bridge CLAUDE.md describes: the
// /generate response comes back in CardDraft's shape (with the _ja/_sentence/_level
// names), and generateBtn's click handler below reads those into these ExportRequest-
// named fields directly, so that exportBtn's handler can later post this object's
// values straight back to /export without any further renaming.
const fields = {
	expression: document.getElementById("f-expression"),
	reading: document.getElementById("f-reading"),
	definition: document.getElementById("f-definition"),
	nuance: document.getElementById("f-nuance"),
	synonyms: document.getElementById("f-synonyms"),
	antonyms: document.getElementById("f-antonyms"),
	example: document.getElementById("f-example"),
	jlpt: document.getElementById("f-jlpt"),
};

let currentWordId = null;
// Not part of `fields` above- word_id isn't a visible/editable form field, it's the
// Postgres word this card belongs to (see backend/models.py's GenerateResponse). Held
// here as plain state rather than a hidden form field so exportBtn's handler below can
// read it without also having to filter it out of `fields`- generateBtn's handler sets
// this on every response, rejectBtn's handler clears it back to null.

// Small shared helpers for the single-word flow's status message box (index.html's
// #statusBox)- `type` is expected to be "error" or "info", matching the CSS classes
// .status.error / .status.info defined in index.html's <style> block, which control
// both the box's color and whether it's visible at all (plain .status has
// `display: none`).
function showStatus(message, type) {
	statusBox.textContent = message;
	statusBox.className = `status ${type}`;
}

function clearStatus() {
	statusBox.textContent = "";
	statusBox.className = "status";
}

// Live theming: these two listeners don't touch the backend at all- they just let the
// user restyle the page instantly as they interact with the color/font pickers.
accentPicker.addEventListener("input", () => {
	// Setting a CSS custom property directly on the root element updates every rule in
	// index.html's <style> block that references var(--accent) (e.g. the button
	// background)- no page reload or re-render needed, the browser recomputes styles
	// as soon as the property changes.
	document.documentElement.style.setProperty("--accent", accentPicker.value);
});

fontPicker.addEventListener("change", () => {
	document.body.style.fontFamily = fontPicker.value;
});

generateBtn.addEventListener("click", async () => {
	const word = wordInput.value.trim();
	if (!word) return;
	// Silently does nothing on an empty/whitespace-only input, rather than showing an
	// error- there's no dedicated "please enter a word" message for this case.

	clearStatus();
	cardBox.classList.remove("visible");
	generateBtn.disabled = true;
	generateBtn.textContent = "Generating...";
	// Hiding any previously-shown card and disabling the button up front prevents a
	// user from double-submitting while a request is already in flight, and stops a
	// stale card from a previous word remaining visible while a new one generates.

	try {
		const response = await fetch(`${BACKEND_URL}/generate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ word }),
		});
		// `{ word }` is object shorthand for `{ word: word }`- this matches
		// GenerateRequest's shape in backend/models.py exactly (a single "word" field).

		if (!response.ok) {
			throw new Error("bad-response");
		}
		// fetch() only rejects on a genuine network failure (e.g. the backend isn't
		// running at all)- an HTTP error status like 502 still resolves normally, so
		// response.ok (true only for 2xx statuses) has to be checked explicitly and
		// turned into a thrown error to be caught by the catch block below.

		const data = await response.json();
		// backend/main.py's /generate route now returns GenerateResponse (backend/models.py):
		// {word_id, duplicate, card}, not a bare CardDraft- data.card is where the eight
		// generated fields actually live now, one level deeper than before. word_id and
		// duplicate aren't consumed here yet- they're threaded through the review form once
		// /export is wired up to use them (see ROADMAP.md).
		const card = data.card;
		currentWordId = data.word_id;
		// Captured here, before anything else touches `data`- this is the one place the
		// backend ever tells the frontend which word this card is (see GenerateResponse
		// in backend/models.py). exportBtn's handler below reads currentWordId when the
		// user eventually clicks Export, whether or not they edited any fields first.
		// This is the field-name bridge in action: the keys on the right (card.expression,
		// card.reading, card.definition_ja, ...) are CardDraft's field names exactly as
		// backend/main.py's /generate route returns them, while the `fields.*` targets on
		// the left are this project's ExportRequest-shaped form fields (see the `fields`
		// object above)- definition_ja becomes fields.definition, example_sentence becomes
		// fields.example, jlpt_level becomes fields.jlpt. synonyms/antonyms are named the
		// same on both sides, so those two just pass straight through.
		fields.expression.value = card.expression ?? word;
		fields.reading.value = card.reading ?? "";
		fields.definition.value = card.definition_ja ?? "";
		fields.nuance.value = card.nuance ?? "";
		fields.synonyms.value = card.synonyms ?? "";
		fields.antonyms.value = card.antonyms ?? "";
		fields.example.value = card.example_sentence ?? "";
		fields.jlpt.value = card.jlpt_level ?? "";
		// `??` is the nullish-coalescing operator- it falls back to the right-hand value
		// only when the left side is specifically null or undefined (unlike `||`, which
		// would also fall back on an empty string or 0). `card.expression ?? word` falls
		// back to the word the user actually typed if the backend response is somehow
		// missing that field; the rest fall back to an empty string so a missing field
		// shows a blank, editable box instead of the literal text "undefined".

		if (data.duplicate) {
			showStatus(
				"This word already has a saved card- showing the existing one.",
				"info",
			);
		}
		// A minimal, non-blocking heads-up for now: duplicate=true means these fields came
		// from Postgres rather than a fresh OpenRouter call (see backend/main.py). The
		// fuller cancel-vs-edit decision flow described in ARCHITECTURE.md is a separate,
		// not-yet-built step- this just stops the duplicate case from looking identical to
		// a freshly generated card with no indication anything different happened.

		cardBox.classList.add("visible");
		// .card.visible is what actually makes this box render at all- see index.html's
		// <style>, where plain .card has `display: none`.
	} catch (err) {
		// Mirrors the LLM parsing/backend failure messaging described in PROJECT.md.
		showStatus(
			"Failed to reach the backend or parse its response. Is the Python service running?",
			"error",
		);
		// One single generic message regardless of what actually went wrong (network
		// failure, non-2xx status, malformed JSON body)- unlike the batch upload flow
		// further down, which does surface the backend's specific error detail.
	} finally {
		generateBtn.disabled = false;
		generateBtn.textContent = "Generate";
		// `finally` runs whether the try block succeeded or the catch block ran- this is
		// what re-enables the button either way, so a failed request doesn't leave it
		// stuck disabled.
	}
});

rejectBtn.addEventListener("click", () => {
	cardBox.classList.remove("visible");
	wordInput.value = "";
	clearStatus();
	currentWordId = null;
});
// Discarding a card never contacts the backend at all- the draft only ever existed in
// the form fields client-side, so "rejecting" it is just hiding the box and resetting
// the input for the next word.

exportBtn.addEventListener("click", async () => {
	const payload = {
		...Object.fromEntries(
			Object.entries(fields).map(([key, el]) => [key, el.value]),
		),
		word_id: currentWordId,
	};
	// Object.entries(fields) turns {expression: <input>, reading: <input>, ...} into
	// [["expression", <input>], ["reading", <input>], ...]; .map(...) replaces each
	// element with its current .value, giving [["expression", "大人"], ...];
	// Object.fromEntries(...) turns that back into a plain object
	// {expression: "大人", reading: "おとな", ...}. The net effect: read every field's
	// live value out of the DOM into one plain object, keyed exactly like ExportRequest
	// (backend/models.py)- which is why this payload can be sent to /export as-is with
	// no further renaming, unlike the /generate response above. word_id is spread in
	// separately since it's not a DOM field (see currentWordId above)- ExportRequest
	// accepts it as optional, so this is currentWordId's value whether that's a real ID
	// or still null (e.g. if generation somehow never set it).

	try {
		const response = await fetch(`${BACKEND_URL}/export`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		});

		if (!response.ok) throw new Error("export-failed");

		showStatus("Card exported to Anki.", "info");
	} catch (err) {
		// Mirrors the AnkiConnect failure messaging described in PROJECT.md.
		showStatus(
			"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled.",
			"error",
		);
	}
});

// Batch upload (.txt) flow below- a separate set of elements/status box from the
// single-word flow above, since both sections are shown on the page at the same time
// and need independent status messages.
const fileInput = document.getElementById("fileInput");
const batchGenerateBtn = document.getElementById("batchGenerateBtn");
const batchStatusBox = document.getElementById("batchStatusBox");
const carousel = document.getElementById("carousel");

function showBatchStatus(message, type) {
	batchStatusBox.textContent = message;
	batchStatusBox.className = `status ${type}`;
}

function clearBatchStatus() {
	batchStatusBox.textContent = "";
	batchStatusBox.className = "status";
}

// Builds one carousel card's DOM subtree for a single BatchCardResult (see
// backend/models.py)- called once per entry in the /generate/batch response.
function buildCarouselCard(result) {
	const card = document.createElement("div");
	card.className = "carousel-card" + (result.error ? " error" : "");
	// This function builds elements directly via document.createElement rather than
	// using an HTML <template>- there's no templating in this project at all, so every
	// piece of a carousel card (label, fields, buttons) is assembled by hand below.

	const label = document.createElement("div");
	label.className = "word-label";
	label.textContent = result.word;
	card.appendChild(label);

	const cardWordId = result.word_id ?? null;
	// Mirrors currentWordId in the single-word flow above, just scoped to this one
	// carousel card via closure instead of a shared module-level variable- each card
	// needs its own, since a batch response can carry a different word_id per result
	// (backend/models.py's BatchCardResult). Falls back to null the same way a missing/
	// failed generation would, so a card built before this field existed (or for a word
	// that somehow has no card) still posts a valid ExportRequest.word_id.

	if (result.error) {
		const errorText = document.createElement("div");
		errorText.textContent = result.error;
		card.appendChild(errorText);

		const retryHint = document.createElement("div");
		retryHint.className = "retry-hint";
		retryHint.textContent =
			"Try generating this word on its own using the single-word form above- " +
			"a solo request sometimes succeeds where a batch entry failed (malformed " +
			"JSON, transient API error, etc).";
		card.appendChild(retryHint);

		return card;
		// Early return- a failed word gets its word label, the error message, and a
		// retry hint, never the editable fields or Discard/Export buttons below, since
		// there's no card content to review or export for a word that failed to generate.
	}

	// fieldDefs pairs each ExportRequest-shaped key with its display label and which
	// HTML tag to build for it ("input" for single-line fields, "textarea" for the
	// longer free-text ones)- driving the loop below instead of repeating near-identical
	// field-building code eight times by hand.
	const fieldDefs = [
		["expression", "Expression", "input"],
		["reading", "Reading", "input"],
		["definition", "Monolingual Definition", "textarea"],
		["nuance", "Nuance", "textarea"],
		["synonyms", "Synonyms", "textarea"],
		["antonyms", "Antonyms", "textarea"],
		["example", "Example Sentence", "textarea"],
		["jlpt", "JLPT Level", "input"],
	];

	// Same field-name bridge as generateBtn's handler above, just applied to a batch
	// result's card instead of a single /generate response- result.card is CardDraft-
	// shaped (definition_ja, example_sentence, jlpt_level), mapped here into the
	// ExportRequest-shaped keys (definition, example, jlpt) that fieldDefs and the
	// eventual /export payload both use. synonyms/antonyms pass straight through, same
	// reasoning as generateBtn's handler above.
	const values = {
		expression: result.card.expression,
		reading: result.card.reading,
		definition: result.card.definition_ja,
		nuance: result.card.nuance,
		synonyms: result.card.synonyms,
		antonyms: result.card.antonyms,
		example: result.card.example_sentence,
		jlpt: result.card.jlpt_level,
	};

	const cardFields = {};
	for (const [key, labelText, tag] of fieldDefs) {
		const fieldWrap = document.createElement("div");
		fieldWrap.className = "field";

		const fieldLabel = document.createElement("label");
		fieldLabel.textContent = labelText;
		fieldWrap.appendChild(fieldLabel);

		const input = document.createElement(tag);
		// `tag` here is the string "input" or "textarea" from fieldDefs- passing a
		// variable to document.createElement works the same as writing the tag name
		// literally, so this one line creates either kind of element depending on
		// which field is currently being built.
		input.value = values[key];
		cardFields[key] = input;
		// Every created field element is kept in `cardFields`, keyed the same way as
		// `values`- this is what lets the Export button below read each field's
		// (possibly user-edited) live value back out later, the same way the
		// single-word flow's `fields` object works at the top of this file.
		fieldWrap.appendChild(input);

		card.appendChild(fieldWrap);
	}

	const actions = document.createElement("div");
	actions.className = "card-actions";

	const discardBtn = document.createElement("button");
	discardBtn.className = "secondary";
	discardBtn.textContent = "Discard";
	discardBtn.addEventListener("click", () => card.remove());
	// card.remove() just deletes this one carousel card's DOM subtree from the page-
	// nothing is sent to the backend, same as the single-word flow's rejectBtn.

	const cardExportBtn = document.createElement("button");
	cardExportBtn.textContent = "Export to Anki";
	cardExportBtn.addEventListener("click", async () => {
		const payload = {
			...Object.fromEntries(
				Object.entries(cardFields).map(([key, el]) => [key, el.value]),
			),
			word_id: cardWordId,
		};
		// Same Object.entries -> map -> Object.fromEntries pattern as exportBtn's handler
		// above, just reading from this card's own `cardFields` (a closure variable
		// captured from the loop above) instead of the single-word flow's shared `fields`.
		// word_id spread in the same way exportBtn's handler does it- now that backend/
		// main.py's /generate/batch route persists each successful card and returns a
		// word_id (see backend/models.py's BatchCardResult), a batch export can be tracked/
		// updated via get_latest_export/record_export too, instead of always being a bare
		// addNote with nothing recorded.

		try {
			const response = await fetch(`${BACKEND_URL}/export`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			if (!response.ok) throw new Error("export-failed");

			cardExportBtn.textContent = "Exported";
			cardExportBtn.disabled = true;
			// Unlike the single-word flow, a successfully-exported batch card stays
			// visible with its button relabeled and disabled, rather than being hidden-
			// each card in the carousel is independent, so there's no single shared
			// status box position that would make sense to clear here.
		} catch (err) {
			showBatchStatus(
				"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled.",
				"error",
			);
		}
	});

	actions.appendChild(discardBtn);
	actions.appendChild(cardExportBtn);
	card.appendChild(actions);

	return card;
}

batchGenerateBtn.addEventListener("click", () => {
	const file = fileInput.files[0];
	if (!file) return;

	clearBatchStatus();
	carousel.innerHTML = "";
	batchGenerateBtn.disabled = true;
	batchGenerateBtn.textContent = "Generating...";
	// carousel.innerHTML = "" wipes out any cards left over from a previous batch
	// upload before the new one's results are appended below.

	const reader = new FileReader();
	// FileReader reads the uploaded file's contents entirely client-side- the raw text
	// is read here in the browser and sent to the backend as a JSON string field
	// (file_content, matching BatchGenerateRequest in backend/models.py), rather than
	// the file itself being uploaded as multipart form data.
	reader.onload = async () => {
		// reader.onload fires once the file has finished being read into memory-
		// everything that depends on the file's contents (reader.result) has to happen
		// inside this callback, since reading a file is asynchronous.
		try {
			const response = await fetch(`${BACKEND_URL}/generate/batch`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ file_content: reader.result }),
			});

			const data = await response.json().catch(() => null);
			// Unlike the single-word flow, the response body is parsed *before* checking
			// response.ok- that's because a 400 (bad batch file) still comes back with a
			// JSON body containing a useful "detail" message (see backend/main.py), which
			// the catch block below wants to show the user. `.catch(() => null)` guards
			// against a response body that isn't valid JSON at all, falling back to null
			// rather than letting that parsing failure escape as its own uncaught error.

			if (!response.ok) {
				throw new Error(data?.detail || "bad-response");
				// `data?.detail` is optional chaining- it safely reads `.detail` only if
				// `data` isn't null/undefined, evaluating to undefined instead of throwing
				// if `data` came back null from the .catch() above. `|| "bad-response"`
				// then falls back to that generic sentinel value if there was no usable
				// detail message to show.
			}

			for (const result of data.results) {
				carousel.appendChild(buildCarouselCard(result));
			}
			// data.results is the list of BatchCardResult entries (backend/models.py)-
			// one buildCarouselCard() call, and one appended card, per word in the
			// original uploaded file, in the same order.
		} catch (err) {
			showBatchStatus(
				err.message && err.message !== "bad-response"
					? err.message
					: "Failed to reach the backend. Is the Python service running?",
				"error",
			);
			// Shows the backend's actual validation message (e.g. "File contains 13 words
			// - the limit is 12 per file.") when one was available, but falls back to a
			// generic connectivity message specifically when err.message is the
			// "bad-response" sentinel thrown above (or missing entirely)- that sentinel is
			// what signals "we got a non-2xx response with no usable detail message",
			// as opposed to a real backend-provided error string.
		} finally {
			batchGenerateBtn.disabled = false;
			batchGenerateBtn.textContent = "Generate from File";
		}
	};
	reader.readAsText(file);
	// Kicks off the actual (asynchronous) file read- reader.onload above only fires
	// once this completes.
});
