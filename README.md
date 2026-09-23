# Zev MCQ Analyzer

A Chrome extension + FastAPI backend that uses the **Jev decision engine** to predict the most likely answer to a multiple-choice question and explain its reasoning via an LLM.

---

## How it works

1. **Extract** — the extension detects MCQ questions on the current page (radio groups, checkbox groups, ordered/unordered lists, plain-text patterns, Google Forms) or lets you paste manually.
2. **Analyze** — sends `{ question, options }` to `POST /api/v1/analyze`. The backend forwards it to Jev, which returns the predicted option + a full probability distribution over all choices.
3. **Explain** — optionally sends the Jev result to `POST /api/v1/explain`. The backend calls an LLM (Vercel AI Gateway or OpenRouter) and returns a plain-language reasoning summary.

The prediction appears **directly on the page** — a floating **J** button (bottom-right) and an overlay card anchored near the question — not just inside the popup.

---

## Architecture

```
extension/          Chrome MV3 extension
  content.js        Page extractor + floating J button
  overlay.js        In-page prediction card (Shadow DOM)
  background.js     Service worker — routes messages → backend
  popup.*           Popup UI
  options.*         Settings page
  lib/backend.js    Fetch wrapper for /api/v1/*
  lib/messages.js   Shared message-type constants

backend/            FastAPI application
  app/
    api/routes.py           POST /api/v1/analyze, /api/v1/explain
    core/config.py          Pydantic-settings configuration
    core/security.py        API key, rate-limit, body-size middleware
    services/jev/           Jev API client + provider abstraction
    services/llm/           LLM provider abstraction (Vercel / OpenRouter / none)
    services/analysis/      Orchestrates Jev + LLM into one response
  evaluation/               Offline benchmark runner
data/
  mcq_benchmark.json        Sample MCQ benchmark dataset
```

---

## Prerequisites

- Python 3.11+
- A [Jev API key](https://console.typesafe.ai) (`JEV_API_KEY`)
- *(Optional)* A Vercel AI Gateway or OpenRouter API key for LLM explanations
- Chrome 116+ (Manifest V3)

---

## Setup

### 1. Backend

```bash
cd backend
cp .env.example .env
# Edit .env — set at minimum JEV_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API docs are available at `http://localhost:8000/docs`.

### 2. Configure CORS for the extension

After loading the extension (step 4), copy its ID from `chrome://extensions` and add it to `backend/.env`:

```env
CORS_ORIGINS=chrome-extension://<your-extension-id>
```

Restart the backend after editing `.env`.

### 3. Optional: LLM explanations

Set one of the following blocks in `backend/.env`:

```env
# Vercel AI Gateway (default)
LLM_PROVIDER=vercel
VERCEL_AI_GATEWAY_API_KEY=...
VERCEL_AI_GATEWAY_MODEL=openai/gpt-4o-mini

# OpenRouter
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=openai/gpt-4o-mini

# Disable explanations
LLM_PROVIDER=none
```

### 4. Load the extension in Chrome

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked** → select the `extension/` folder
4. Open the popup → ⚙ → set **Backend URL** to `http://localhost:8000`

### 5. Optional: shared API key

Set `API_KEY=<secret>` in `backend/.env` and put the same value in the extension's ⚙ settings ("API key"). It is forwarded as the `X-API-Key` header.

---

## Usage

### On the page (recommended)

1. Start the backend and navigate to any quiz/MCQ page.
2. Click the floating **J** button (bottom-right).
   - If multiple MCQs are detected, a picker panel appears — click one.
   - With exactly one MCQ, analysis starts immediately.
3. A prediction card appears on the page showing:
   - Predicted option + confidence %
   - Full probability distribution (sorted bars)
   - **Why?** button → LLM explanation

### From the popup

1. Click the extension icon.
2. Click **Extract from page** or paste question + options (one per line).
3. Click **Analyze** — result appears in the popup *and* as an in-page card.
4. Click **Why? (explain)** for the LLM reasoning summary.

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `JEV_API_KEY` | Yes | — | Jev decision engine key |
| `JEV_MODEL` | No | `type-safe/jev-latest` | Jev model identifier |
| `JEV_BASE_URL` | No | `https://ai-gateway.vercel.sh/v1` | Jev API base URL |
| `LLM_PROVIDER` | No | `vercel` | `vercel` / `openrouter` / `none` |
| `VERCEL_AI_GATEWAY_API_KEY` | If provider=vercel | — | |
| `VERCEL_AI_GATEWAY_MODEL` | No | `type-safe/jev-latest` | |
| `OPENROUTER_API_KEY` | If provider=openrouter | — | |
| `OPENROUTER_MODEL` | If provider=openrouter | — | |
| `CORS_ORIGINS` | Yes (for extension) | — | Comma-separated allowed origins |
| `API_KEY` | No | — | Optional shared secret (X-API-Key) |
| `LOG_LEVEL` | No | `INFO` | Uvicorn log level |

---

## Running tests

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

---

## Running the benchmark

```bash
cd backend
python -m evaluation.run_benchmark --dataset ../data/mcq_benchmark.json
```

---

## Limitations

- Extraction heuristics are generic; per-site selectors (Moodle, Canvas, etc.) can be added to `content.js`.
- Firefox (MV3) is not configured yet — needs `browser_specific_settings` in the manifest.
- No keyboard shortcut is bound yet (`commands` key in manifest is not set).

---

## License

MIT
