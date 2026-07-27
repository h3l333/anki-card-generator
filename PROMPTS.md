# Prompts

Prompt templates used for card generation. Kept here so changes are tracked
separately from the code that uses them.

## Model

Current model: `yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b`

Chosen for Japanese-specific tuning over generic general-purpose models (see
`scripts/test_ollama.sh` for the original comparison tests).

Test it directly, independent of the application - useful for isolating
whether a bad or slow card came from the prompt/backend code versus the model
itself:

```bash
docker exec -it ollama_japanese_llm ollama run yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b
```

## Card generation prompt

All four generation features (definition, nuance, example sentence, JLPT
estimate) are requested in a single call - see `backend/llm.py`.

**Prompt template:**

```text
対象語: 「{word}」

あなたは日本語学習者(中級〜上級)向けの辞書カードを作成します。
必ず「{word}」についてのみ回答してください。他の単語やより一般的な例に置き換えないでください。

次の情報をJSON形式で生成してください:
- expression: 「{word}」の表記(漢字・かな)
- reading: 「{word}」のひらがなでの読み方
- definition_ja: 「{word}」の日本語のみによる定義(モノリンガル)
- nuance: 「{word}」の使い方のニュアンス、フォーマル度、類似語との違いなどの説明
- example_sentence: 「{word}」を使った自然な例文。ふりがなは付けず、漢字とかなのみのプレーンテキストで書いてください。
- jlpt_level: 「{word}」の推定されるJLPTレベル(N5〜N1のいずれか)

繰り返しますが、対象語は「{word}」です。
```

**Output schema:** `backend/models.py::CardDraft`

**Known issue:** this is a distilled _reasoning_ model- it produces
chain-of-thought before the final structured answer, which on modest
hardware has measured at roughly 2 tokens/sec. A single card can take
several minutes to generate. Worth keeping in mind for frontend UX
(loading state expectations) and worth revisiting if a faster or
non-reasoning model would give better latency for this task.

Separately, `backend/llm.py` enforces `format=CardDraft.model_json_schema()`
on the Ollama call, which grammar-constrains output to the schema from the
first token. For a model trained to reason freely before answering, this may
conflict with its normal thinking phase- a plausible contributor to topic
drift (see change log below), distinct from prompt wording alone.

## Change log

- 2026-07-25: initial prompt and model choice documented alongside the first
  working backend implementation.
- 2026-07-26: observed the model occasionally ignoring the target word
  mid-generation (drifting to an unrelated word) and inventing ad hoc
  furigana notation not specified by the prompt. Mitigated by: anchoring the
  target word at the start, middle, and end of the prompt; dropping the
  furigana requirement from `example_sentence` (now plain kanji/kana text,
  matching the `CardDraft.example_sentence` field description); and adding a
  retry-once check in `generate_card()` that verifies `expression` actually
  contains the requested word before returning. Not fully confirmed to solve
  drift given the schema-constraint concern above- still worth an end-to-end
  retest, and worth revisiting a two-stage (reason-then-extract) generation
  approach or a non-reasoning model if drift persists.
