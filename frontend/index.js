const BACKEND_URL = "http://localhost:5000";

const wordInput = document.getElementById("wordInput");
const generateBtn = document.getElementById("generateBtn");
const statusBox = document.getElementById("statusBox");
const generateProgress = document.getElementById("generateProgress");
const generateStage = document.getElementById("generateStage");
const generateElapsed = document.getElementById("generateElapsed");
const cardBox = document.getElementById("cardBox");
const exportBtn = document.getElementById("exportBtn");
const rejectBtn = document.getElementById("rejectBtn");
const accentPicker = document.getElementById("accentPicker");
const fontPicker = document.getElementById("fontPicker");
const levelPicker = document.getElementById("levelPicker");

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

function showStatus(message, type) {
	statusBox.textContent = message;
	statusBox.className = `status ${type}`;
}

function clearStatus() {
	statusBox.textContent = "";
	statusBox.className = "status";
}

async function readNdjsonLines(response, onLine) {
	const bodyReader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	while (true) {
		const { done, value } = await bodyReader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });

		let newlineIndex;
		while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
			const line = buffer.slice(0, newlineIndex);
			buffer = buffer.slice(newlineIndex + 1);
			if (line) onLine(JSON.parse(line));
		}
	}
}

function progressStageText(event, hasRetried) {
	if (event.event === "retry" || hasRetried) {
		return "Retrying- model returned an unexpected word...";
	}
	return "Waiting for model...";
}

const INFO_BG_LIGHTEN = 12;
const INFO_BG_MAX_LIGHTNESS = 96;
const INFO_TEXT_SHIFT = 40;
const INFO_TEXT_MIN_LIGHTNESS = 4;
const INFO_TEXT_MAX_LIGHTNESS = 92;

function hexToRgb(hex) {
	const clean = hex.replace("#", "");
	return {
		r: parseInt(clean.slice(0, 2), 16),
		g: parseInt(clean.slice(2, 4), 16),
		b: parseInt(clean.slice(4, 6), 16),
	};
}

function rgbToHsl(r, g, b) {
	r /= 255;
	g /= 255;
	b /= 255;
	const max = Math.max(r, g, b);
	const min = Math.min(r, g, b);
	let h = 0;
	let s = 0;
	const l = (max + min) / 2;

	if (max !== min) {
		const d = max - min;
		s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
		switch (max) {
			case r:
				h = (g - b) / d + (g < b ? 6 : 0);
				break;
			case g:
				h = (b - r) / d + 2;
				break;
			default:
				h = (r - g) / d + 4;
		}
		h /= 6;
	}
	return { h: h * 360, s: s * 100, l: l * 100 };
}


function deriveInfoColors(accentHex) {
	const accentRgb = hexToRgb(accentHex);
	const { h, s, l } = rgbToHsl(accentRgb.r, accentRgb.g, accentRgb.b);

	const bgLightness = Math.min(l + INFO_BG_LIGHTEN, INFO_BG_MAX_LIGHTNESS);
	const textLightness = bgLightness >= 50
		? Math.max(bgLightness - INFO_TEXT_SHIFT, INFO_TEXT_MIN_LIGHTNESS)
		: Math.min(bgLightness + INFO_TEXT_SHIFT, INFO_TEXT_MAX_LIGHTNESS);

	return {
		background: `hsl(${h}, ${s}%, ${bgLightness}%)`,
		text: `hsl(${h}, ${s}%, ${textLightness}%)`,
	};
}

function applyInfoColors() {
	const { background, text } = deriveInfoColors(accentPicker.value);
	document.documentElement.style.setProperty("--info-bg", background);
	document.documentElement.style.setProperty("--info-text", text);
}

applyInfoColors();

accentPicker.addEventListener("input", () => {
	document.documentElement.style.setProperty("--accent", accentPicker.value);
	applyInfoColors();
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

	showStatus(
		"Generating... structured JSON output can take a while (up to a few minutes)- see README Troubleshooting if it seems stuck.",
		"info",
	);

	const requestStart = Date.now();
	let hasRetried = false;
	generateProgress.classList.remove("visible");
	generateStage.textContent = "Waiting for model...";
	generateElapsed.textContent = "0s";
	const elapsedTicker = setInterval(() => {
		generateElapsed.textContent = `${Math.floor((Date.now() - requestStart) / 1000)}s`;
	}, 1000);

	try {
		const response = await fetch(`${BACKEND_URL}/generate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				word,
				level: levelPicker.value,
				mode: document.querySelector('input[name="genMode"]:checked').value,
			}),
		});

		if (!response.ok) {
			throw new Error("bad-response");
		}

		let sawTerminalEvent = false;
		await readNdjsonLines(response, (event) => {
			if (event.event === "heartbeat" || event.event === "retry") {
				if (event.event === "retry") hasRetried = true;
				generateProgress.classList.add("visible");
				generateStage.textContent = progressStageText(event, hasRetried);
				return;
			}

			if (event.event === "error") {
				sawTerminalEvent = true;
				showStatus(event.detail, "error");
				return;
			}

			sawTerminalEvent = true;
			const card = event.card;
			currentWordId = event.word_id;
			fields.expression.value = card.expression ?? word;
			fields.reading.value = card.reading ?? "";
			fields.definition.value = card.definition_ja ?? "";
			fields.nuance.value = card.nuance ?? "";
			fields.synonyms.value = card.synonyms ?? "";
			fields.antonyms.value = card.antonyms ?? "";
			fields.example.value = card.example_sentence ?? "";
			fields.jlpt.value = card.jlpt_level ?? "";

			if (event.duplicate) {
				showStatus(
					"This word already has a saved card- showing the existing one.",
					"info",
				);
			}

			cardBox.classList.add("visible");
		});
		if (!sawTerminalEvent) {
			throw new Error("bad-response");
		}
	} catch (err) {
		showStatus(
			"Failed to reach the backend or parse its response. Is the Python service running?",
			"error",
		);
	} finally {
		generateBtn.disabled = false;
		generateBtn.textContent = "Generate";
		clearInterval(elapsedTicker);
		generateProgress.classList.remove("visible");
	}
});

rejectBtn.addEventListener("click", () => {
	cardBox.classList.remove("visible");
	wordInput.value = "";
	clearStatus();
	currentWordId = null;
});

exportBtn.addEventListener("click", async () => {
	const payload = {
		...Object.fromEntries(
			Object.entries(fields).map(([key, el]) => [key, el.value]),
		),
		word_id: currentWordId,
	};

	try {
		const response = await fetch(`${BACKEND_URL}/export`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify(payload),
		});

		if (!response.ok) throw new Error("export-failed");

		showStatus("Card exported to Anki.", "info");
	} catch (err) {
		showStatus(
			"Unable to reach Anki. Please ensure Anki is running with the AnkiConnect add-on enabled.",
			"error",
		);
	}
});

const fileInput = document.getElementById("fileInput");
const batchGenerateBtn = document.getElementById("batchGenerateBtn");
const batchStatusBox = document.getElementById("batchStatusBox");
const batchProgress = document.getElementById("batchProgress");
const batchStage = document.getElementById("batchStage");
const batchElapsed = document.getElementById("batchElapsed");
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

	if (result.duplicate) {
		const duplicateBanner = document.createElement("div");
		duplicateBanner.className = "status info";
		duplicateBanner.textContent =
			"This word already has a saved card- showing the existing one.";
		card.appendChild(duplicateBanner);
	}

	const cardWordId = result.word_id ?? null;

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
	}

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
		const payload = {
			...Object.fromEntries(
				Object.entries(cardFields).map(([key, el]) => [key, el.value]),
			),
			word_id: cardWordId,
		};

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

	showBatchStatus(
		"Generating... structured JSON output can take a while per word (up to a few minutes each)- see README Troubleshooting if it seems stuck.",
		"info",
	);

	const reader = new FileReader();
	reader.onload = async () => {
		try {
			const response = await fetch(`${BACKEND_URL}/generate/batch`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					file_content: reader.result,
					level: levelPicker.value,
					mode: document.querySelector('input[name="genMode"]:checked').value,
				}),
			});

			if (!response.ok) {
				const data = await response.json().catch(() => null);
				throw new Error(data?.detail || "bad-response");
			}

			let total = null;
			let progressIndex = null;
			let hasRetried = false;

			await readNdjsonLines(response, (event) => {
				if ("event" in event) {
					if (event.index !== progressIndex) {
						progressIndex = event.index;
						hasRetried = false;
					}
					if (event.event === "retry") hasRetried = true;
					batchProgress.classList.add("visible");
					batchStage.textContent =
						`"${event.word}" (${event.index + 1}/${total ?? "?"}) - ` +
						progressStageText(event, hasRetried);
					batchElapsed.textContent = `${event.elapsed_s}s`;
					return;
				}

				if (!("result" in event)) {
					total = event.total;
					showBatchStatus(`Generating... 0/${total} done.`, "info");
					return;
				}

				const completed = event.completed;
				total = event.total;
				carousel.appendChild(buildCarouselCard(event.result));
				showBatchStatus(
					`Generating... ${completed}/${total} done. Each word can take up ` +
						"to a few minutes- see README Troubleshooting if it seems stuck.",
					"info",
				);
				batchProgress.classList.remove("visible");
			});
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
			batchProgress.classList.remove("visible");
		}
	};
	reader.readAsText(file);
});

const datasetSection = document.getElementById("datasetSection");
const datasetGenerateBtn = document.getElementById("datasetGenerateBtn");
const datasetStatusBox = document.getElementById("datasetStatusBox");
const datasetProgress = document.getElementById("datasetProgress");
const datasetStage = document.getElementById("datasetStage");
const datasetElapsed = document.getElementById("datasetElapsed");
const datasetCarousel = document.getElementById("datasetCarousel");

function showDatasetStatus(message, type) {
	datasetStatusBox.textContent = message;
	datasetStatusBox.className = `status ${type}`;
}

function clearDatasetStatus() {
	datasetStatusBox.textContent = "";
	datasetStatusBox.className = "status";
}

const DATASET_SECTION_CONFIG = {
	vocab: {
		exportPath: "/export/dataset-vocab",
		tag: "N2::Vocab",
		fieldDefs: [
			["expression", "Expression", "input"],
			["reading", "Reading", "input"],
			["definition", "Monolingual Definition", "textarea"],
			["nuance", "Nuance", "textarea"],
			["synonyms", "Synonyms", "textarea"],
			["antonyms", "Antonyms", "textarea"],
			["example", "Example Sentence", "textarea"],
			["jlpt", "JLPT Level", "input"],
		],
		values: (card) => ({
			expression: card.expression,
			reading: card.reading,
			definition: card.definition_ja,
			nuance: card.nuance,
			synonyms: card.synonyms,
			antonyms: card.antonyms,
			example: card.example_sentence,
			jlpt: card.jlpt_level,
		}),
	},
	grammar: {
		exportPath: "/export/grammar",
		tag: "N2::Grammar",
		fieldDefs: [
			["pattern", "Pattern", "input"],
			["connection", "Connection", "input"],
			["meaning", "Meaning", "textarea"],
			["nuance", "Nuance", "textarea"],
			["similar_patterns", "Similar Patterns", "textarea"],
			["example_sentence", "Example Sentence", "textarea"],
			["jlpt_level", "JLPT Level", "input"],
		],
		values: (card) => ({ ...card }),
	},
	reading: {
		exportPath: "/export/reading",
		tag: "N2::Reading",
		fieldDefs: [
			["topic", "Topic", "input"],
			["passage", "Passage", "textarea"],
			["question", "Question", "textarea"],
			["answer", "Answer", "textarea"],
			["vocab_notes", "Vocab Notes", "textarea"],
			["jlpt_level", "JLPT Level", "input"],
		],
		values: (card) => ({ ...card }),
	},
};

function buildDatasetCarouselCard(result) {
	const config = DATASET_SECTION_CONFIG[result.section];
	const card = document.createElement("div");
	card.className = "carousel-card" + (result.error ? " error" : "");

	const label = document.createElement("div");
	label.className = "word-label";
	label.textContent = result.item;
	card.appendChild(label);

	if (result.error) {
		const errorText = document.createElement("div");
		errorText.textContent = result.error;
		card.appendChild(errorText);

		const retryHint = document.createElement("div");
		retryHint.className = "retry-hint";
		retryHint.textContent =
			"Try generating this dataset again- a solo request sometimes succeeds " +
			"where an entry failed (malformed JSON, transient API error, etc).";
		card.appendChild(retryHint);

		return card;
	}

	const values = config.values(result.card);
	const cardFields = {};
	for (const [key, labelText, tag] of config.fieldDefs) {
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
		const payload = {
			...Object.fromEntries(
				Object.entries(cardFields).map(([key, el]) => [key, el.value]),
			),
			tags: [config.tag],
		};

		try {
			const response = await fetch(`${BACKEND_URL}${config.exportPath}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});

			if (!response.ok) throw new Error("export-failed");

			const data = await response.json();
			cardExportBtn.textContent = data.status === "duplicate" ? "Already in Anki" : "Exported";
			cardExportBtn.disabled = true;
		} catch (err) {
			showDatasetStatus(
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

datasetGenerateBtn.addEventListener("click", async () => {
	const section = datasetSection.value;

	clearDatasetStatus();
	datasetCarousel.innerHTML = "";
	datasetGenerateBtn.disabled = true;
	datasetGenerateBtn.textContent = "Generating...";

	showDatasetStatus(
		"Generating... structured JSON output can take a while per item (up to a few minutes each)- see README Troubleshooting if it seems stuck.",
		"info",
	);

	try {
		const response = await fetch(`${BACKEND_URL}/generate/dataset`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				section,
				level: "N2",
				mode: document.querySelector('input[name="genMode"]:checked').value,
			}),
		});

		if (!response.ok) {
			const data = await response.json().catch(() => null);
			throw new Error(data?.detail || "bad-response");
		}

		let total = null;
		let progressIndex = null;
		let hasRetried = false;

		await readNdjsonLines(response, (event) => {
			if ("event" in event) {
				if (event.index !== progressIndex) {
					progressIndex = event.index;
					hasRetried = false;
				}
				if (event.event === "retry") hasRetried = true;
				datasetProgress.classList.add("visible");
				datasetStage.textContent =
					`"${event.item}" (${event.index + 1}/${total ?? "?"}) - ` +
					progressStageText(event, hasRetried);
				datasetElapsed.textContent = `${event.elapsed_s}s`;
				return;
			}

			if (!("result" in event)) {
				total = event.total;
				showDatasetStatus(`Generating... 0/${total} done.`, "info");
				return;
			}

			const completed = event.completed;
			total = event.total;
			datasetCarousel.appendChild(buildDatasetCarouselCard(event.result));
			showDatasetStatus(
				`Generating... ${completed}/${total} done. Each item can take up ` +
					"to a few minutes- see README Troubleshooting if it seems stuck.",
				"info",
			);
			datasetProgress.classList.remove("visible");
		});
	} catch (err) {
		showDatasetStatus(
			err.message && err.message !== "bad-response"
				? err.message
				: "Failed to reach the backend. Is the Python service running?",
			"error",
		);
	} finally {
		datasetGenerateBtn.disabled = false;
		datasetGenerateBtn.textContent = "Generate from Dataset";
		datasetProgress.classList.remove("visible");
	}
});

