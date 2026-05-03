/* PharmaFlow AI — Members History JS */

let allMembers = [];
let memberSortCol = "total_risk_adjusted_savings";
let memberSortDir = -1;

async function init() {
  const plan = sessionStorage.getItem("pf_plan") || "PLAN-GOLD-001";
  const members = await fetch(`/api/members?plan=${encodeURIComponent(plan)}`).then(r => r.json());
  allMembers = members;
  renderSummaryCards(members);
  renderMembersTable(members);
}

// ── Summary cards ─────────────────────────────────────────────────────────

function renderSummaryCards(members) {
  const total = members.length;
  const rec = members.filter(m => m.overall_band === "Recommend").length;
  const rev = members.filter(m => m.overall_band === "Review").length;
  const avgSavings = total
    ? members.reduce((s, m) => s + m.total_risk_adjusted_savings, 0) / total
    : 0;

  set("ms-total", total);
  set("ms-recommend", rec);
  set("ms-review", rev);
  set("ms-avg-savings", fmt$(avgSavings));
}

function set(id, val) { const el = document.getElementById(id); if (el) el.textContent = val; }
function fmt$(n) {
  if (n == null) return "—";
  return "$" + Number(n).toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

// ── Members table ─────────────────────────────────────────────────────────

function bandBadge(b) {
  const cls = { "Recommend": "band-recommend", "Review": "band-review", "Do Not Switch": "band-donotswitch" }[b] || "";
  return `<span class="band ${cls}">${b}</span>`;
}

function renderMembersTable(members) {
  const search = (document.getElementById("member-search")?.value || "").toLowerCase();
  let filtered = search
    ? members.filter(m => m.member_id.toLowerCase().includes(search))
    : members;

  filtered = [...filtered].sort((a, b) => memberSortDir * (b[memberSortCol] - a[memberSortCol]));

  document.getElementById("member-count").textContent = `${filtered.length} member${filtered.length === 1 ? "" : "s"}`;

  const tbody = document.getElementById("members-tbody");
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty">No members found.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(m => `
    <tr>
      <td style="font-family:monospace;font-weight:600">${m.member_id}</td>
      <td style="text-align:center">${m.claim_count}</td>
      <td style="text-align:center">${m.drug_count}</td>
      <td><span class="savings-pos">${fmt$(m.total_gross_savings)}</span></td>
      <td><span class="${m.total_risk_adjusted_savings >= 0 ? 'savings-pos' : 'savings-neg'}">${fmt$(m.total_risk_adjusted_savings)}</span></td>
      <td style="text-align:center;color:var(--recommend);font-weight:600">${m.recommend_count}</td>
      <td style="text-align:center;color:var(--review);font-weight:600">${m.review_count}</td>
      <td>${bandBadge(m.overall_band)}</td>
      <td>
        <button class="btn-view" onclick="showMemberDetail('${m.member_id}')">View →</button>
      </td>
    </tr>
  `).join("");
}

function filterMembers() { renderMembersTable(allMembers); }

function sortMembers(col) {
  if (memberSortCol === col) memberSortDir *= -1;
  else { memberSortCol = col; memberSortDir = -1; }
  renderMembersTable(allMembers);
}

// ── Member detail panel ───────────────────────────────────────────────────

async function showMemberDetail(memberId) {
  const data = await fetch(`/api/members/${encodeURIComponent(memberId)}`).then(r => r.json());
  const overlay = document.getElementById("member-modal-overlay");
  overlay.style.display = "flex";
  document.body.style.overflow = "hidden";

  document.getElementById("detail-member-title").textContent = `${memberId} — Claim Detail`;
  document.getElementById("detail-summary-inline").textContent =
    `${data.recommendations.length} claims · Gross ${fmt$(data.total_gross_savings)} · Risk-Adj ${fmt$(data.total_risk_adjusted_savings)}`;

  const tbody = document.getElementById("detail-tbody");

  function equivBadge(e) {
    const cls = { "GENERIC_EQUIVALENT": "equiv-generic", "THERAPEUTIC_ALTERNATIVE": "equiv-therapeutic" }[e] || "equiv-no-alt";
    const label = { "GENERIC_EQUIVALENT": "Generic Equiv.", "THERAPEUTIC_ALTERNATIVE": "Therapeutic Alt." }[e] || e;
    return `<span class="equiv ${cls}">${label}</span>`;
  }
  function riskBar(score) {
    const pct = Math.round(score * 100);
    const cls = score < 0.3 ? "risk-low" : score < 0.6 ? "risk-med" : "risk-high";
    return `<div class="risk-bar-wrap"><div class="risk-bar"><div class="risk-bar-fill ${cls}" style="width:${pct}%"></div></div><span class="risk-label">${pct}%</span></div>`;
  }

  tbody.innerHTML = data.recommendations.map((r, i) => {
    const detailId = `md-detail-${i}`;
    const codes = (r.reason_codes || []).map(c => `<span class="code-tag">${c}</span>`).join(" ");
    return `
      <tr class="main-row" data-i="d${i}">
        <td><button class="expand-btn" onclick="toggleMemberDetail(${i})">&#9654;</button></td>
        <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.current_drug}">${r.current_drug}</td>
        <td style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${r.candidate_alternative}">${r.candidate_alternative}</td>
        <td>${equivBadge(r.equivalence_type)}</td>
        <td><span class="savings-pos">${fmt$(r.gross_savings)}</span></td>
        <td><span class="${r.risk_adjusted_savings >= 0 ? 'savings-pos' : 'savings-neg'}">${fmt$(r.risk_adjusted_savings)}</span></td>
        <td>${riskBar(r.clinical_risk_score)}</td>
        <td>${bandBadge(r.recommendation_band)}</td>
      </tr>
      <tr class="detail-row" id="${detailId}">
        <td class="detail-cell" colspan="8">
          <div class="detail-panel">
            <div class="detail-grid">
              <div class="detail-section">
                <h4>Drug Mapping</h4>
                <div class="detail-kv"><span class="k">TE Code</span><span class="v">${r.te_code || "—"}</span></div>
                <div class="detail-kv"><span class="k">Confidence</span><span class="v">${pct(r.mapping?.mapping_confidence)}</span></div>
                <div class="detail-kv"><span class="k">Reason</span><span class="v" style="max-width:200px;text-align:right;font-size:11px">${r.mapping?.mapping_reason || "—"}</span></div>
              </div>
              <div class="detail-section">
                <h4>Cost Analysis</h4>
                <div class="detail-kv"><span class="k">Brand cost</span><span class="v">$${r.cost_analysis?.current_unit_cost?.toFixed(4)}/${r.cost_analysis?.pricing_unit}</span></div>
                <div class="detail-kv"><span class="k">Generic cost</span><span class="v">$${r.cost_analysis?.alternative_unit_cost?.toFixed(4)}/${r.cost_analysis?.pricing_unit}</span></div>
                <div class="detail-kv"><span class="k">Gross savings</span><span class="v savings-pos">${fmt$(r.gross_savings)}</span></div>
              </div>
              <div class="detail-section">
                <h4>Clinical Risk</h4>
                <div class="detail-kv"><span class="k">Failure prob.</span><span class="v">${pct(r.switch_failure_probability)}</span></div>
                <div class="detail-kv"><span class="k">Medical delta</span><span class="v">${fmt$(r.clinical_risk?.expected_medical_cost_delta)}</span></div>
                <div class="detail-kv"><span class="k">Risk-adj savings</span><span class="v">${fmt$(r.risk_adjusted_savings)}</span></div>
              </div>
            </div>
            <div class="detail-section"><h4>Reason Codes</h4><div class="codes">${codes || "—"}</div></div>
            <div class="detail-section" style="margin-top:12px"><h4>Explanation</h4>
              <div class="detail-explanation">${r.explanation}</div>
            </div>
          </div>
        </td>
      </tr>`;
  }).join("");
}

function toggleMemberDetail(i) {
  const row = document.getElementById(`md-detail-${i}`);
  const mainRow = document.querySelector(`tr.main-row[data-i="d${i}"]`);
  const btn = mainRow?.querySelector(".expand-btn");
  if (!row) return;
  const open = row.classList.toggle("open");
  if (btn) btn.innerHTML = open ? "&#9660;" : "&#9654;";
  if (mainRow) mainRow.classList.toggle("expanded", open);
}

function closeDetail() {
  document.getElementById("member-modal-overlay").style.display = "none";
  document.body.style.overflow = "";
}

function pct(v) { return v == null ? "—" : Math.round(v * 100) + "%"; }

document.addEventListener("DOMContentLoaded", init);
