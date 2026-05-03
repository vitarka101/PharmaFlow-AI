/* PharmaFlow AI — Prescription Advisor Chat JS */

let pendingFile = null;
let sessionTotalGross = 0;
let sessionTotalRisk = 0;
let sessionAnalyzed = 0;
let sessionFound = 0;

// Session memory: unique ID + last-5 message history for LLM context
const sessionId = (() => {
  const stored = sessionStorage.getItem("pf_session_id");
  if (stored) return stored;
  const id = (typeof crypto !== "undefined" && crypto.randomUUID)
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
  sessionStorage.setItem("pf_session_id", id);
  return id;
})();
let chatHistory = [];  // [{role, content}, ...] capped at 10

// ── Persist & restore session state across tab navigations ────────────────

function saveSessionState() {
  // Strip any in-flight typing indicators before saving so they don't restore broken
  const thread = document.getElementById("chat-thread");
  const clone = thread.cloneNode(true);
  clone.querySelectorAll('[id^="typing-"]').forEach(el => el.remove());
  sessionStorage.setItem("pf_thread_html", clone.innerHTML);
  sessionStorage.setItem("pf_sidebar_html", document.getElementById("session-results-list").innerHTML);
  sessionStorage.setItem("pf_bands_html", document.getElementById("session-bands").innerHTML);
  sessionStorage.setItem("pf_stats", JSON.stringify({
    analyzed: sessionAnalyzed, found: sessionFound,
    gross: sessionTotalGross, risk: sessionTotalRisk,
    statsVisible: document.getElementById("session-stats").style.display !== "none",
  }));
  sessionStorage.setItem("pf_history", JSON.stringify(chatHistory));
}

function restoreSessionState() {
  const thread = sessionStorage.getItem("pf_thread_html");
  if (!thread) return; // nothing to restore

  document.getElementById("chat-thread").innerHTML = thread;
  document.getElementById("session-results-list").innerHTML =
    sessionStorage.getItem("pf_sidebar_html") || "";
  document.getElementById("session-bands").innerHTML =
    sessionStorage.getItem("pf_bands_html") || "";

  const stats = JSON.parse(sessionStorage.getItem("pf_stats") || "{}");
  sessionAnalyzed    = stats.analyzed || 0;
  sessionFound       = stats.found    || 0;
  sessionTotalGross  = stats.gross    || 0;
  sessionTotalRisk   = stats.risk     || 0;
  if (stats.statsVisible) {
    document.getElementById("session-empty").style.display = "none";
    document.getElementById("session-stats").style.display = "block";
    set("stat-analyzed", sessionAnalyzed);
    set("stat-found",    sessionFound);
    set("stat-gross",    fmt$(sessionTotalGross));
    set("stat-risk",     fmt$(sessionTotalRisk));
  }

  chatHistory = JSON.parse(sessionStorage.getItem("pf_history") || "[]");

  // Scroll thread to bottom
  const t = document.getElementById("chat-thread");
  t.scrollTop = t.scrollHeight;
}

// Restore on load
restoreSessionState();

// Save whenever user navigates away (tab switch, link click, etc.)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") saveSessionState();
});
window.addEventListener("pagehide", saveSessionState);

// ── File handling ─────────────────────────────────────────────────────────

function handleFileSelect() {
  const input = document.getElementById("file-input");
  if (input.files && input.files[0]) setFile(input.files[0]);
}

function handleDrop(event) {
  event.preventDefault();
  document.getElementById("upload-zone").classList.remove("drag-over");
  const f = event.dataTransfer.files[0];
  if (f && f.name.toLowerCase().endsWith(".csv")) setFile(f);
  else appendSystemMsg("Only CSV files are supported for upload.");
}

function setFile(f) {
  pendingFile = f;
  document.getElementById("file-ready").textContent = `✓ ${f.name} ready`;
  document.getElementById("file-ready").style.display = "inline";
  document.getElementById("upload-label").style.display = "none";
  const cancel = document.getElementById("file-cancel");
  if (cancel) cancel.style.display = "inline";
}

function clearFile() {
  pendingFile = null;
  document.getElementById("file-ready").style.display = "none";
  document.getElementById("upload-label").style.display = "inline";
  document.getElementById("file-input").value = "";
  const cancel = document.getElementById("file-cancel");
  if (cancel) cancel.style.display = "none";
}

// ── Send message ──────────────────────────────────────────────────────────

async function sendMessage() {
  const input = document.getElementById("msg-input");
  const drugQuery = input.value.trim();
  const btn = document.getElementById("send-btn");

  if (!pendingFile && !drugQuery) {
    appendSystemMsg("Please upload a CSV or type drug names before sending.");
    return;
  }

  // Show user message
  if (pendingFile) appendUserMsg(`📎 Uploaded: ${pendingFile.name}`);
  else appendUserMsg(drugQuery);

  input.value = "";
  btn.disabled = true;
  btn.textContent = "Analyzing…";

  // Show typing indicator
  const typingId = appendTyping();

  try {
    const fd = new FormData();
    if (pendingFile) fd.append("file", pendingFile);
    else fd.append("drug_query", drugQuery);
    fd.append("session_id", sessionId);
    fd.append("history", JSON.stringify(chatHistory.slice(-5)));

    // For CSV uploads: fetch immediately but animate a processing delay before rendering
    const fetchPromise = fetch("/api/chat/analyze", { method: "POST", body: fd });

    let resp;
    if (pendingFile) {
      const steps = [
        "Analyzing claims…",
        "Running agent pipeline…",
        "Calculating risk-adjusted savings…",
        "Preparing results…",
      ];
      const stepEl = document.querySelector(`#${typingId} .msg-bubble`);
      let stepIndex = 0;
      if (stepEl) stepEl.innerHTML = steps[0];
      const stepInterval = setInterval(() => {
        stepIndex++;
        if (stepIndex < steps.length && stepEl) stepEl.innerHTML = steps[stepIndex];
      }, 3000);

      // Wait for both fetch AND 10s delay
      [resp] = await Promise.all([
        fetchPromise,
        new Promise(r => setTimeout(r, 10000)),
      ]);
      clearInterval(stepInterval);
    } else {
      resp = await fetchPromise;
    }

    removeTyping(typingId);

    if (!resp.ok) {
      const err = await resp.json();
      appendBotMsg(`<span style="color:var(--do-not-switch)">⚠ ${err.error || "Analysis failed."}</span>`);
    } else {
      const data = await resp.json();
      updateSessionStats(data);
      appendAnalysisResult(data);
      if (data.dashboard_updated) {
        appendBotMsg(`<p style="color:var(--recommend);font-weight:600">✓ Dashboard and Members pages updated — navigate there to see the new opportunities.</p>`);
      }
      // Update local history for LLM context
      const userContent = pendingFile ? `[CSV: ${pendingFile.name}]` : drugQuery;
      chatHistory.push({ role: "user", content: userContent });
      chatHistory.push({ role: "assistant", content: data.summary_text || "" });
      if (chatHistory.length > 10) chatHistory = chatHistory.slice(-10);
    }
    saveSessionState();

  } catch (e) {
    removeTyping(typingId);
    appendBotMsg(`<span style="color:var(--do-not-switch)">⚠ Error: ${e.message}</span>`);
  } finally {
    clearFile();
    btn.disabled = false;
    btn.textContent = "Send ▶";
  }
}

// ── Session stats sidebar ─────────────────────────────────────────────────

function updateSessionStats(data) {
  sessionAnalyzed += (data.analyzed || 0) + (data.no_alternative_count || 0);
  sessionFound += data.analyzed || 0;
  sessionTotalGross += data.total_gross_savings || 0;
  sessionTotalRisk += data.total_risk_adjusted_savings || 0;

  document.getElementById("session-empty").style.display = "none";
  document.getElementById("session-stats").style.display = "block";
  set("stat-analyzed", sessionAnalyzed);
  set("stat-found", sessionFound);
  set("stat-gross", fmt$(sessionTotalGross));
  set("stat-risk", fmt$(sessionTotalRisk));

  // Band summary pills
  const bc = data.band_counts || {};
  document.getElementById("session-bands").innerHTML = [
    bc["Recommend"] ? `<span class="band band-recommend">${bc["Recommend"]} Recommend</span>` : "",
    bc["Review"] ? `<span class="band band-review">${bc["Review"]} Review</span>` : "",
    bc["Do Not Switch"] ? `<span class="band band-donotswitch">${bc["Do Not Switch"]} Do Not Switch</span>` : "",
  ].join(" ");

  // Sidebar result cards
  const list = document.getElementById("session-results-list");
  const cards = (data.results || [])
    .filter(r => !r.skipped && !r.no_alternative)
    .map(r => {
      const drug = r.current_drug || r.drug_name || "—";
      const alt = r.candidate_alternative || r.alternative || "—";
      const band = r.recommendation_band || "";
      const gross = r.gross_savings ?? r.gross_savings_per_30_day ?? 0;
      const riskAdj = r.risk_adjusted_savings ?? 0;
      const bandCls = { "Recommend": "band-recommend", "Review": "band-review", "Do Not Switch": "band-donotswitch" }[band] || "";
      return `
        <div class="sidebar-result-card">
          <div class="src-drug" title="${drug}">${drug}</div>
          <div class="src-arrow">↓</div>
          <div class="src-alt" title="${alt}">${alt}</div>
          <div style="display:flex;justify-content:space-between;margin-top:6px;align-items:center">
            <span class="band ${bandCls}" style="font-size:10px">${band}</span>
            <span class="savings-pos" style="font-size:12px">${fmt$(gross)}</span>
          </div>
        </div>`;
    }).join("");
  list.innerHTML = cards || "";
}

// ── Chat message rendering ────────────────────────────────────────────────

function appendAnalysisResult(data) {
  // Summary text bubble
  appendBotMsg(`<p>${data.summary_text}</p>`);

  // Results table if we have real matches
  const valid = (data.results || []).filter(r => !r.skipped && !r.no_alternative);
  if (!valid.length) return;

  const tableRows = valid.map(r => {
    const drug = r.current_drug || r.drug_name || "—";
    const alt = r.candidate_alternative || r.alternative || "—";
    const gross = r.gross_savings ?? r.gross_savings_per_30_day ?? 0;
    const riskAdj = r.risk_adjusted_savings ?? 0;
    const band = r.recommendation_band || "";
    const te = r.te_code || r.mapping?.te_code || "—";
    const equiv = r.equivalence_type || "—";
    const bandCls = { "Recommend": "band-recommend", "Review": "band-review", "Do Not Switch": "band-donotswitch" }[band] || "";
    const equivCls = equiv === "GENERIC_EQUIVALENT" ? "equiv-generic" : "equiv-therapeutic";
    const equivLabel = equiv === "GENERIC_EQUIVALENT" ? "Generic Equiv." : "Therapeutic Alt.";
    return `
      <tr>
        <td style="max-width:150px;word-break:break-word" title="${drug}">${drug}</td>
        <td style="max-width:150px;word-break:break-word" title="${alt}">${alt}</td>
        <td><span class="equiv ${equivCls}" style="font-size:11px">${equivLabel}</span></td>
        <td><span class="savings-pos">${fmt$(gross)}</span></td>
        <td><span class="${riskAdj >= 0 ? 'savings-pos' : 'savings-neg'}">${fmt$(riskAdj)}</span></td>
        <td><span class="band ${bandCls}" style="font-size:11px">${band}</span></td>
      </tr>`;
  }).join("");

  appendBotMsg(`
    <div style="margin-top:8px">
      <table class="chat-result-table" style="width:100%;table-layout:fixed">
        <colgroup>
          <col style="width:22%"><col style="width:22%"><col style="width:16%">
          <col style="width:14%"><col style="width:14%"><col style="width:12%">
        </colgroup>
        <thead>
          <tr>
            <th>Current Drug</th><th>Generic Alternative</th><th>Equivalence</th>
            <th>Gross Savings</th><th>Risk-Adj. Savings</th><th>Band</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
    <p style="margin-top:8px;font-size:12px;color:var(--text-muted)">
      Savings shown are per fill cycle (based on uploaded quantity or 30-day default).
      TE code AB = FDA-approved therapeutic equivalent. Refer all switches to a pharmacist.
    </p>
  `);

  // No-alternative list
  const noAlt = (data.results || []).filter(r => r.no_alternative);
  if (noAlt.length) {
    appendBotMsg(`<p style="color:var(--text-muted);font-size:13px">ℹ No generic alternative found for: ${noAlt.map(r => `<strong>${r.drug_name}</strong>`).join(", ")}.</p>`);
  }
}

function appendUserMsg(text) {
  const thread = document.getElementById("chat-thread");
  thread.insertAdjacentHTML("beforeend", `
    <div class="msg msg-user">
      <div class="msg-bubble msg-bubble-user">${escHtml(text)}</div>
      <div class="msg-avatar">👤</div>
    </div>`);
  thread.scrollTop = thread.scrollHeight;
}

function appendBotMsg(html) {
  const thread = document.getElementById("chat-thread");
  thread.insertAdjacentHTML("beforeend", `
    <div class="msg msg-system">
      <div class="msg-avatar">🤖</div>
      <div class="msg-bubble">${html}</div>
    </div>`);
  thread.scrollTop = thread.scrollHeight;
}

function appendSystemMsg(text) {
  appendBotMsg(`<span style="color:var(--text-muted);font-size:13px">${escHtml(text)}</span>`);
}

let _typingCounter = 0;
function appendTyping() {
  const id = `typing-${++_typingCounter}`;
  const thread = document.getElementById("chat-thread");
  thread.insertAdjacentHTML("beforeend", `
    <div class="msg msg-system" id="${id}">
      <div class="msg-avatar">🤖</div>
      <div class="msg-bubble"><span class="typing-dots"><span></span><span></span><span></span></span></div>
    </div>`);
  thread.scrollTop = thread.scrollHeight;
  return id;
}

function removeTyping(id) {
  document.getElementById(id)?.remove();
}

function clearSession() {
  sessionAnalyzed = sessionFound = sessionTotalGross = sessionTotalRisk = 0;
  chatHistory = [];
  // Clear persisted state so navigating back shows a fresh session
  sessionStorage.removeItem("pf_thread_html");
  sessionStorage.removeItem("pf_sidebar_html");
  sessionStorage.removeItem("pf_bands_html");
  sessionStorage.removeItem("pf_stats");
  sessionStorage.removeItem("pf_history");
  sessionStorage.removeItem("pf_session_id");
  document.getElementById("session-empty").style.display = "block";
  document.getElementById("session-stats").style.display = "none";
  document.getElementById("session-results-list").innerHTML = "";
  document.getElementById("session-bands").innerHTML = "";
  document.getElementById("chat-thread").innerHTML = `
    <div class="msg msg-system">
      <div class="msg-avatar">🤖</div>
      <div class="msg-bubble">
        <strong>PharmaFlow Advisor</strong><br/>
        Session cleared. Upload a claims CSV or type drug names to start a new analysis.
      </div>
    </div>`;
  clearFile();
}

// ── LLM status badge ──────────────────────────────────────────────────────

fetch("/api/config").then(r => r.json()).then(c => {
  const el = document.getElementById("llm-status");
  if (!el) return;
  const active = c.use_llm?.toLowerCase() === "true" && c.model_name;
  el.textContent = active
    ? `✦ AI: ${c.model_name}`
    : "○ LLM off (deterministic mode)";
  el.style.color = active ? "var(--recommend)" : "var(--text-muted)";
}).catch(() => {});

// ── Utilities ─────────────────────────────────────────────────────────────

function set(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function fmt$(n) {
  if (n == null) return "—";
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
