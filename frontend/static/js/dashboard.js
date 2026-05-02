/* PharmaFlow AI — Dashboard JS */

const API = {
  dashboard: "/api/dashboard",
  recommendations: "/api/recommendations",
};

let allRecs = [];
let sortCol = "risk_adjusted_savings";
let sortDir = -1; // -1 = desc

// ── Fetch & render ────────────────────────────────────────────────────────

async function init() {
  try {
    const [summary, recs] = await Promise.all([
      fetch(API.dashboard).then(r => r.json()),
      fetch(API.recommendations).then(r => r.json()),
    ]);
    renderSummary(summary);
    allRecs = recs;
    applyFiltersAndRender();
  } catch (err) {
    document.getElementById("table-body").innerHTML =
      `<tr><td colspan="10" class="empty">Error loading data: ${err.message}</td></tr>`;
  }
}

// ── Summary cards ─────────────────────────────────────────────────────────

function fmt$(n) {
  if (n == null) return "—";
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function renderSummary(s) {
  set("card-gross",      fmt$(s.total_gross_savings));
  set("card-risk-adj",   fmt$(s.total_risk_adjusted_savings));
  set("card-total",      s.opportunity_count);
  set("card-recommend",  s.recommend_count);
  set("card-review",     s.review_count);
  set("card-blocked",    s.do_not_switch_count);
}

function set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Filters ───────────────────────────────────────────────────────────────

function applyFiltersAndRender() {
  const band     = document.getElementById("f-band").value;
  const equiv    = document.getElementById("f-equiv").value;
  const minSav   = parseFloat(document.getElementById("f-min-savings").value) || null;
  const maxClin  = parseFloat(document.getElementById("f-max-clinical").value) || null;

  let recs = allRecs.filter(r => {
    if (band   && r.recommendation_band !== band) return false;
    if (equiv  && r.equivalence_type !== equiv)   return false;
    if (minSav != null && r.risk_adjusted_savings < minSav) return false;
    if (maxClin != null && r.clinical_risk_score > maxClin) return false;
    return true;
  });

  // Sort
  recs.sort((a, b) => sortDir * (b[sortCol] - a[sortCol]));

  document.getElementById("result-count").textContent = `${recs.length} opportunit${recs.length === 1 ? "y" : "ies"}`;
  renderTable(recs);
}

function clearFilters() {
  ["f-band","f-equiv"].forEach(id => document.getElementById(id).value = "");
  ["f-min-savings","f-max-clinical"].forEach(id => document.getElementById(id).value = "");
  applyFiltersAndRender();
}

// ── Table ─────────────────────────────────────────────────────────────────

function bandBadge(b) {
  const cls = { "Recommend": "band-recommend", "Review": "band-review", "Do Not Switch": "band-donotswitch" }[b] || "";
  return `<span class="band ${cls}">${b}</span>`;
}

function equivBadge(e) {
  const cls = {
    "GENERIC_EQUIVALENT": "equiv-generic",
    "THERAPEUTIC_ALTERNATIVE": "equiv-therapeutic",
    "NO_ALTERNATIVE": "equiv-no-alt",
  }[e] || "";
  const label = { "GENERIC_EQUIVALENT": "Generic Equiv.", "THERAPEUTIC_ALTERNATIVE": "Therapeutic Alt.", "NO_ALTERNATIVE": "No Alt." }[e] || e;
  return `<span class="equiv ${cls}">${label}</span>`;
}

function savingsCell(val) {
  const cls = val >= 0 ? "savings-pos" : "savings-neg";
  const sign = val >= 0 ? "" : "";
  return `<span class="${cls}">${fmt$(val)}</span>`;
}

function riskBar(score) {
  const pct = Math.round(score * 100);
  const cls = score < 0.3 ? "risk-low" : score < 0.6 ? "risk-med" : "risk-high";
  return `<div class="risk-bar-wrap">
    <div class="risk-bar"><div class="risk-bar-fill ${cls}" style="width:${pct}%"></div></div>
    <span class="risk-label">${pct}%</span>
  </div>`;
}

function renderTable(recs) {
  const tbody = document.getElementById("table-body");
  if (recs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty">No opportunities match the current filters.</td></tr>`;
    return;
  }

  const rows = recs.map((r, i) => {
    const detailId = `detail-${i}`;
    const mainRow = `
      <tr class="main-row" data-i="${i}">
        <td><button class="expand-btn" onclick="toggleDetail(${i})">&#9654;</button></td>
        <td style="font-family:monospace;font-size:12px">${r.member_id}</td>
        <td><div style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.current_drug}">${r.current_drug}</div></td>
        <td><div style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.candidate_alternative}">${r.candidate_alternative}</div></td>
        <td>${equivBadge(r.equivalence_type)}</td>
        <td>${savingsCell(r.gross_savings)}</td>
        <td>${savingsCell(r.risk_adjusted_savings)}</td>
        <td>${riskBar(r.clinical_risk_score)}</td>
        <td>${riskBar(r.access_risk_score)}</td>
        <td>${bandBadge(r.recommendation_band)}</td>
      </tr>`;

    const codes = (r.reason_codes || []).map(c => `<span class="code-tag">${c}</span>`).join("");
    const detailRow = `
      <tr class="detail-row" id="${detailId}">
        <td class="detail-cell" colspan="10">
          <div class="detail-panel">
            <div class="detail-grid">
              <div class="detail-section">
                <h4>Drug Mapping (Librarian)</h4>
                <div class="detail-kv"><span class="k">Equivalence type</span><span class="v">${r.equivalence_type}</span></div>
                <div class="detail-kv"><span class="k">TE code</span><span class="v">${r.te_code || "—"}</span></div>
                <div class="detail-kv"><span class="k">Mapping confidence</span><span class="v">${pct(r.mapping?.mapping_confidence)}</span></div>
                <div class="detail-kv"><span class="k">Dosage form/route</span><span class="v">${r.mapping?.dosage_form_route || "—"}</span></div>
                <div class="detail-kv"><span class="k">Strength</span><span class="v">${r.mapping?.strength || "—"}</span></div>
              </div>
              <div class="detail-section">
                <h4>Cost Analysis (Auditor)</h4>
                <div class="detail-kv"><span class="k">Brand unit cost</span><span class="v">$${r.cost_analysis?.current_unit_cost?.toFixed(4)} / ${r.cost_analysis?.pricing_unit}</span></div>
                <div class="detail-kv"><span class="k">Generic unit cost</span><span class="v">$${r.cost_analysis?.alternative_unit_cost?.toFixed(4)} / ${r.cost_analysis?.pricing_unit}</span></div>
                <div class="detail-kv"><span class="k">Quantity (normalized)</span><span class="v">${r.cost_analysis?.normalized_quantity?.toFixed(0)} units</span></div>
                <div class="detail-kv"><span class="k">Gross savings</span><span class="v">${savingsCell(r.gross_savings)}</span></div>
                <div class="detail-kv"><span class="k">PBM spread estimate</span><span class="v">${fmt$(r.cost_analysis?.spread_estimate)}</span></div>
              </div>
              <div class="detail-section">
                <h4>Clinical Risk (Clinician)</h4>
                <div class="detail-kv"><span class="k">Clinical risk score</span><span class="v">${pct(r.clinical_risk_score)}</span></div>
                <div class="detail-kv"><span class="k">Switch failure prob.</span><span class="v">${pct(r.switch_failure_probability)}</span></div>
                <div class="detail-kv"><span class="k">Expected medical delta</span><span class="v">${fmt$(r.clinical_risk?.expected_medical_cost_delta)}</span></div>
                <div class="detail-kv"><span class="k">Risk-adj. savings</span><span class="v">${savingsCell(r.risk_adjusted_savings)}</span></div>
                <div class="detail-kv"><span class="k">95% CI</span><span class="v">${fmt$(r.credible_interval_low)} – ${fmt$(r.credible_interval_high)}</span></div>
              </div>
              <div class="detail-section">
                <h4>Access & Adherence (Social Navigator)</h4>
                <div class="detail-kv"><span class="k">Pharmacy access score</span><span class="v">${pct(r.access_risk?.pharmacy_access_score)}</span></div>
                <div class="detail-kv"><span class="k">Adherence risk</span><span class="v">${pct(r.access_risk?.adherence_risk_score)}</span></div>
                <div class="detail-kv"><span class="k">Preferred pharmacy</span><span class="v">${r.access_risk?.preferred_pharmacy_available ? "Yes" : "No"}</span></div>
                <div class="detail-kv"><span class="k">Access override</span><span class="v">${r.access_risk?.access_override ? "⚠ Yes" : "No"}</span></div>
              </div>
            </div>
            <div class="detail-section" style="margin-bottom:12px">
              <h4>Reason Codes</h4>
              <div class="codes">${codes || "—"}</div>
            </div>
            <div class="detail-section">
              <h4>Payer/Pharmacist Explanation</h4>
              <div class="detail-explanation">${r.explanation}</div>
            </div>
            <div style="margin-top:12px">
              <button class="btn-download" onclick="downloadPackage('${r.recommendation_id}', this)">
                &#128196; Download Switch Package (4 PDFs)
              </button>
            </div>
          </div>
        </td>
      </tr>`;

    return mainRow + detailRow;
  }).join("");

  tbody.innerHTML = rows;
}

function pct(v) {
  if (v == null) return "—";
  return Math.round(v * 100) + "%";
}

function toggleDetail(i) {
  const detailRow = document.getElementById(`detail-${i}`);
  const mainRow = document.querySelector(`tr.main-row[data-i="${i}"]`);
  const btn = mainRow?.querySelector(".expand-btn");
  if (!detailRow) return;
  const isOpen = detailRow.classList.contains("open");
  detailRow.classList.toggle("open", !isOpen);
  if (btn) btn.innerHTML = isOpen ? "&#9654;" : "&#9660;";
  if (mainRow) mainRow.classList.toggle("expanded", !isOpen);
}

// ── Sort ──────────────────────────────────────────────────────────────────

function setSort(col) {
  if (sortCol === col) { sortDir *= -1; }
  else { sortCol = col; sortDir = -1; }
  applyFiltersAndRender();
}

// ── Document download ─────────────────────────────────────────────────────

async function downloadPackage(recId, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Generating…";
  try {
    const resp = await fetch(`/api/documents/${encodeURIComponent(recId)}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      alert(`Download failed: ${err.detail || resp.statusText}`);
      return;
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `switch_package_${recId}.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(`Download error: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", init);
