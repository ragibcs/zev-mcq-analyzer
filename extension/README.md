# Jev MCQ Analyzer — Browser Extension

Chrome (Manifest V3) extension for the Jev MCQ Confidence Analyzer backend.

## What it does

1. **Extract** — pulls the MCQ question + options from the current tab
   (selected text, radio/checkbox groups, or lists) or paste manually.
2. **Analyze** — sends `{question, options}` to `POST /api/v1/analyze`;
   shows Jev's predicted option, confidence, and the full probability distribution.
3. **Explain** — sends the Jev result to `POST /api/v1/explain`; shows the LLM's
   reasoning summary (requires an LLM provider configured on the backend, see
   `LLM_PROVIDER` in `backend/.env.example`).

### Prediction on the page itself

The prediction appears **in the page**, not only in the popup:

- A floating **J** button (bottom-right) detects MCQs on the page. If several
  are found, a **picker panel** lists them all — click one to analyze it. With
  exactly one MCQ, analysis starts immediately.
- The prediction card anchors near the analyzed question (drag it anywhere),
  shows the predicted option, confidence %, sorted probability bars, and a
  **Why?** button for the LLM explanation.
- Detection strategies: radio/checkbox groups (one MCQ per group), `<ul>/<ol>`
  lists preceded by a question-like node, plain-text patterns
  (`12. question…?` followed by `a. option` lines), and **Google Forms**
  (`div[role=listitem]`/`role=radio` ARIA widgets — embedded form iframes
  work too, via `all_frames`).
- Analyzing from the popup also mirrors the result into the page overlay.
- Page content is isolated: the card lives in a closed shadow root with
  `all: initial`, and site scripts cannot read or restyle it.

## Files

| File | Role |
|---|---|
| `manifest.json` | MV3 manifest — permissions: `storage`, `activeTab`, `scripting` |
| `background.js` | Service worker — routes messages → backend calls; per-tab explain context |
| `content.js` | Page extractor (selection / inputs / lists) + floating **J** button |
| `overlay.js` | In-page prediction card (Shadow DOM): prediction, bars, Why? |
| `popup.html/css/js` | Popup UI: question, options, result, distribution bars |
| `options.html/js` | Standalone settings page (same fields as popup ⚙) |
| `lib/backend.js` | Fetch wrapper for `/api/v1/*` |
| `lib/messages.js` | Message-type constants shared by popup/content/worker |

## Setup

### 1. Backend

```bash
cd backend
cp .env.example .env
# Edit .env: set JEV_API_KEY (and LLM_PROVIDER if you want explanations)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### 2. Allow the extension origin in backend CORS

The extension origin is `chrome-extension://<extension-id>`. After loading the
extension, copy its ID from `chrome://extensions` and set it in `backend/.env`:

```
CORS_ORIGINS=chrome-extension://<your-extension-id>
```

(For development you can list several origins, comma-separated. Alternatively
Chrome sends `Origin: chrome-extension://...` and FastAPI's CORSMiddleware will
only accept explicitly allowed origins — a wildcard will not work with
credentials, and this backend deliberately uses an explicit allow-list.)

### 3. Optional API key

If you set `API_KEY` in `backend/.env`, put the same value in the extension's
⚙ settings ("API key"). It is sent as the `X-API-Key` header.

### 4. Load the extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select this `extension/` folder
4. Open the popup → ⚙ → set Backend URL (default `http://localhost:8000`)

## Try it

**On the page (recommended):**

1. Start the backend and open any quiz page.
2. Click the floating **J** button (bottom-right).
3. The prediction card appears on the page — prediction, confidence, bars.
4. Click **Why?** in the card for the LLM explanation.

**From the popup:**

1. Click the extension icon.
2. Click **Extract from page** (or paste question + options, one per line).
3. Click **Analyze** → result shows in the popup *and* as a card on the page.
4. Click **Why? (explain)** → LLM summary (needs `LLM_PROVIDER` ≠ `none`).

## Limitations / next steps

- Extraction heuristics are generic (radio/checkbox/list/text patterns).
  Multiple MCQs per page are supported via the in-page picker; per-site
  selectors (Moodle, Google Forms, etc.) can be added later.
- No keyboard shortcut yet (`commands` in manifest).
- Options are re-lettered A/B/C… on send; if the site uses different ids the
  display maps by text.
- Firefox (MV3) is not configured yet — needs `browser_specific_settings`.
