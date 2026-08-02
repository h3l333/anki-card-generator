// Placeholder backend address- update once the Python backend exists (see ARCHITECTURE.md).
const BACKEND_URL = "http://localhost:5000";

const wordInput = document.getElementById("wordInput");
const generateBtn = document.getElementById("generateBtn");
const statusBox = document.getElementById("statusBox");
const cardBox = document.getElementById("cardBox");
const exportBtn = document.getElementById("exportBtn");
const rejectBtn = document.getElementById("rejectBtn");
const accentPicker = document.getElementById("accentPicker");
const fontPicker = document.getElementById("fontPicker");

const fields = {
	expression: document.getElementById("f-expression"),
	reading: document.getElementById("f-reading"),
	definition: document.getElementById("f-definition"),
	nuance: document.getElementById("f-nuance"),
	example: document.getElementById("f-example"),
	jlpt: document.getElementById("f-jlpt"),
};

function showStatus(message, type) {
	statusBox.textContent = message;
	statusBox.className = `status ${type}`;
}

function clearStatus() {
	statusBox.textContent = "";
	statusBox.className = "status";
}

accentPicker.addEventListener("input", () => {
	document.documentElement.style.setProperty("--accent", accentPicker.value);
});

fontPicker.addEventListener("change", () => {
	document.body.style.fontFamily = fontPicker.value;
});

generateBtn.addEventListener("click", async () => {
	const word = wordInput.value.trim();
	if (!word) return;

	clearStatus();
	cardBox.classList.remove("visible");
	generateBtn.disabled = true;
	generateBtn.textContent = "Generating...";

	try {
		const response = await fetch(`${BACKEND_URL}/generate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ word }),
		});

		if (!response.ok) {
			throw new Error("bad-response");
		}

		const data = await response.json();
		fields.expression.value = data.expression ?? word;
		fields.reading.value = data.reading ?? "";
		fields.definition.value = data.definition_ja ?? "";
		fields.nuance.value = data.nuance ?? "";
		fields.example.value = data.example_sentence ?? "";
		fields.jlpt.value = data.jlpt_level ?? "";

		cardBox.classList.add("visible");
	} catch (err) {
		// Mirrors the LLM parsing/backend failure messaging described in PROJECT.md.
		showStatus(
			"Failed to reach the backend or parse its response. Is the Python service running?",
			"error",
		);
	} finally {
		generateBtn.disabled = false;
		generateBtn.textContent = "Generate";
	}
});

rejectBtn.addEventListener("click", () => {
	cardBox.classList.remove("visible");
	wordInput.value = "";
	clearStatus();
});

exportBtn.addEventListener("click", async () => {
	const payload = Object.fromEntries(
		Object.entries(fields).map(([key, el]) => [key, el.value]),
	);

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

function buildCarouselCard(result) {
	const card = document.createElement("div");
	card.className = "carousel-card" + (result.error ? " error" : "");

	const label = document.createElement("div");
	label.className = "word-label";
	label.textContent = result.word;
	card.appendChild(label);

	if (result.error) {
		const errorText = document.createElement("div");
		errorText.textContent = result.error;
		card.appendChild(errorText);
		return card;
	}

	const fieldDefs = [
		["expression", "Expression", "input"],
		["reading", "Reading", "input"],
		["definition", "Monolingual Definition", "textarea"],
		["nuance", "Nuance", "textarea"],
		["example", "Example Sentence", "textarea"],
		["jlpt", "JLPT Level", "input"],
	];

	const values = {
		expression: result.card.expression,
		reading: result.card.reading,
		definition: result.card.definition_ja,
		nuance: result.card.nuance,
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
		input.value = values[key];
		cardFields[key] = input;
		fieldWrap.appendChild(input);

		card.appendChild(fieldWrap);
	}

	const actions = document.createElement("div");
	actions.className = "card-actions";

	const discardBtn = document.createElement("button");
	discardBtn.className = "secondary";
	discardBtn.textContent = "Discard";
	discardBtn.addEventListener("click", () => card.remove());

	const cardExportBtn = document.createElement("button");
	cardExportBtn.textContent = "Export to Anki";
	cardExportBtn.addEventListener("click", async () => {
		const payload = Object.fromEntries(
			Object.entries(cardFields).map(([key, el]) => [key, el.value]),
		);

		try {
			const response = await fetch(`${BACKEND_URL}/export`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			if (!response.ok) throw new Error("export-failed");

			cardExportBtn.textContent = "Exported";
			cardExportBtn.disabled = true;
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

	const reader = new FileReader();
	reader.onload = async () => {
		try {
			const response = await fetch(`${BACKEND_URL}/generate/batch`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ file_content: reader.result }),
			});

			const data = await response.json().catch(() => null);

			if (!response.ok) {
				throw new Error(data?.detail || "bad-response");
			}

			for (const result of data.results) {
				carousel.appendChild(buildCarouselCard(result));
			}
		} catch (err) {
			showBatchStatus(
				err.message && err.message !== "bad-response"
					? err.message
					: "Failed to reach the backend. Is the Python service running?",
				"error",
			);
		} finally {
			batchGenerateBtn.disabled = false;
			batchGenerateBtn.textContent = "Generate from File";
		}
	};
	reader.readAsText(file);
});
