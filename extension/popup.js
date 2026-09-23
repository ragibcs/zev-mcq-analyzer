/**
 * Popup controller: extraction, analyze, explain, settings.
 */

const $ = (id) => document.getElementById(id);

const els = {
  question: $("question"),
  options: $("options"),
  extract: $("extract-btn"),
  analyze: $("analyze-btn"),
  explain: $("explain-btn"),
  result: $("result"),
  prediction: $("prediction"),
  confidence: $("confidence"),
  distribution: $("distribution"),
  explanation: $("explanation"),
  status: $("status"),
  settingsBtn: $("settings-btn"),
  mainView: $("main-view"),
  settingsView: $("settings-view"),
  baseUrl: $("base-url"),
  apiKey: $("api-key"),
  backBtn: $("back-btn"),
  saveBtn: $("save-btn"),
  settingsStatus: $("settings-status"),
  barTemplate: $("bar-row"),
};

let lastResult = null;

document.addEventListener("DOMContentLoaded", () => {
  els.extract.addEventListener("click", handleExtract);
  els.analyze.addEventListener("click", handleAnalyze);
  els.explain.addEventListener("click", handleExplain);
  els.settingsBtn.addEventListener("click", openSettings);
  els.backBtn.addEventListener("click", closeSettings);
  els.saveBtn.addEventListener("click", saveSettings);

  chrome.storage.sync.get({ baseUrl: "", apiKey: "" }, ({ baseUrl }) => {
    if (!baseUrl) setStatus("Set your backend URL in ⚙ settings.", true);
  });
});

// ── Extraction ───────────────────────────────────────────────────────

async function handleExtract() {
  setStatus("Extracting from page…");
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) {
    setStatus("No active tab found.", true);
    return;
  }

  let response;
  try {
    // Broadcasts to all frames; content.js only answers from frames that
    // actually hold an MCQ (embedded Google Forms iframes included).
    response = await chrome.tabs.sendMessage(tab.id, { type: "extract-selection" });
  } catch {
    // Content script not injected (e.g. extension was reloaded after the
    // page loaded) — inject into every frame, then retry.
    try {
      await chrome.scripting.executeScript({
        target: { tabId: tab.id, allFrames: true },
        files: ["content.js", "overlay.js"],
      });
      response = await chrome.tabs.sendMessage(tab.id, { type: "extract-selection" });
    } catch (err) {
      setStatus(`Cannot read this page: ${err.message}`, true);
      return;
    }
  }

  if (!response || !response.ok) {
    setStatus("Extraction failed.", true);
    return;
  }

  const { question, options } = response.mcq || {};
  if (question) els.question.value = question;
  if (options && options.length >= 2) {
    els.options.value = options.map((o) => o.text).join("\n");
    setStatus(`Extracted ${options.length} options.`, false, "ok");
  } else if (question) {
    setStatus("Question captured; enter options manually.", false, "ok");
  } else {
    setStatus("Nothing found — paste the question and options.", true);
  }
}

// ── Analyze ──────────────────────────────────────────────────────────

async function handleAnalyze() {
  const question = els.question.value.trim();
  const options = parseOptions(els.options.value);

  if (!question) return setStatus("Enter a question first.", true);
  if (options.length < 2) return setStatus("Need at least 2 options (one per line).", true);

  els.analyze.disabled = true;
  setStatus("Analyzing…");
  hide(els.result);

  const res = await chrome.runtime.sendMessage({
    type: "analyze",
    question,
    options: options.map((text, i) => ({ id: letter(i), text })),
  });

  els.analyze.disabled = false;
  if (!res || !res.ok) {
    setStatus(res?.error || "Analyze failed.", true);
    return;
  }

  lastResult = res.result;
  renderResult(res.result);
  setStatus("Done.", false, "ok");

  // Mirror the prediction into the page overlay (site er moddhei dekha jay).
  const analyzedOptions = options.map((text, i) => ({ id: letter(i), text }));
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      await chrome.tabs.sendMessage(tab.id, {
        type: "show-overlay-result",
        payload: { question, options: analyzedOptions, result: res.result },
      });
    }
  } catch {
    /* page can't host the overlay (chrome:// etc.) — popup still shows it */
  }
}

function renderResult(result) {
  els.prediction.textContent = result.predicted_option;
  els.prediction.title = result.predicted_option;
  els.confidence.textContent = `${Math.round((result.confidence || 0) * 100)}%`;

  els.distribution.textContent = "";
  const rows = [...(result.distribution || [])].sort((a, b) => b.probability - a.probability);
  for (const row of rows) {
    const node = els.barTemplate.content.cloneNode(true);
    node.querySelector(".bar-label").textContent = row.option_text || row.option_id;
    node.querySelector(".bar-label").title = row.option_text || row.option_id;
    node.querySelector(".bar-fill").style.width = `${Math.round(row.probability * 100)}%`;
    node.querySelector(".bar-pct").textContent = `${Math.round(row.probability * 100)}%`;
    els.distribution.appendChild(node);
  }

  els.explanation.textContent = "";
  hide(els.explanation);
  show(els.result);
}

// ── Explain ──────────────────────────────────────────────────────────

async function handleExplain() {
  if (!lastResult) return;
  els.explain.disabled = true;
  setStatus("Explaining…");

  const res = await chrome.runtime.sendMessage({
    type: "explain",
    question: els.question.value.trim(),
    options: parseOptions(els.options.value).map((text, i) => ({ id: letter(i), text })),
    jevResult: lastResult,
  });

  els.explain.disabled = false;
  if (!res || !res.ok) {
    setStatus(res?.error || "Explanation failed (is an LLM provider configured?).", true);
    return;
  }

  els.explanation.textContent = res.result.summary;
  show(els.explanation);
  setStatus("Done.", false, "ok");
}

// ── Settings ─────────────────────────────────────────────────────────

function openSettings() {
  chrome.storage.sync.get({ baseUrl: "", apiKey: "" }, ({ baseUrl, apiKey }) => {
    els.baseUrl.value = baseUrl;
    els.apiKey.value = apiKey;
  });
  hide(els.mainView);
  show(els.settingsView);
}

function closeSettings() {
  hide(els.settingsView);
  show(els.mainView);
}

function saveSettings() {
  let base = els.baseUrl.value.trim().replace(/\/+$/, "");
  if (base && !/^https?:\/\//.test(base)) base = `http://${base}`;
  chrome.storage.sync.set({ baseUrl: base, apiKey: els.apiKey.value.trim() }, () => {
    els.settingsStatus.textContent = "Saved.";
    els.settingsStatus.classList.add("ok");
    setTimeout(() => {
      els.settingsStatus.textContent = "";
      els.settingsStatus.classList.remove("ok");
      closeSettings();
    }, 700);
  });
}

// ── Helpers ──────────────────────────────────────────────────────────

function parseOptions(raw) {
  return raw
    .split("\n")
    .map((line) => line.replace(/^\s*[A-Za-z0-9]+[.)]\s+/, "").trim())
    .filter(Boolean);
}

function letter(i) {
  // Option ids only need to be unique per request (max 64 chars per backend).
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  return i < 26 ? alphabet[i] : `O${i + 1}`;
}

function setStatus(text, isError = false, ok = false) {
  els.status.textContent = text;
  els.status.classList.toggle("error", isError);
  els.status.classList.toggle("ok", ok && !isError);
}

function show(el) { el.classList.remove("hidden"); }
function hide(el) { el.classList.add("hidden"); }
