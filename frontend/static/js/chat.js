/* PharmaFlow AI — Prescription Advisor Chat JS */

let pendingFile = null;
let sessionTotalGross = 0;
let sessionTotalRisk = 0;
let sessionAnalyzed = 0;
let sessionFound = 0;

// Session memory: unique ID + last-5 message history for LLM context
const sessionId = (typeof crypto !== "undefined" && crypto.randomUUID)
  ? crypto.randomUUID()
  : Math.random().toString(36).slice(2);
let chatHistory = [];  // [{role, content}, ...] capped at 5

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
}

function clearFile() {
  pendingFile = null;
  document.getElementById("file-ready").style.display = "none";
  document.getElementById("upload-label").style.display = "inline";
  document.getElementById("file-input").value = "";
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

    const resp = await fetch("/api/chat/analyze", { method: "POST", body: fd });
    removeTyping(typingId);

    if (!resp.ok) {
      const err = await resp.json();
      appendBotMsg(`<span style="color:var(--do-not-switch)">⚠ ${err.error || "Analysis failed."}</span>`);
      return;
    }

    const data = await resp.json();
    updateSessionStats(data);
    appendAnalysisResult(data);
    // Update local history for LLM context
    const userContent = pendingFile ? `[CSV: ${pendingFile.name}]` : drugQuery;
    chatHistory.push({ role: "user", content: userContent });
    chatHistory.push({ role: "assistant", content: data.summary_text || "" });
    if (chatHistory.length > 10) chatHistory = chatHistory.slice(-10);
    clearFile();

  } catch (e) {
    removeTyping(typingId);
    appendBotMsg(`<span style="color:var(--do-not-switch)">⚠ Error: ${e.message}</span>`);
  } finally {
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
        <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${drug}">${drug}</td>
        <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${alt}">${alt}</td>
        <td><span class="equiv ${equivCls}" style="font-size:11px">${equivLabel}</span></td>
        <td style="font-size:11px;color:var(--text-muted)">${te}</td>
        <td><span class="savings-pos">${fmt$(gross)}</span></td>
        <td><span class="${riskAdj >= 0 ? 'savings-pos' : 'savings-neg'}">${fmt$(riskAdj)}</span></td>
        <td><span class="band ${bandCls}" style="font-size:11px">${band}</span></td>
      </tr>`;
  }).join("");

  appendBotMsg(`
    <div style="overflow-x:auto;margin-top:8px">
      <table class="chat-result-table">
        <thead>
          <tr>
            <th>Current Drug</th><th>Generic Alternative</th><th>Equivalence</th>
            <th>TE Code</th><th>Gross Savings</th><th>Risk-Adj. Savings</th><th>Band</th>
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

// ── Utilities ─────────────────────────────────────────────────────────────

function set(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function fmt$(n) {
  if (n == null) return "—";
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}
function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
