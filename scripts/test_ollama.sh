#!/usr/bin/env bash

echo -e "\n--- Testing REST API (JSON Schema) ---"

# Test 1: Curl call targeting the local Ollama container or host
curl -s http://localhost:11435/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b",
    "prompt": "Provide a dictionary entry for 飛行機.",
    "stream": false,
    "format": {
      "type": "object",
      "properties": {
        "word": { "type": "string" },
        "reading": { "type": "string" },
        "definition": { "type": "string" }
      },
      "required": ["word", "reading", "definition"]
    }
  }'

# Test 2: Curl call inquiring about nuances within the Japanese language, targeting the Ollama container
curl -s http://localhost:11435/api/generate \
  -H "Content-Type: application/json" \
  -d '{
    "model": "yuma/DeepSeek-R1-Distill-Qwen-Japanese:14b",
    "prompt": "日本語の国語辞典および類語辞典の専門家として、「活用」と「用いる」の違い、それぞれの意味、使い分けを日本語のみで詳しく解説してください。",
    "stream": false,
    "format": {
      "type": "object",
      "properties": {
        "word_1": {
          "type": "object",
          "properties": {
            "term": { "type": "string" },
            "reading": { "type": "string" },
            "definition": { "type": "string" },
            "example": { "type": "string" }
          },
          "required": ["term", "reading", "definition", "example"]
        },
        "word_2": {
          "type": "object",
          "properties": {
            "term": { "type": "string" },
            "reading": { "type": "string" },
            "definition": { "type": "string" },
            "example": { "type": "string" }
          },
          "required": ["term", "reading", "definition", "example"]
        },
        "key_difference": { "type": "string" },
        "usage_tip": { "type": "string" }
      },
      "required": ["word_1", "word_2", "key_difference", "usage_tip"]
    }
  }'