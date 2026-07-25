// Placeholder backend address - update once the Python backend exists (see ARCHITECTURE.md).
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
