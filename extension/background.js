/**
 * MV3 service worker: routes messages between popup/content script and backend.
 *
 * Two entry paths:
 *  - popup "analyze"/"explain"  → responds to the popup directly
 *  - page  "analyze-from-page"  → analyzes and pushes the result into the
 *    page overlay (chrome.tabs.sendMessage to the originating tab)
 */

import { analyze, explain, getProviders } from "./lib/backend.js";
import { ANALYZE, EXPLAIN, PING } from "./lib/messages.js";

const DEFAULT_SETTINGS = {
  baseUrl: "http://localhost:8000",
  apiKey: "",
};

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.sync.get(DEFAULT_SETTINGS, (settings) => {
    // Seed defaults on first install so popup always has a baseUrl.
    chrome.storage.sync.set(settings);
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  handleMessage(message, sender)
    .then(sendResponse)
    .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
  return true; // async response
});

async function handleMessage(message, sender) {
  switch (message.type) {
    case PING: {
      const { baseUrl } = await loadSettings();
      const providers = await getProviders(baseUrl).catch(() => null);
      return { ok: true, providers };
    }

    case ANALYZE: {
      const { baseUrl, apiKey } = await loadSettings();
      const result = await analyze(baseUrl, apiKey, {
        question: message.question,
        options: message.options,
      });
      return { ok: true, result };
    }

    case EXPLAIN: {
      const { baseUrl, apiKey } = await loadSettings();
      const result = await explain(baseUrl, apiKey, {
        question: message.question,
        options: message.options,
        jevResult: message.jevResult,
      });
      return { ok: true, result };
    }    // ── In-page flow: prediction shows on the page itself ───────────
    case "analyze-from-page": {
      const tabId = sender?.tab?.id;
      if (!tabId) return { ok: false, error: "No originating tab." };
      // Route replies (status/result) to the frame that sent the message,
      // so results appear in the right frame when the MCQ lives in an
      // embedded Google Forms iframe.
      const frameId = sender?.frameId ?? 0;
      const reply = (msg) => sendToTab(tabId, msg, frameId);

      const { baseUrl, apiKey } = await loadSettings();
      reply({ type: "overlay-status", text: "Analyzing…" });

      try {
        const result = await analyze(baseUrl, apiKey, {
          question: message.question,
          options: message.options,
        });
        reply({
          type: "show-overlay-result",
          payload: {
            question: message.question,
            options: message.options,
            result,
            // DOMRect is not structured-cloneable — copy the numeric fields.
            anchorRect: toPlainRect(message.anchorRect),
          },
        });
        // Remember context so the overlay's "Why?" can call /explain.
        pageContexts.set(tabId, {
          question: message.question,
          options: message.options,
          jevResult: result,
        });
        return { ok: true };
      } catch (err) {
        reply({
          type: "overlay-status",
          text: String(err.message || err),
          isError: true,
        });
        return { ok: false, error: String(err.message || err) };
      }
    }

    // ── Multi-MCQ: FAB detected several MCQs → show the picker ──────
    case "show-mcq-picker": {
      const tabId = sender?.tab?.id;
      if (!tabId) return { ok: false, error: "No originating tab." };
      // runtime.sendMessage from a content script never reaches overlay.js
      // in the same frame, so bounce the picker back to the exact frame
      // that detected the MCQs.
      sendToTab(tabId, { type: "show-mcq-picker", mcqs: message.mcqs }, sender?.frameId ?? 0);
      return { ok: true };
    }

    // ── Multi-MCQ: user picked one MCQ in the page picker ───────────
    case "picker-selected": {
      const tabId = sender?.tab?.id;
      if (!tabId) return { ok: false, error: "No originating tab." };
      // Forward back to the SAME frame's content script, which remembers
      // the detected MCQ list (window.__jevPickerMcqs) and starts the
      // analysis. The subsequent analyze-from-page also comes from that
      // frame, so results stay in it.
      sendToTab(tabId, { type: "picker-selected", index: message.index }, sender?.frameId ?? 0);
      return { ok: true };
    }

    case "overlay-explain": {
      const tabId = sender?.tab?.id;
      if (!tabId) return { ok: false, error: "No originating tab." };
      const frameId = sender?.frameId ?? 0;

      const ctx = pageContexts.get(tabId);
      if (!ctx) return { ok: false, error: "No analysis context for this tab." };

      const { baseUrl, apiKey } = await loadSettings();
      sendToTab(tabId, { type: "overlay-status", text: "Explaining…" }, frameId);

      try {
        const result = await explain(baseUrl, apiKey, ctx);
        sendToTab(tabId, { type: "overlay-explain-result", text: result.summary }, frameId);
        return { ok: true };
      } catch (err) {
        sendToTab(tabId, {
          type: "overlay-status",
          text: String(err.message || err),
          isError: true,
        }, frameId);
        return { ok: false, error: String(err.message || err) };
      }
    }

    default:
      return { ok: false, error: `Unknown message type: ${message.type}` };
  }
}

// Per-tab analysis context for the overlay "Why?" button. Service workers can
// be killed between events, so this is best-effort — the overlay shows a hint
// if the context is gone (user re-analyzes to restore it).
const pageContexts = new Map();

chrome.tabs.onRemoved.addListener((tabId) => pageContexts.delete(tabId));

function sendToTab(tabId, message, frameId) {
  const opts = typeof frameId === "number" ? { frameId } : undefined;
  chrome.tabs.sendMessage(tabId, message, opts).catch(() => {
    /* overlay not injected in this tab/frame — ignore */
  });
}

/** DOMRect → plain {top,left,right,bottom,width,height} for messaging. */
function toPlainRect(rect) {
  if (!rect || typeof rect !== "object") return null;
  return {
    top: rect.top,
    left: rect.left,
    right: rect.right,
    bottom: rect.bottom,
    width: rect.width,
    height: rect.height,
  };
}

function loadSettings() {
  return chrome.storage.sync.get(DEFAULT_SETTINGS);
}
