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
日本語学習者(中級〜上級)向けに、次の単語についての情報をJSON形式で生成してください。

対象語: {word}

含める情報:
- expression: 単語の表記(漢字・かな)
- reading: ひらがなでの読み方
- definition_ja: 日本語のみによる単語の定義(モノリンガル)
- nuance: 使い方のニュアンス、フォーマル度、類似語との違いなどの説明
- example_sentence: ふりがな付きの自然な例文
- jlpt_level: 推定されるJLPTレベル(N5〜N1のいずれか)
```

**Output schema:** `backend/models.py::CardDraft`

**Known issue:** this is a distilled *reasoning* model - it produces
chain-of-thought before the final structured answer, which on modest
hardware has measured at roughly 2 tokens/sec. A single card can take
several minutes to generate. Worth keeping in mind for frontend UX
(loading state expectations) and worth revisiting if a faster or
non-reasoning model would give better latency for this task.

## Change log

- 2026-07-25: initial prompt and model choice documented alongside the first
  working backend implementation.
