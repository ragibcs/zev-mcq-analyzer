/**
 * Overlay renderer: injects a Shadow-DOM card into the page showing the
 * prediction, confidence, distribution bars and optional explanation.
 *
 * Lives in the content-script world; popup/worker drive it via messages.
 */

(() => {
  if (window.__jevOverlayInstalled) return;
  window.__jevOverlayInstalled = true;

  const HOST_ID = "jev-mcq-analyzer-overlay";
  const MAX_Z = 2147483600;

  let host = null;
  let root = null;
  let els = null;
  let dragState = null;
  let currentOptions = []; // [{ id, text }] as analyzed
  let anchorRect = null; // DOMRect of the analyzed MCQ, for card positioning

  function ensureHost() {
    if (host && document.documentElement.contains(host)) return;

    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = `all:initial; position:fixed; z-index:${MAX_Z};`;
    document.documentElement.appendChild(host);

    root = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = CSS;
    root.appendChild(style);

    const card = document.createElement("div");
    card.className = "card";
    card.innerHTML = `
      <div class="head">
        <span class="dot"></span>
        <span class="title">Jev Prediction</span>
        <span class="spacer"></span>
        <button class="btn-icon" data-act="close" title="Close">✕</button>
      </div>
      <div class="body">
        <div class="q"></div>
        <div class="verdict">
          <div class="verdict-main">
            <div class="vlabel">PREDICTION</div>
            <div class="vvalue">—</div>
          </div>
          <div class="verdict-conf">
            <div class="vlabel">CONFIDENCE</div>
            <div class="vconf">—%</div>
          </div>
        </div>
        <div class="bars"></div>
        <div class="explain hidden">
          <div class="vlabel">WHY</div>
          <div class="etext"></div>
        </div>
        <div class="foot">
          <button class="btn ghost" data-act="explain">Why?</button>
          <span class="status"></span>
        </div>
      </div>
      <div class="drag-handle"></div>
    `;
    root.appendChild(card);

    // ── MCQ picker panel (multiple MCQs on one page) ────────────────
    const picker = document.createElement("div");
    picker.className = "picker hidden";
    picker.innerHTML = `
      <div class="head">
        <span class="dot"></span>
        <span class="title">Detected MCQs</span>
        <span class="spacer"></span>
        <button class="btn-icon" data-act="picker-close" title="Close">✕</button>
      </div>
      <div class="plist"></div>
    `;
    root.appendChild(picker);
    picker
      .querySelector('[data-act="picker-close"]')
      .addEventListener("click", () => picker.classList.add("hidden"));

    els = {
      card,
      picker,
      plist: picker.querySelector(".plist"),
      q: card.querySelector(".q"),
      vvalue: card.querySelector(".vvalue"),
      vconf: card.querySelector(".vconf"),
      bars: card.querySelector(".bars"),
      explain: card.querySelector(".explain"),
      etext: card.querySelector(".etext"),
      explainBtn: card.querySelector('[data-act="explain"]'),
      status: card.querySelector(".status"),
    };

    card.querySelector('[data-act="close"]').addEventListener("click", hide);

    // Drag by the header.
    const head = card.querySelector(".head");
    head.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      const rect = card.getBoundingClientRect();
      dragState = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      head.setPointerCapture(e.pointerId);
    });
    head.addEventListener("pointermove", (e) => {
      if (!dragState) return;
      const w = card.offsetWidth, h = card.offsetHeight;
      const left = clamp(e.clientX - dragState.dx, 4, window.innerWidth - w - 4);
      const top = clamp(e.clientY - dragState.dy, 4, window.innerHeight - h - 4);
      card.style.left = `${left}px`;
      card.style.top = `${top}px`;
      card.style.right = "auto";
      card.style.bottom = "auto";
    });
    head.addEventListener("pointerup", () => (dragState = null));
    head.addEventListener("pointercancel", () => (dragState = null));

    els.explainBtn.addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "overlay-explain" }).catch(() => {});
    });
  }

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  /** Show the picker: payload { mcqs: [{ question, options, rect }] } */
  function showPicker(payload) {
    ensureHost();
    const mcqs = payload.mcqs || [];
    hideCard();
    els.plist.textContent = "";
    mcqs.forEach((mcq, i) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "pitem";
      item.innerHTML = `
        <span class="pnum"></span>
        <span class="pwrap">
          <span class="ptext"></span>
          <span class="pmeta"></span>
        </span>
      `;
      item.querySelector(".pnum").textContent = String(i + 1);
      const q = truncate(mcq.question || "(untitled question)", 90);
      item.querySelector(".ptext").textContent = q;
      item.querySelector(".ptext").title = mcq.question || "";
      item.querySelector(".pmeta").textContent = `${mcq.options.length} options`;
      item.addEventListener("click", () => {
        els.picker.classList.add("hidden");
        chrome.runtime.sendMessage({ type: "picker-selected", index: i });
        setStatus("Analyzing…");
        showCard();
      });
      els.plist.appendChild(item);
    });
    els.picker.classList.remove("hidden");
    // Place the picker near the FAB (bottom-right), clamped to the viewport.
    els.picker.style.left = `${Math.max(8, window.innerWidth - 356)}px`;
    els.picker.style.top = `${Math.max(8, window.innerHeight - 436)}px`;
    show();
  }

  /** Payload { question, options, result, anchorRect } */
  function showResult(payload) {
    ensureHost();
    currentOptions = payload.options || [];
    anchorRect = payload.anchorRect || null;
    els.picker.classList.add("hidden");

    const { result } = payload;
    els.q.textContent = truncate(payload.question || "", 160);
    els.q.title = payload.question || "";

    // Predicted option text (result.predicted_option is the option id we sent).
    const pred = (currentOptions.find(
      (o) => o.id === result.predicted_option
    ) || {}).text || result.predicted_option;
    els.vvalue.textContent = truncate(pred, 60);
    els.vvalue.title = pred;
    els.vconf.textContent = `${Math.round((result.confidence || 0) * 100)}%`;

    els.bars.textContent = "";
    const rows = [...(result.distribution || [])].sort(
      (a, b) => b.probability - a.probability
    );
    for (const row of rows) {
      const label = row.option_text || row.option_id;
      const isBest =
        row.option_id === result.predicted_option ||
        (!row.option_id && label === pred);
      const bar = document.createElement("div");
      bar.className = "bar-row" + (isBest ? " best" : "");
      bar.innerHTML = `
        <span class="bar-label"></span>
        <div class="bar-track"><div class="bar-fill"></div></div>
        <span class="bar-pct"></span>
      `;
      bar.querySelector(".bar-label").textContent = truncate(label, 34);
      bar.querySelector(".bar-label").title = label;
      bar.querySelector(".bar-fill").style.width = `${Math.round(row.probability * 100)}%`;
      bar.querySelector(".bar-pct").textContent = `${Math.round(row.probability * 100)}%`;
      els.bars.appendChild(bar);
    }

    els.explain.classList.add("hidden");
    els.etext.textContent = "";
    els.explainBtn.disabled = false;
    els.status.textContent = "";

    // Position near the analyzed MCQ, or bottom-right by default.
    positionNearSelection();
    show();
  }

  function positionNearSelection() {
    const rect = anchorRect || lastSelectionRect();
    const w = 320, h = 260; // estimates before layout
    let top, left;
    if (rect) {
      left = rect.right + 12;
      top = rect.top - 20;
      if (left + w > window.innerWidth - 8) left = rect.left - w - 12;
      if (top + h > window.innerHeight - 8) top = window.innerHeight - h - 8;
    } else {
      left = window.innerWidth - w - 16;
      top = window.innerHeight - h - 16;
    }
    left = clamp(left, 8, Math.max(8, window.innerWidth - w - 8));
    top = clamp(top, 8, Math.max(8, window.innerHeight - h - 8));
    els.card.style.left = `${left}px`;
    els.card.style.top = `${top}px`;
  }

  function lastSelectionRect() {
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

  function showExplanation(text) {
    ensureHost();
    els.etext.textContent = text;
    els.explain.classList.remove("hidden");
    els.explainBtn.disabled = false;
    els.status.textContent = "";
  }

  function setStatus(text, isError) {
    if (!els) return;
    els.status.textContent = text;
    els.status.classList.toggle("err", !!isError);
    if (!isError) els.explainBtn.disabled = false;
  }

  function showCard() {
    if (host) host.style.display = "block";
  }

  function hideCard() {
    if (host) host.style.display = "none";
  }

  function show() {
    if (host) host.style.display = "block";
  }

  function truncate(text, n) {
    return text.length > n ? text.slice(0, n - 1) + "…" : text;
  }

  // ── Messages from the service worker / popup ──────────────────────
  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "show-overlay-result") {
      showResult(message.payload);
      sendResponse({ ok: true });
    } else if (message.type === "show-mcq-picker") {
      showPicker(message);
      sendResponse({ ok: true });
    } else if (message.type === "hide-overlay") {
      hide();
      sendResponse({ ok: true });
    } else if (message.type === "overlay-status") {
      setStatus(message.text, message.isError);
      sendResponse({ ok: true });
    } else if (message.type === "overlay-explain-result") {
      showExplanation(message.text);
      sendResponse({ ok: true });
    }
    return true;
  });

  const CSS = `
    :host, * { box-sizing: border-box; }
    .card {
      all: initial;
      position: fixed;
      width: 320px;
      display: block;
      font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
      color: #e8eaf0;
      background: rgba(23, 26, 33, 0.97);
      border: 1px solid #2a3040;
      border-radius: 12px;
      box-shadow: 0 12px 40px rgba(0,0,0,.45);
      overflow: hidden;
      cursor: default;
      user-select: none;
    }
    .head {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 10px;
      background: #1f2430;
      border-bottom: 1px solid #2a3040;
      cursor: grab;
    }
    .head:active { cursor: grabbing; }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: #4f8cff; }
    .title { font-size: 12px; font-weight: 600; }
    .spacer { flex: 1; }
    .btn-icon {
      all: unset; cursor: pointer; color: #9aa3b2;
      font-size: 12px; padding: 2px 6px; border-radius: 6px;
    }
    .btn-icon:hover { color: #fff; background: #2a3040; }
    .body { padding: 10px 12px 12px; }
    .q {
      color: #9aa3b2; font-size: 11px; margin-bottom: 8px;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .verdict { display: flex; gap: 16px; margin-bottom: 10px; }
    .vlabel {
      font-size: 9px; letter-spacing: .08em; color: #9aa3b2;
      text-transform: uppercase; margin-bottom: 2px;
    }
    .vvalue { font-size: 16px; font-weight: 700; color: #3ecf8e; }
    .vconf { font-size: 16px; font-weight: 700; }
    .bars { margin-bottom: 8px; }
    .bar-row {
      display: grid; grid-template-columns: 110px 1fr 36px;
      align-items: center; gap: 6px; margin-bottom: 4px;
    }
    .bar-label {
      font-size: 11px; color: #9aa3b2;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .bar-track { height: 7px; background: #2a3040; border-radius: 4px; overflow: hidden; }
    .bar-fill { height: 100%; background: #4f8cff; border-radius: 4px; transition: width .3s; }
    .bar-row.best .bar-fill { background: #3ecf8e; }
    .bar-row.best .bar-label { color: #e8eaf0; font-weight: 600; }
    .foot { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
    .btn {
      all: unset; cursor: pointer; font-size: 11px; font-weight: 600;
      padding: 4px 10px; border-radius: 7px;
      background: #2a3040; color: #e8eaf0;
    }
    .btn:hover { background: #343b4d; }
    .btn:disabled { opacity: .45; cursor: not-allowed; }
    .status { font-size: 11px; color: #9aa3b2; }
    .status.err { color: #ff6b6b; }
    .explain { margin: 6px 0 8px; }
    .etext {
      font-size: 12px; color: #c6cbd6; white-space: pre-wrap;
      max-height: 140px; overflow-y: auto;
      background: #1f2430; border-radius: 8px; padding: 8px;
    }
    .picker {
      position: fixed;
      width: 340px;
      max-height: 420px;
      display: block;
      font: 13px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif;
      color: #e8eaf0;
      background: rgba(23, 26, 33, 0.97);
      border: 1px solid #2a3040;
      border-radius: 12px;
      box-shadow: 0 12px 40px rgba(0,0,0,.45);
      overflow: hidden;
      cursor: default;
      user-select: none;
    }
    .picker.hidden { display: none !important; }
    .plist { max-height: 360px; overflow-y: auto; padding: 6px; }
    .pitem {
      all: unset;
      display: grid;
      grid-template-columns: 22px 1fr;
      gap: 8px;
      align-items: start;
      width: 100%;
      box-sizing: border-box;
      padding: 8px;
      margin-bottom: 4px;
      border-radius: 8px;
      cursor: pointer;
      color: inherit;
      font: inherit;
    }
    .pitem:hover { background: #2a3040; }
    .pnum {
      display: inline-block;
      min-width: 18px;
      text-align: center;
      font-size: 11px;
      font-weight: 700;
      color: #4f8cff;
      background: #1f2430;
      border: 1px solid #2a3040;
      border-radius: 6px;
      padding: 2px 0;
    }
    .pwrap { display: block; min-width: 0; }
    .ptext {
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #e8eaf0;
      overflow: hidden;
      text-overflow: ellipsis;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }
    .pmeta {
      display: block;
      font-size: 10px;
      color: #9aa3b2;
      margin-top: 2px;
    }
    .hidden { display: none !important; }
  `;
})();
