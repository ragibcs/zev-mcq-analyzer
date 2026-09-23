/**
 * Content script: MCQ extractor (multi-MCQ aware) + floating action button.
 *
 * The extractor is exposed as window.__jevExtractMcqs so overlay.js can build
 * a picker when a page contains multiple MCQs. The floating "J" button opens
 * the picker (or analyzes directly when exactly one MCQ is found) — the
 * prediction card appears on the page itself (overlay.js).
 */

(() => {
  if (window.__jevAnalyzerInstalled) return;
  window.__jevAnalyzerInstalled = true;

  const MAX_QUESTION_CHARS = 8000; // must match backend max_question_chars
  const MAX_OPTION_CHARS = 2000; // must match backend Option.text max

  const FAB_ID = "jev-mcq-analyzer-fab";

  // ── Floating action button ────────────────────────────────────────

  function ensureFab() {
    if (document.getElementById(FAB_ID)) return;
    if (!window.location.protocol.startsWith("http")) return;
    // Only show the FAB in the top frame or in embeddable quiz frames
    // (e.g. Google Forms embedded via /viewform?embedded=true). Inner
    // ad/analytics iframes must stay quiet.
    const isTop = window === window.top;
    const isQuizFrame = /docs\.google\.com\/forms/.test(window.location.href);
    if (!isTop && !isQuizFrame) return;

    const fab = document.createElement("button");
    fab.id = FAB_ID;
    fab.type = "button";
    fab.textContent = "J";
    fab.title = "Find MCQs on this page";
    fab.style.cssText = [
      "all:initial",
      "position:fixed",
      "right:14px",
      "bottom:14px",
      "z-index:2147483600",
      "width:36px",
      "height:36px",
      "border-radius:50%",
      "background:#1f2430",
      "color:#4f8cff",
      "border:1px solid #2a3040",
      "font:700 15px/36px system-ui, sans-serif",
      "text-align:center",
      "cursor:pointer",
      "box-shadow:0 4px 14px rgba(0,0,0,.35)",
      "user-select:none",
    ].join(";");
    fab.addEventListener("mouseenter", () => (fab.style.background = "#2a3040"));
    fab.addEventListener("mouseleave", () => (fab.style.background = "#1f2430"));

    fab.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const mcqs = window.__jevExtractMcqs();
      window.__jevPickerMcqs = mcqs; // for the picker → analyze round-trip
      if (mcqs.length === 0) {
        chrome.runtime.sendMessage({
          type: "overlay-status",
          text: "No MCQ found on this page — select the question text and try again.",
          isError: true,
        });
        return;
      }
      if (mcqs.length === 1) {
        analyzeMcq(mcqs[0]);
        return;
      }
      chrome.runtime.sendMessage({ type: "show-mcq-picker", mcqs });
    });

    document.documentElement.appendChild(fab);
  }

  function analyzeMcq(mcq) {
    chrome.runtime.sendMessage({
      type: "analyze-from-page",
      question: mcq.question,
      options: mcq.options,
      // DOMRect is not reliably structured-cloneable across contexts —
      // send a plain numeric snapshot for overlay positioning.
      anchorRect: plainRect(mcq.rect),
    });
  }

  function plainRect(rect) {
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", ensureFab, { once: true });
  } else {
    ensureFab();
  }

  // ── Messages ──────────────────────────────────────────────────────

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "extract-selection") {
      const mcq = extractMcq();
      // Respond only when this frame actually holds an MCQ — with
      // all_frames content scripts, empty frames must not shadow the
      // real answer (the first response wins).
      if (mcq.question || mcq.options.length >= 2) {
        sendResponse({ ok: true, mcq });
      }
      return false;
    } else if (message.type === "picker-selected") {
      // background.js forwarded the user's picker choice back to this tab.
      const mcq = (window.__jevPickerMcqs || [])[message.index];
      if (mcq) analyzeMcq(mcq);
      sendResponse({ ok: true });
    }
    return true;
  });

  // ── Multi-MCQ extraction ──────────────────────────────────────────

  /**
   * Public entry: every detected MCQ with backend-safe ids and lengths.
   * Each entry: { question, options: [{id, text}], rect }
   * rect anchors the overlay card near the question (best effort).
   */
  function extractMcqs() {
    const results = [];
    const seen = new Set();

    // 0. Google Forms (and similar ARIA-widget apps): div[role=radio], no
    //    real inputs — must run before the generic strategies.
    for (const mcq of extractFromGoogleForms()) {
      const key = mcqKey(mcq);
      if (mcq.question && !seen.has(key)) {
        seen.add(key);
        results.push(mcq);
      }
    }

    // 1. Radio/checkbox groups — one MCQ per group.
    for (const mcq of extractFromInputs()) {
      const key = mcqKey(mcq);
      if (mcq.question && !seen.has(key)) {
        seen.add(key);
        results.push(mcq);
      }
    }

    // 2. List-based MCQs (ul/ol preceded by a question-ish heading).
    for (const mcq of extractFromLists()) {
      const key = mcqKey(mcq);
      if (mcq.question && !seen.has(key)) {
        seen.add(key);
        results.push(mcq);
      }
    }

    // 3. Text MCQs: "N. question?" followed by "a. option" lines/paragraphs.
    for (const mcq of extractFromTextBlocks()) {
      const key = mcqKey(mcq);
      if (!seen.has(key)) {
        seen.add(key);
        results.push(mcq);
      }
    }

    // 4. Selection fallback: single MCQ from the highlighted text.
    const selection = selectedText();
    if (selection && !results.some((m) => selection.startsWith(m.question.slice(0, 60)))) {
      const selMcq = parseMcqText(selection);
      if (selMcq && selMcq.options.length >= 2) {
        results.unshift(selMcq); // explicit user selection first
      } else if (selection.includes("?") && !results.length) {
        results.push({ question: clip(selection), options: [], rect: selRect() });
      }
    }

    return results;
  }

  function mcqKey(mcq) {
    return (
      mcq.question.slice(0, 80).toLowerCase() +
      "|" +
      mcq.options
        .slice(0, 6)
        .map((o) => o.text.slice(0, 40).toLowerCase())
        .join("~")
    );
  }

  // ── Strategy 0: Google Forms (ARIA widgets, no real inputs) ───────

  /**
   * Google Forms renders each question as div[role=listitem], the title as
   * div[role=heading], and options as div[role=radio|checkbox] with the
   * option text in aria-label. There are no visible <input> elements, so the
   * generic extractors find nothing.
   */
  function extractFromGoogleForms() {
    const items = document.querySelectorAll('div[role="listitem"]');
    if (!items.length) return [];

    const results = [];
    for (const item of items) {
      const widgets = item.querySelectorAll(
        'div[role="radio"], div[role="checkbox"]'
      );
      if (widgets.length < 2 || widgets.length > 12) continue;

      const heading = item.querySelector('[role="heading"]');
      // Strip the trailing "*" Forms adds to required questions.
      const question = (heading ? normalize(heading.textContent) : "")
        .replace(/\s*\*\s*$/, "")
        .trim();
      if (!question) continue;

      const options = [];
      const seen = new Set();
      for (const widget of widgets) {
        // Skip the "Other:" free-text option (it contains a text input).
        if (widget.querySelector('input[type="text"]')) continue;
        const labelled =
          widget.getAttribute("aria-label") ||
          (widget.querySelector("[aria-label]") || {}).getAttribute?.("aria-label") ||
          "";
        const text = normalize(labelled || widget.textContent || "");
        if (!text || text.length > MAX_OPTION_CHARS) continue;
        const key = text.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        options.push({ id: text, text });
      }
      if (options.length >= 2) {
        results.push({
          question: clip(question),
          options,
          rect: rectOf(item),
        });
      }
    }
    return results;
  }

  function extractFromInputs() {
    const inputs = Array.from(
      document.querySelectorAll('input[type="radio"], input[type="checkbox"]')
    ).filter((el) => !el.disabled && isVisible(el));

    const groups = new Map();
    for (const input of inputs) {
      const key = input.name || `__anonymous_${groupId(input)}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(input);
    }

    const results = [];
    for (const [, group] of groups) {
      if (group.length < 2 || group.length > 12) continue;
      const options = group
        .map((el) => labelFor(el))
        .filter(Boolean)
        .map((text) => ({ id: text, text }));
      const seen = new Set();
      const unique = options.filter((o) => {
        const k = o.text.toLowerCase();
        if (seen.has(k)) return false;
        seen.add(k);
        return true;
      });
      if (unique.length >= 2) {
        const question = findQuestionForGroup(group[0]);
        if (question) {
          results.push({
            question,
            options: unique,
            rect: rectOf(group[0].closest("label") || group[0]),
          });
        }
      }
    }
    return results;
  }

  // ── Strategy 2: lists preceded by a question-like node ────────────

  function extractFromLists() {
    const results = [];
    for (const list of document.querySelectorAll("ul, ol")) {
      const items = Array.from(list.querySelectorAll(":scope > li"))
        .map((li) => li.textContent.trim())
        .filter((t) => t && t.length <= MAX_OPTION_CHARS);
      const unique = [...new Set(items)];
      if (unique.length < 2 || unique.length > 12) continue;

      const question = findQuestionForList(list);
      if (!question) continue;
      const anchor =
        list.previousElementSibling ||
        list.closest("section, .question, [class*='question']") ||
        list;
      results.push({
        question,
        options: unique.map((t) => ({ id: t, text: t })),
        rect: rectOf(anchor),
      });
    }
    return results;
  }

  // ── Strategy 3: plain-text MCQ patterns ───────────────────────────

  const Q_NUM = /^\s*(\d{1,3})\s*[.)]\s+(.{0,8000})$/;
  const OPT_LINE = /^\s*([A-Da-d])\s*[).:]\s+(.+)$/;
  const BLOCK_TAGS = new Set(["P", "DIV", "LI", "H1", "H2", "H3", "H4", "SPAN", "TD"]);

  function extractFromTextBlocks() {
    const results = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.parentElement) return NodeFilter.FILTER_REJECT;
        const tag = node.parentElement.tagName;
        return BLOCK_TAGS.has(tag) && node.textContent.trim().length > 3
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    });

    let qNum = null;
    let qText = null;
    let qRectNode = null;
    let options = null;

    const flush = () => {
      if (qNum !== null && qText && options && options.length >= 2) {
        results.push({
          question: `${qNum}. ${qText}`,
          options,
          rect: qRectNode ? rectOf(qRectNode) : null,
        });
      }
      qNum = null;
      qText = null;
      qRectNode = null;
      options = null;
    };

    while (walker.nextNode()) {
      const text = walker.currentNode.textContent.trim();
      const node = walker.currentNode.parentElement;
      const qMatch = text.match(Q_NUM);
      const optMatch = text.match(OPT_LINE);

      if (qMatch && qMatch[2].includes("?")) {
        flush();
        qNum = qMatch[1];
        qText = qMatch[2];
        qRectNode = node;
        options = [];
      } else if (options && qNum !== null && optMatch && optMatch[2].trim().length <= MAX_OPTION_CHARS) {
        const letter = optMatch[1].toUpperCase();
        if (!options.some((o) => o.id === letter)) {
          options.push({ id: letter, text: optMatch[2].trim() });
        }
      } else if (options && qNum !== null && !optMatch && text.length > MAX_OPTION_CHARS) {
        flush();
      }
    }
    flush();
    return results;
  }

  /**
   * Parse a raw text blob (user selection) into an MCQ: numbered question
   * line + a./b. lines, or question line + bare option lines.
   */
  function parseMcqText(raw) {
    const lines = raw.split(/\n+/).map((l) => l.trim()).filter(Boolean);
    if (lines.length < 3) return null;

    const qLineIdx = lines.findIndex((l) => l.includes("?") || /^(?:\d{1,3}[.)]|Q\d*)/i.test(l));
    if (qLineIdx === -1) return null;

    const optionLines = lines.slice(qLineIdx + 1);
    const options = [];
    for (const line of optionLines) {
      const m = line.match(OPT_LINE);
      const text = m ? m[2].trim() : line;
      const id = m ? m[1].toUpperCase() : letterFor(options.length);
      if (text && text.length <= MAX_OPTION_CHARS && !options.some((o) => o.text === text)) {
        options.push({ id, text });
      }
    }
    if (options.length < 2) return null;

    const qm = lines[qLineIdx].match(Q_NUM);
    const question = qm ? qm[2].trim() : lines[qLineIdx];
    return { question: clip(question), options, rect: selRect() };
  }

  // ── Question finders ──────────────────────────────────────────────

  function findQuestionForGroup(input) {
    // Walk up to the question's container, then read its heading/text.
    let node = input.closest("fieldset, form, .question, [class*='question'], [role='radiogroup'], label");
    while (node) {
      const q = extractQuestionFromContainer(node);
      if (q) return q;
      node = node.parentElement;
    }
    return "";
  }

  function findQuestionForList(list) {
    let node = list.previousElementSibling;
    let hops = 0;
    while (node && hops < 6) {
      const text = normalize(node.textContent);
      if (text) {
        // Accept headings, sentences ending in "?" or ":" and numbered items.
        if (/^H[1-4]$/.test(node.tagName) || text.endsWith("?") || text.endsWith(":") || Q_NUM.test(text)) {
          return clip(text);
        }
        return ""; // non-question sibling → list is probably not an MCQ
      }
      node = node.previousElementSibling;
      hops += 1;
    }
    return "";
  }

  function extractQuestionFromContainer(container) {
    const anchor = container.querySelector(
      "h1, h2, h3, h4, .question-text, [class*='question'], [class*='prompt'], legend"
    );
    if (anchor) {
      const text = normalize(anchor.textContent);
      if (text) return clip(text);
    }
    // Fall back to the container's own text minus the option labels.
    const optTexts = new Set();
    container.querySelectorAll("input").forEach((input) => {
      const label = labelFor(input);
      if (label) optTexts.add(label.toLowerCase());
    });
    const own = normalize(container.textContent);
    if (own) {
      let question = own;
      for (const t of optTexts) {
        question = question.replace(new RegExp(t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi"), "");
      }
      question = normalize(question);
      if (question.length > 8) return clip(question);
    }
    return "";
  }

  // ── Selection helpers ─────────────────────────────────────────────

  function selectedText() {
    const sel = window.getSelection();
    return sel ? sel.toString().trim() : "";
  }

  function selRect() {
    try {
      const sel = window.getSelection();
      if (sel && sel.rangeCount > 0 && sel.toString().trim()) {
        return sel.getRangeAt(0).getBoundingClientRect();
      }
    } catch {
      /* ignore */
    }
    return null;
  }

  function rectOf(el) {
    if (!el || !el.getBoundingClientRect) return null;
    try {
      return el.getBoundingClientRect();
    } catch {
      return null;
    }
  }

  // ── Single-MCQ heuristic (kept for the popup "Extract" button) ────

  function extractMcq() {
    const selection = selectedText();
    if (selection) {
      const parsed = parseMcqText(selection);
      if (parsed) return parsed;
      if (selection.includes("?")) return { question: clip(selection), options: [] };
    }

    const structured = extractFromInputs();
    if (structured.length) return pickBest(structured);

    const listBased = extractFromLists();
    if (listBased.length) return pickBest(listBased);

    return { question: selection || "", options: [] };
  }

  function pickBest(list) {
    return list.reduce((best, m) => (m.options.length > best.options.length ? m : best));
  }

  // ── Label / misc helpers ──────────────────────────────────────────

  function labelFor(input) {
    if (input.id) {
      const label = document.querySelector(`label[for="${CSS.escape(input.id)}"]`);
      if (label) return normalize(label.textContent);
    }
    const parentLabel = input.closest("label");
    if (parentLabel) return normalize(parentLabel.textContent);
    const sibling = input.nextElementSibling;
    if (sibling && sibling.tagName === "LABEL") return normalize(sibling.textContent);
    return normalize(input.value || "");
  }

  function groupId(input) {
    const form = input.closest("form, fieldset, .question, [role='radiogroup']");
    return form
      ? Array.prototype.indexOf.call(form.querySelectorAll("input"), input)
      : 0;
  }

  function isVisible(el) {
    return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  function normalize(text) {
    return text.replace(/\s+/g, " ").trim();
  }

  function clip(text) {
    return text.length > MAX_QUESTION_CHARS ? text.slice(0, MAX_QUESTION_CHARS) : text;
  }

  /** Backend Option.text allows max 2000 chars; clip long labels. */
  function clipOption(text) {
    return text.length > MAX_OPTION_CHARS ? text.slice(0, MAX_OPTION_CHARS - 1) + "…" : text;
  }

  /** Backend Option.id allows max 64 chars — the extractor may return labels. */
  function tidyOption(option) {
    return {
      id: option.text.length <= 64 ? option.text : `OPT_${hash(option.text)}`,
      text: clipOption(option.text),
    };
  }

  function hash(text) {
    let h = 0;
    for (let i = 0; i < text.length; i++) {
      h = (h * 31 + text.charCodeAt(i)) | 0;
    }
    return Math.abs(h).toString(36);
  }

  function letterFor(i) {
    const alphabet = "abcdefghijklmnopqrstuvwxyz";
    return i < 26 ? alphabet[i] : `o${i + 1}`;
  }

  /** Public entry: extracted MCQ with backend-safe ids and lengths. */
  function mcqForBackend() {
    const mcq = extractMcq();
    return { question: mcq.question, options: mcq.options.map(tidyOption) };
  }

  /** Public entry: all detected MCQs, tidied for the backend. */
  function mcqsForBackend() {
    return extractMcqs().map((mcq) => ({
      question: mcq.question,
      options: mcq.options.map(tidyOption),
      rect: plainRect(mcq.rect),
    }));
  }

  // Expose for overlay.js (same content-script world).
  window.__jevExtractMcq = extractMcq;
  window.__jevMcqForBackend = mcqForBackend;
  window.__jevExtractMcqs = mcqsForBackend;
})();
