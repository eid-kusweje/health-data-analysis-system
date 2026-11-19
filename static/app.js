"use strict";
/* Malawi Health & Disease Analytics — frontend.
   Charts are plain SVG generated in the browser (no external libraries),
   which keeps the dashboard fast on low-bandwidth connections. All chart
   colours come from the approved palette only. */
const PALETTE = ["#5878E9", "#7FC29B", "#65524D", "#B5EF8A", "#D7F171"];
const C_BLUE = PALETTE[0], C_TEAL = PALETTE[1], C_TAUPE = PALETTE[2];
const state = { user: null, datasets: [], datasetId: null, overview: null,
                overviewFor: null, quality: null, patterns: null,
                previewPage: 1, filtersBuiltFor: null };

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = v => String(v ?? "").replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = v => v === null || v === undefined ? "—" :
  new Intl.NumberFormat("en-GB").format(Math.round(Number(v)));
const fmt1 = v => v === null || v === undefined ? "—" : Number(v).toFixed(1);

function toast(msg, ok = false) {
  const t = $("#toast"); t.textContent = msg;
  t.className = "toast" + (ok ? " ok" : "");
  setTimeout(() => t.classList.add("hidden"), 4200);
}
/* --- auth token ---------------------------------------------------------
   The page authenticates with a Bearer token (returned by /api/auth/login)
   sent as an Authorization header on every request. It is kept in memory
   and, when the browser allows it, in localStorage. This matters because
   session cookies alone fail when the dashboard is embedded in a
   cross-site iframe (hosted live previews): the browser blocks the
   third-party cookie, login looks successful, and the next API call
   bounces the user back to the login page. The cookie is kept server-side
   as a fallback for normal top-level browsing. */
const TOKEN_KEY = "mha_api_token";
let memoryToken = null;
function getToken() {
  if (memoryToken) return memoryToken;
  try { memoryToken = localStorage.getItem(TOKEN_KEY); } catch (e) { /* storage blocked: memory only */ }
  return memoryToken;
}
function setToken(token) {
  memoryToken = token || null;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch (e) { /* storage blocked: memory copy still works for this page */ }
}
function authHeaders(extra = {}) {
  const t = getToken();
  return { ...extra, ...(t ? { Authorization: `Bearer ${t}` } : {}) };
}
function sessionExpired() {
  setToken(null); state.user = null;
  showLogin("Your session has expired — please sign in again.");
}

async function api(url, options = {}) {
  const { headers: optHeaders, ...rest } = options;
  const res = await fetch(url, {
    credentials: "same-origin", ...rest,
    headers: authHeaders({ "Content-Type": "application/json", ...(optHeaders || {}) }),
  });
  const isAuthCall = url.includes("/api/me") || url.includes("/api/auth/login");
  if (res.status === 401 && !isAuthCall) {
    sessionExpired();
    throw new Error("Session expired — please sign in again.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/* Downloads go through fetch (so the Authorization header is sent) and are
   saved from a Blob - plain <a href="/api/..."> links would depend on the
   session cookie, which embedded previews may block. */
async function downloadFile(url) {
  try {
    const res = await fetch(url, { headers: authHeaders(), credentials: "same-origin" });
    if (res.status === 401) { sessionExpired(); return; }
    if (!res.ok) {
      let msg = `Download failed (${res.status})`;
      try { msg = (await res.json()).error || msg; } catch (e) { /* not JSON */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    const match = /filename="?([^"]+)"?/.exec(res.headers.get("Content-Disposition") || "");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = match ? match[1] : "download";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  } catch (e) { toast(e.message); }
}
const loading = el => { el.innerHTML = `<div class="card loading">Loading analysis…</div>`; };
const noDataset = el => { el.innerHTML = `<div class="card empty-state">
  <h2>No dataset selected</h2><p>Choose a dataset in the top bar, or go to
  <strong>Datasets</strong> to upload a de-identified CSV/Excel file. The demo
  dataset is selected automatically when available.</p>
  <button class="btn" onclick="switchView('datasets')">Go to Datasets</button></div>`; };

/* ============================ SVG charts ============================ */
function axisMax(v) { if (v <= 0) return 1; const p = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / p * 2) / 2 * p; }

function lineChart(data, h = 250) {
  if (!data.length) return `<p class="muted">No dated records to chart.</p>`;
  const w = 720, pad = { l: 56, r: 14, t: 16, b: 40 };
  const max = axisMax(Math.max(...data.map(d => d.value)));
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const X = i => pad.l + (data.length === 1 ? iw / 2 : i * iw / (data.length - 1));
  const Y = v => pad.t + ih - (v / max) * ih;
  let grid = "", labels = "";
  for (let g = 0; g <= 4; g++) { const v = max * g / 4, y = Y(v);
    grid += `<line x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}" stroke="rgba(101,82,77,.14)"/>
             <text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="${C_TAUPE}">${fmt(v)}</text>`; }
  const step = Math.max(1, Math.ceil(data.length / 10));
  data.forEach((d, i) => { if (i % step === 0 || i === data.length - 1)
    labels += `<text x="${X(i)}" y="${h - 16}" text-anchor="middle" font-size="11" fill="${C_TAUPE}">${esc(d.label)}</text>`; });
  const pts = data.map((d, i) => `${X(i)},${Y(d.value)}`).join(" ");
  const area = `${pad.l},${Y(0)} ${pts} ${X(data.length - 1)},${Y(0)}`;
  const dots = data.map((d, i) => `<circle cx="${X(i)}" cy="${Y(d.value)}" r="3.2" fill="${C_TEAL}"><title>${esc(d.label)}: ${fmt(d.value)}</title></circle>`).join("");
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Line chart">${grid}
    <polygon points="${area}" fill="rgba(88,120,233,.12)"/>
    <polyline points="${pts}" fill="none" stroke="${C_BLUE}" stroke-width="2.6"/>${dots}${labels}</svg>`;
}

function barChart(data, h = 250, paletteBars = false) {
  if (!data.length) return `<p class="muted">No data to chart.</p>`;
  const w = 720, pad = { l: 52, r: 12, t: 20, b: 56 };
  const max = axisMax(Math.max(...data.map(d => d.value)));
  const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;
  const bw = iw / data.length;
  let s = "";
  for (let g = 0; g <= 4; g++) { const v = max * g / 4, y = pad.t + ih - (v / max) * ih;
    s += `<line x1="${pad.l}" y1="${y}" x2="${w - pad.r}" y2="${y}" stroke="rgba(101,82,77,.14)"/>
          <text x="${pad.l - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="${C_TAUPE}">${fmt(v)}</text>`; }
  const peak = Math.max(...data.map(d => d.value));
  data.forEach((d, i) => {
    const bh = (d.value / max) * ih, x = pad.l + i * bw + bw * 0.18, y = pad.t + ih - bh;
    const fill = paletteBars ? PALETTE[i % PALETTE.length] : (d.value === peak ? C_BLUE : C_TEAL);
    s += `<rect x="${x}" y="${y}" width="${bw * 0.64}" height="${Math.max(bh, 1)}" rx="4" fill="${fill}"><title>${esc(d.label)}: ${fmt(d.value)}</title></rect>
          <text x="${x + bw * 0.32}" y="${y - 5}" text-anchor="middle" font-size="10.5" font-weight="700" fill="${C_TAUPE}">${fmt(d.value)}</text>
          <text x="${x + bw * 0.32}" y="${h - 30}" text-anchor="end" font-size="11" fill="${C_TAUPE}" transform="rotate(-32 ${x + bw * 0.32} ${h - 30})">${esc(d.label)}</text>`;
  });
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Bar chart">${s}</svg>`;
}

function hBarChart(data) {
  if (!data.length) return `<p class="muted">No data to chart.</p>`;
  const rowH = 30, w = 720, padL = 128, padR = 70, h = data.length * rowH + 18;
  const max = Math.max(...data.map(d => d.value), 1);
  let s = "";
  data.forEach((d, i) => {
    const y = 8 + i * rowH, bw = (d.value / max) * (w - padL - padR);
    s += `<text x="${padL - 10}" y="${y + 15}" text-anchor="end" font-size="12" fill="${C_TAUPE}">${esc(d.label)}</text>
          <rect x="${padL}" y="${y}" width="${Math.max(bw, 2)}" height="18" rx="5" fill="${i === 0 ? C_BLUE : C_TEAL}"><title>${esc(d.label)}: ${fmt(d.value)}</title></rect>
          <text x="${padL + bw + 8}" y="${y + 14}" font-size="12" font-weight="700" fill="${C_TAUPE}">${fmt(d.value)}</text>`;
  });
  return `<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Horizontal bar chart">${s}</svg>`;
}

function donutChart(data, size = 220) {
  const total = data.reduce((a, d) => a + d.value, 0);
  if (!data.length || total <= 0) return `<p class="muted">No data to chart.</p>`;
  const r = 78, c = 2 * Math.PI * r; let offset = 0, segs = "", legend = "";
  data.forEach((d, i) => {
    const frac = d.value / total, len = frac * c, col = PALETTE[i % PALETTE.length];
    segs += `<circle cx="110" cy="110" r="${r}" fill="none" stroke="${col}" stroke-width="34"
      stroke-dasharray="${Math.max(len - 2, 0)} ${c - len + 2}" stroke-dashoffset="${-offset}"
      transform="rotate(-90 110 110)"><title>${esc(d.label)}: ${fmt(d.value)} (${(frac * 100).toFixed(1)}%)</title></circle>`;
    offset += len;
    legend += `<span><i style="background:${col}"></i>${esc(d.label)} · ${(frac * 100).toFixed(1)}%</span>`;
  });
  return `<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap">
    <svg viewBox="0 0 220 220" style="width:${size}px;max-width:100%" role="img" aria-label="Donut chart">${segs}
      <text x="110" y="104" text-anchor="middle" font-size="21" font-weight="700" fill="${C_TAUPE}">${fmt(total)}</text>
      <text x="110" y="126" text-anchor="middle" font-size="12" fill="${C_TAUPE}">total cases</text></svg>
    <div class="legend" style="flex-direction:column;align-items:flex-start;gap:7px;margin:0">${legend}</div></div>`;
}

function scoreDonut(score) {
  const r = 62, c = 2 * Math.PI * r, filled = c * Math.min(Math.max(score, 0), 100) / 100;
  const col = score >= 85 ? C_TEAL : score >= 70 ? C_BLUE : C_TAUPE;
  return `<svg viewBox="0 0 170 170" style="width:170px;max-width:100%" role="img" aria-label="Data quality score ${score}">
    <circle cx="85" cy="85" r="${r}" fill="none" stroke="rgba(101,82,77,.14)" stroke-width="20"/>
    <circle cx="85" cy="85" r="${r}" fill="none" stroke="${col}" stroke-width="20"
      stroke-dasharray="${filled} ${c - filled}" transform="rotate(-90 85 85)" stroke-linecap="round"/>
    <text x="85" y="84" text-anchor="middle" font-size="30" font-weight="700" fill="${C_TAUPE}">${fmt1(score)}</text>
    <text x="85" y="106" text-anchor="middle" font-size="12" fill="${C_TAUPE}">/ 100</text></svg>`;
}

function ratingPill(rating) {
  const cls = rating === "Needs attention" ? "pill solid" :
              rating === "Fair" ? "pill lime" : "pill";
  return `<span class="${cls}">${esc(rating)}</span>`;
}
function completenessPill(pct) {
  return `<span class="pill ${pct >= 95 ? "" : pct >= 90 ? "blue" : pct >= 80 ? "lime" : "solid"}">${fmt1(pct)}%</span>`;
}
function dimensionRows(dims) {
  const fills = ["", "teal", "green", "lime", "taupe"];
  return Object.entries(dims).map(([k, v], i) => `
    <div class="dim-row"><span style="text-transform:capitalize"><strong>${esc(k)}</strong></span>
      <div class="bar-track"><div class="bar-fill ${fills[i % fills.length]}" style="width:${v === null ? 0 : v}%"></div></div>
      <span>${v === null ? "N/A" : fmt1(v) + "%"}</span></div>`).join("");
}
function insightsBox(list) {
  if (!list.length) return "";
  return `<div class="card"><h2>Key observations</h2><div class="insight-box">
    <strong>Read disease patterns together with data quality:</strong>
    <ul>${list.map(t => `<li>${esc(t)}</li>`).join("")}</ul></div></div>`;
}
function districtTable(rows) {
  if (!rows.length) return `<p class="muted">No district data.</p>`;
  return `<div class="table-wrap"><table class="data">
    <tr><th>District</th><th>Region</th><th class="num">Cases</th><th>Top disease</th>
    <th class="num">Records</th><th class="num">Record completeness</th></tr>
    ${rows.map(r => `<tr><td><strong>${esc(r.district)}</strong></td><td>${esc(r.region)}</td>
      <td class="num">${fmt(r.cases)}</td><td>${esc(r.top_disease || "—")}</td>
      <td class="num">${fmt(r.records)}</td><td class="num">${completenessPill(r.completeness_pct)}</td></tr>`).join("")}
    </table></div>
    <p class="small muted">A district can rank high on cases <em>and</em> low on completeness —
    that combination needs data follow-up before the burden ranking is trusted.</p>`;
}
const icon = {
  cases: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M3 12h4l2.5-6 4 12L16 12h5"/></svg>`,
  rows: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M4 6h16M4 12h16M4 18h16"/></svg>`,
  shield: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 3l7 3v6c0 4.4-3 7.4-7 9-4-1.6-7-4.6-7-9V6l7-3z"/><path d="M9 12l2 2 4-4.5"/></svg>`,
  pin: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z"/><circle cx="12" cy="10" r="2.6"/></svg>`
};
const kpiCard = (label, value, note, chip, ic) => `
  <div class="card kpi-card"><div class="kpi-top"><span class="kpi-label">${esc(label)}</span>
  <span class="icon-chip ${chip}">${ic}</span></div>
  <div class="kpi-value">${value}</div><div class="kpi-note">${note}</div></div>`;

/* ============================ views ============================ */
async function getOverview(force = false) {
  if (!force && state.overview && state.overviewFor === state.datasetId) return state.overview;
  state.overview = await api(`/api/datasets/${state.datasetId}/overview`);
  state.overviewFor = state.datasetId;
  const q = state.overview.quality;
  $("#topScorePill").textContent = `Data quality ${fmt1(q.overall_score)} · ${q.rating}`;
  return state.overview;
}

async function renderOverview() {
  const el = $("#overviewContent");
  if (!state.datasetId) return noDataset(el);
  loading(el);
  try {
    const { quality: q, patterns: p } = await getOverview();
    const ds = state.datasets.find(d => d.id === state.datasetId);
    el.innerHTML = `
    ${ds?.is_demo ? `<div class="notice" style="margin-bottom:16px"><strong>Demo dataset:</strong>
      synthetic data with deliberately planted quality problems (missing values concentrated in
      Mangochi, duplicates, late reports, one malaria spike). Use it to verify that every check works.</div>` : ""}
    <div class="grid kpis" style="margin-bottom:16px">
      ${kpiCard("Total reported cases", fmt(p.kpis.total_cases),
        `${esc(p.kpis.period_start || "—")} to ${esc(p.kpis.period_end || "—")}`, "chip-blue", icon.cases)}
      ${kpiCard("Records analysed", fmt(p.kpis.records),
        `<strong>${fmt(p.kpis.diseases)}</strong> diseases tracked`, "chip-teal", icon.rows)}
      ${kpiCard("Data-quality score", fmt1(q.overall_score) + " / 100",
        ratingPill(q.rating), "chip-green", icon.shield)}
      ${kpiCard("Districts covered", fmt(p.kpis.districts),
        `of <strong>28</strong> Malawi districts${p.kpis.unrecognised_district_values ? ` · <strong>${p.kpis.unrecognised_district_values}</strong> unrecognised district value(s)` : ""}`, "chip-lime", icon.pin)}
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Cases over time</h2><p class="card-sub">Monthly reported cases (all diseases &amp; districts)</p>
        <div class="chart-box">${lineChart(p.trend_monthly)}</div></div>
      <div class="card"><h2>Cases by disease</h2><p class="card-sub">Share of total reported cases</p>
        ${donutChart(p.by_disease)}</div>
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Data-quality dimensions</h2>
        <p class="card-sub">Completeness = % of records with all key fields (${esc((q.key_fields || []).join(", "))})</p>
        ${dimensionRows(q.dimensions)}
        <p class="small muted">${esc(q.timeliness.note)}</p>
        <button class="btn secondary small-btn" onclick="switchView('quality')">Open data-quality analysis</button></div>
      <div class="card"><h2>Top districts by reported cases</h2><p class="card-sub">Highest reported burden first</p>
        <div class="chart-box">${hBarChart(p.by_district.slice(0, 8))}</div></div>
    </div>
    <div class="grid two">
      <div class="card"><h2>District situation — burden with data quality</h2>
        <p class="card-sub">The centrepiece of this system: never rank districts without their completeness.</p>
        ${districtTable(p.district_table.slice(0, 10))}</div>
      <div>${insightsBox(p.insights)}
        <div class="card" style="margin-top:16px"><h2>Seasonal pattern</h2>
        <p class="card-sub">Total cases by calendar month — watch the rainy-season (Nov–Apr) rise.</p>
        <div class="chart-box">${barChart(p.seasonality, 230)}</div></div></div>
    </div>`;
  } catch (e) { el.innerHTML = `<div class="card"><div class="error-box">${esc(e.message)}</div></div>`; }
}

async function renderDatasets() {
  const canUpload = ["admin", "analyst"].includes(state.user.role);
  $("#uploadCard").style.opacity = canUpload ? 1 : .65;
  if (!canUpload) $("#uploadForm").innerHTML =
    `<div class="notice">Your role (<strong>viewer</strong>) is read-only, so uploads are disabled.
     Sign in as <strong>analyst@demo.mw</strong> to test uploading.</div>`;
  const el = $("#datasetList");
  if (!state.datasets.length) { el.innerHTML = `<p class="muted">No datasets yet.</p>`; }
  else el.innerHTML = `<div class="table-wrap"><table class="data">
    <tr><th>Dataset</th><th class="num">Rows</th><th class="num">Columns</th><th>Uploaded by</th><th>Uploaded</th><th>Actions</th></tr>
    ${state.datasets.map(d => `<tr>
      <td><strong>${esc(d.name)}</strong> ${d.is_demo ? `<span class="pill lime">Demo</span>` : ""}
        <div class="small muted">${esc(d.original_filename)}${d.description ? " · " + esc(d.description) : ""}</div></td>
      <td class="num">${fmt(d.row_count)}</td><td class="num">${d.col_count}</td>
      <td>${esc(d.owner_name || "—")}</td><td>${esc((d.uploaded_at || "").slice(0, 10))}</td>
      <td style="white-space:nowrap">
        <button class="btn ${d.id === state.datasetId ? "lime" : "secondary"} small-btn" data-select="${d.id}">
          ${d.id === state.datasetId ? "Active" : "Select"}</button>
        ${canUpload ? `<button class="btn danger small-btn" data-delete="${d.id}">Delete</button>` : ""}
      </td></tr>`).join("")}</table></div>`;
  $$("[data-select]", el).forEach(b => b.onclick = () => selectDataset(Number(b.dataset.select)));
  $$("[data-delete]", el).forEach(b => b.onclick = () => deleteDataset(Number(b.dataset.delete)));
  renderPreview();
}

async function renderPreview() {
  const el = $("#previewContent");
  if (!state.datasetId) { el.innerHTML = `<p class="muted">Select a dataset to preview it.</p>`; return; }
  el.innerHTML = `<div class="loading">Loading preview…</div>`;
  try {
    const d = await api(`/api/datasets/${state.datasetId}/preview?page=${state.previewPage}`);
    const mapping = Object.entries(d.dataset.mapping)
      .map(([k, v]) => `<span class="pill blue">${esc(k)} ← ${esc(v)}</span>`).join("");
    el.innerHTML = `
      <p class="small"><strong>${esc(d.dataset.name)}</strong> · ${fmt(d.total_rows)} rows ·
        page ${d.page} · cell completeness ${fmt1(d.profile.completeness_pct)}%</p>
      <div class="mapping-chips">${mapping || `<span class="pill solid">No known columns detected</span>`}</div>
      <div class="tabs"><button class="tab-btn active" id="tabRows">Rows</button>
        <button class="tab-btn" id="tabProfile">Column profile</button></div>
      <div id="previewRows" class="table-wrap"><table class="data">
        <tr>${d.columns.map(c => `<th>${esc(c)}</th>`).join("")}</tr>
        ${d.rows.map(r => `<tr>${r.map(v => `<td>${v === null ? `<span class="pill lime">missing</span>` : esc(v)}</td>`).join("")}</tr>`).join("")}
      </table></div>
      <div id="previewProfile" class="table-wrap hidden"><table class="data">
        <tr><th>Column</th><th>Type</th><th class="num">Missing</th><th class="num">Missing %</th><th class="num">Unique</th><th>Examples</th></tr>
        ${d.profile.per_column.map(c => `<tr><td><strong>${esc(c.name)}</strong></td><td>${esc(c.dtype)}</td>
          <td class="num">${fmt(c.missing)}</td><td class="num">${fmt1(c.missing_pct)}%</td>
          <td class="num">${fmt(c.unique)}</td><td>${esc(c.examples.join(", "))}</td></tr>`).join("")}
      </table></div>
      <div style="margin-top:12px;display:flex;gap:8px">
        <button class="btn secondary small-btn" id="prevPage" ${d.page <= 1 ? "disabled" : ""}>← Previous</button>
        <button class="btn secondary small-btn" id="nextPage" ${d.page * d.per_page >= d.total_rows ? "disabled" : ""}>Next →</button></div>`;
    $("#tabRows").onclick = () => { $("#previewRows").classList.remove("hidden"); $("#previewProfile").classList.add("hidden"); $("#tabRows").classList.add("active"); $("#tabProfile").classList.remove("active"); };
    $("#tabProfile").onclick = () => { $("#previewProfile").classList.remove("hidden"); $("#previewRows").classList.add("hidden"); $("#tabProfile").classList.add("active"); $("#tabRows").classList.remove("active"); };
    $("#prevPage").onclick = () => { state.previewPage--; renderPreview(); };
    $("#nextPage").onclick = () => { state.previewPage++; renderPreview(); };
  } catch (e) { el.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
}

async function renderQuality() {
  const el = $("#qualityContent");
  if (!state.datasetId) return noDataset(el);
  loading(el);
  try {
    const { quality: q } = await api(`/api/datasets/${state.datasetId}/quality`);
    state.quality = q;
    const weights = Object.entries(q.score_weights).map(([k, w]) => `${k} ${w}`).join(" · ");
    el.innerHTML = `
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Overall data-quality score</h2>
        <div class="score-ring" style="margin-top:8px">${scoreDonut(q.overall_score)}
          <div><p style="margin:0 0 8px">${ratingPill(q.rating)}</p>
          <p class="small muted" style="max-width:320px">Weighted score (weights: ${esc(weights)}).
          Bands are deliberately strict: Excellent ≥ 95, Good ≥ 85, Fair ≥ 70.
          Outliers are flagged for review but never reduce the score — an outlier
          may be a genuine outbreak.</p>
          <p class="small"><strong>${fmt1(q.complete_records_pct)}%</strong> of records have all key fields
          (${esc((q.key_fields || []).join(", "))}).</p></div></div></div>
      <div class="card"><h2>Dimensions</h2><p class="card-sub">Each dimension is scored independently (WHO data-quality dimensions).</p>
        ${dimensionRows(q.dimensions)}
        <div class="notice">${esc(q.timeliness.note)}${q.timeliness.assessable ?
          `<br><strong>${fmt(q.timeliness.late_rows)}</strong> late reports (${fmt1(q.timeliness.late_pct)}%) ·
           median delay ${fmt1(q.timeliness.median_delay_days)} days after month end.` : ""}</div></div>
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Missing values by column</h2><p class="card-sub">Share of rows missing a value in each column</p>
        ${q.missing_by_column.map(c => `<div class="dim-row"><span>${esc(c.name)}</span>
          <div class="bar-track"><div class="bar-fill ${c.missing_pct > 10 ? "taupe" : "teal"}" style="width:${Math.min(c.missing_pct, 100)}%"></div></div>
          <span>${fmt1(c.missing_pct)}%</span></div>`).join("")}</div>
      <div class="card"><h2>Validity flags</h2><p class="card-sub">Values that cannot be correct as recorded</p>
        <div class="table-wrap"><table class="data" style="min-width:0">
          <tr><th>Issue</th><th class="num">Records</th></tr>
          ${q.checks.filter(c => /Negative|Non-numeric|Future|Unrecognised|Districts not/.test(c.check))
            .map(c => `<tr><td>${esc(c.check)}</td><td class="num"><strong>${fmt(c.affected)}</strong></td></tr>`).join("")}
        </table></div>
        ${q.unknown_districts.length ? `<p class="small" style="margin-top:10px">Not in the 28-district list:
          ${q.unknown_districts.map(d => `<span class="pill solid">${esc(d)}</span>`).join(" ")}</p>` : ""}
        <p class="small muted">Exact duplicate rows: <strong>${fmt(q.duplicates)}</strong> ·
          possible extreme outliers for review: <strong>${fmt(q.outlier_count)}</strong>.</p></div>
    </div>
    <div class="card" style="margin-bottom:16px"><h2>All checks — records affected</h2>
      <p class="card-sub">Nothing is silently corrected: every problem is counted here first.</p>
      <div class="table-wrap"><table class="data">
        <tr><th>Check</th><th class="num">Affected</th><th class="num">%</th><th>What it means</th></tr>
        ${q.checks.map(c => `<tr><td><strong>${esc(c.check)}</strong></td><td class="num">${fmt(c.affected)}</td>
          <td class="num">${c.pct === null ? "N/A" : fmt1(c.pct) + "%"}</td><td>${esc(c.meaning)}</td></tr>`).join("")}
      </table></div></div>
    <div class="card"><h2>Possible extreme outliers — verify, do not auto-delete</h2>
      <p class="card-sub">Beyond 3 × IQR within the same disease / district / sex / age group
      (spreadsheet row numbers include the header row). Showing the largest ${q.outliers.length} of ${fmt(q.outlier_count)}.</p>
      ${q.outliers.length ? `<div class="table-wrap"><table class="data">
        <tr><th class="num">Row</th><th>Disease</th><th>District</th><th>Period</th><th class="num">Cases</th><th class="num">Usual max for group</th></tr>
        ${q.outliers.map(o => `<tr><td class="num">${o.row}</td><td>${esc(o.disease)}</td><td>${esc(o.district)}</td>
          <td>${esc(o.period)}</td><td class="num"><strong>${fmt(o.cases)}</strong></td>
          <td class="num">${fmt(o.expected_max)}</td></tr>`).join("")}</table></div>`
        : `<p class="muted">No extreme outliers detected.</p>`}
      <div class="no-print" style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn secondary" id="showCleanLogBtn">Preview cleaning actions</button>
        <button class="btn" id="cleanedCsvQualityBtn">Download cleaned CSV</button></div>
      <div id="cleanLogQuality" style="margin-top:12px"></div></div>`;
    $("#showCleanLogBtn").onclick = showCleaningLog;
  } catch (e) { el.innerHTML = `<div class="card"><div class="error-box">${esc(e.message)}</div></div>`; }
}

async function showCleaningLog() {
  const targets = [$("#cleanLogQuality"), $("#cleanLog")].filter(Boolean);
  try {
    const d = await api(`/api/datasets/${state.datasetId}/cleaned.csv?log=1`);
    const html = `<div class="table-wrap"><table class="data" style="min-width:0">
      <tr><th>Cleaning action</th><th class="num">Cells / rows affected</th></tr>
      ${d.cleaning_log.map(l => `<tr><td>${esc(l.action)}</td><td class="num">${fmt(l.affected)}</td></tr>`).join("")}
      </table></div><p class="small muted">Cleaned export keeps ${fmt(d.rows)} rows.</p>`;
    targets.forEach(t => t.innerHTML = html);
  } catch (e) { toast(e.message + " (cleaning export needs an analyst/admin account)"); }
}

function buildFilters(options) {
  const sel = (id, label, values) => `<div class="field"><label for="${id}">${label}</label>
    <select id="${id}"><option value="">All</option>${values.map(v => `<option>${esc(v)}</option>`).join("")}</select></div>`;
  $("#filterBar").innerHTML =
    sel("fDisease", "Disease", options.disease) + sel("fDistrict", "District", options.district) +
    sel("fRegion", "Region", options.region) + sel("fSex", "Sex", options.sex) +
    sel("fAge", "Age group", options.age_group) +
    `<div class="field"><label for="fFrom">From (month)</label><input id="fFrom" type="month" min="${options.date_min || ""}" max="${options.date_max || ""}"></div>
     <div class="field"><label for="fTo">To (month)</label><input id="fTo" type="month" min="${options.date_min || ""}" max="${options.date_max || ""}"></div>`;
  state.filtersBuiltFor = state.datasetId;
}
function currentFilters() {
  const f = { disease: $("#fDisease")?.value, district: $("#fDistrict")?.value,
              region: $("#fRegion")?.value, sex: $("#fSex")?.value,
              age_group: $("#fAge")?.value, date_from: $("#fFrom")?.value,
              date_to: $("#fTo")?.value };
  return Object.fromEntries(Object.entries(f).filter(([, v]) => v));
}

async function renderPatterns() {
  const el = $("#patternsContent");
  if (!state.datasetId) return noDataset(el);
  loading(el);
  try {
    const filters = state.filtersBuiltFor === state.datasetId ? currentFilters() : {};
    const qs = new URLSearchParams(filters).toString();
    const { patterns: p } = await api(`/api/datasets/${state.datasetId}/patterns?${qs}`);
    state.patterns = p;
    if (state.filtersBuiltFor !== state.datasetId) buildFilters(p.filter_options);
    const active = Object.entries(p.filters_applied);
    $("#filterStatus").textContent = active.length ?
      "Filters: " + active.map(([k, v]) => `${k} = ${v}`).join(" · ") : "No filters applied";
    const hmMax = Math.max(1, ...p.heatmap.cells.flat());
    el.innerHTML = `
    <div class="grid kpis" style="margin-bottom:16px">
      ${kpiCard("Cases in selection", fmt(p.kpis.total_cases), `${esc(p.kpis.period_start || "—")} to ${esc(p.kpis.period_end || "—")}`, "chip-blue", icon.cases)}
      ${kpiCard("Deaths in selection", p.kpis.total_deaths === null ? "—" : fmt(p.kpis.total_deaths),
        p.kpis.case_fatality_pct === null ? "No deaths column" : `Case-fatality <strong>${fmt1(p.kpis.case_fatality_pct)}%</strong>`, "chip-teal", icon.shield)}
      ${kpiCard("Records in selection", fmt(p.kpis.records), `<strong>${fmt(p.kpis.diseases)}</strong> diseases`, "chip-green", icon.rows)}
      ${kpiCard("Districts in selection", fmt(p.kpis.districts), `of <strong>28</strong> Malawi districts`, "chip-lime", icon.pin)}
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Trend over time</h2><p class="card-sub">Monthly cases in the current selection (months with no reports shown as zero)</p>
        <div class="chart-box">${lineChart(p.trend_monthly)}</div></div>
      <div class="card"><h2>Cases by disease</h2><p class="card-sub">Within the current selection</p>
        <div class="chart-box">${barChart(p.by_disease, 250, true)}</div></div>
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Cases by district</h2><p class="card-sub">Top districts in the current selection</p>
        <div class="chart-box">${hBarChart(p.by_district)}</div></div>
      <div class="grid" style="gap:16px">
        <div class="card"><h2>By sex</h2>${donutChart(p.by_sex, 170)}</div>
        <div class="card"><h2>By age group</h2><div class="chart-box">${barChart(p.by_age_group, 210)}</div></div>
      </div>
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Seasonality</h2><p class="card-sub">Cases by calendar month across all years in the selection</p>
        <div class="chart-box">${barChart(p.seasonality, 240)}</div></div>
      <div class="card"><h2>District × disease heatmap</h2><p class="card-sub">Darker teal = more reported cases (flat colour steps)</p>
        ${p.heatmap.districts.length ? `<div class="table-wrap"><table class="data" style="min-width:0">
          <tr><th>District</th>${p.heatmap.diseases.map(d => `<th class="num">${esc(d)}</th>`).join("")}</tr>
          ${p.heatmap.districts.map((dist, i) => `<tr><td><strong>${esc(dist)}</strong></td>
            ${p.heatmap.cells[i].map(v => `<td class="heat-cell" style="background:rgba(127,194,155,${(0.10 + 0.82 * v / hmMax).toFixed(2)})">${fmt(v)}</td>`).join("")}</tr>`).join("")}
          </table></div>` : `<p class="muted">Needs both district and disease data.</p>`}</div>
    </div>
    <div class="grid two">
      <div class="card"><h2>District table — burden with completeness</h2>${districtTable(p.district_table)}</div>
      <div>${insightsBox(p.insights)}</div>
    </div>`;
  } catch (e) { el.innerHTML = `<div class="card"><div class="error-box">${esc(e.message)}</div></div>`; }
}

async function renderReports() {
  const el = $("#reportContent");
  if (!state.datasetId) return noDataset(el);
  loading(el);
  try {
    const { quality: q, patterns: p } = await getOverview();
    const ds = state.datasets.find(d => d.id === state.datasetId);
    const topTable = (rows, label) => `<div class="table-wrap"><table class="data" style="min-width:0">
      <tr><th>${label}</th><th class="num">Cases</th><th class="num">Share</th></tr>
      ${rows.slice(0, 5).map(r => `<tr><td>${esc(r.label)}</td><td class="num">${fmt(r.value)}</td>
        <td class="num">${p.kpis.total_cases ? fmt1(100 * r.value / p.kpis.total_cases) + "%" : "—"}</td></tr>`).join("")}</table></div>`;
    el.innerHTML = `<div class="card">
      <p class="pill lime">Situation report</p>
      <h1 style="margin-top:8px">Public health data quality &amp; disease pattern report</h1>
      <p class="muted">Dataset: <strong>${esc(ds?.name || "")}</strong> · Generated
        ${new Date().toLocaleString("en-GB")} by ${esc(state.user.name)} (${esc(state.user.role)}) ·
        Period ${esc(p.kpis.period_start || "—")} to ${esc(p.kpis.period_end || "—")}</p>
      ${ds?.is_demo ? `<div class="notice">Demo dataset: synthetic test data — not real Malawi statistics.</div>` : ""}
      <div class="grid half" style="margin:16px 0">
        <div><h2>Data quality: ${fmt1(q.overall_score)} / 100 — ${esc(q.rating)}</h2>${dimensionRows(q.dimensions)}
          <p class="small muted">${esc(q.timeliness.note)}</p></div>
        <div><h2>Headline numbers</h2>
          <div class="table-wrap"><table class="data" style="min-width:0">
            <tr><td>Total reported cases</td><td class="num"><strong>${fmt(p.kpis.total_cases)}</strong></td></tr>
            <tr><td>Total deaths</td><td class="num">${p.kpis.total_deaths === null ? "—" : fmt(p.kpis.total_deaths)}</td></tr>
            <tr><td>Case-fatality</td><td class="num">${p.kpis.case_fatality_pct === null ? "—" : fmt1(p.kpis.case_fatality_pct) + "%"}</td></tr>
            <tr><td>Records analysed</td><td class="num">${fmt(p.kpis.records)}</td></tr>
            <tr><td>Duplicate rows</td><td class="num">${fmt(q.duplicates)}</td></tr>
            <tr><td>Records missing a key field</td><td class="num">${fmt(q.checks[0].affected)} (${fmt1(q.checks[0].pct)}%)</td></tr>
          </table></div></div>
      </div>
      <div class="grid half"><div><h2>Top diseases</h2>${topTable(p.by_disease, "Disease")}</div>
        <div><h2>Top districts</h2>${topTable(p.by_district, "District")}</div></div>
      <h2 style="margin-top:18px">Interpretation</h2>
      ${insightsBox(p.insights).replaceAll("card", "")}
      <h2 style="margin-top:14px">Methods &amp; limitations</h2>
      <p>Exploratory Data Analysis (EDA) with Pandas: descriptive counts, monthly trends,
      district comparisons and WHO-style data-quality dimensions (completeness, validity,
      uniqueness, consistency, timeliness) plus extreme-outlier flagging at 3 × IQR.
      Negative and future-dated records are excluded from case totals but remain
      counted in the data-quality results above.</p><p>
      Patterns are exploratory observations, not proof of cause, and must be interpreted
      together with reporting completeness, case definitions and timeliness above.
      This system does not diagnose individuals and does not declare outbreaks.</p>
      <p><strong>Malawi 2063 alignment:</strong> digital transformation of public services,
      stronger health information for evidence-based planning, and human-capital
      development through usable, low-bandwidth digital tools.</p></div>`;
  } catch (e) { el.innerHTML = `<div class="card"><div class="error-box">${esc(e.message)}</div></div>`; }
}

async function renderAdmin() {
  const el = $("#adminContent");
  loading(el);
  try {
    const [{ users }, sys, { audit }] = await Promise.all([
      api("/api/admin/users"), api("/api/admin/system"), api("/api/admin/audit")]);
    el.innerHTML = `
    <div class="grid kpis" style="margin-bottom:16px">
      ${kpiCard("Registered users", fmt(sys.users), "All roles", "chip-blue", icon.rows)}
      ${kpiCard("Datasets stored", fmt(sys.datasets), "Including demo data", "chip-teal", icon.cases)}
      ${kpiCard("SQLite database", sys.database_size_kb + " KB", esc(sys.database_file), "chip-green", icon.shield)}
      ${kpiCard("Backup", "Ready", "Download a full database copy", "chip-lime", icon.pin)}
    </div>
    <div class="grid two" style="margin-bottom:16px">
      <div class="card"><h2>Create user</h2><p class="card-sub">Roles: admin (all), analyst (upload/analyse/export), viewer (read-only)</p>
        <form id="createUserForm">
          <div class="field"><label>Full name</label><input id="cuName" required></div>
          <div class="field"><label>Email</label><input id="cuEmail" type="email" required></div>
          <div class="field"><label>Password (8+ characters)</label><input id="cuPassword" type="text" required minlength="8"></div>
          <div class="field"><label>Role</label><select id="cuRole"><option>analyst</option><option>viewer</option><option>admin</option></select></div>
          <button class="btn" type="submit">Create user</button></form>
        <hr style="border:0;border-top:1px solid rgba(101,82,77,.16);margin:20px 0">
        <h2>Database backup</h2><p class="small muted">SQLite is the test &amp; backup database.
          Restore by replacing <em>instance/app.sqlite3</em> with the backup file while the server is stopped.</p>
        <button class="btn lime" id="backupBtn">Download backup (.sqlite3)</button></div>
      <div class="card"><h2>Users</h2><div class="table-wrap"><table class="data" style="min-width:0">
        <tr><th>Name</th><th>Role</th><th>Status</th><th></th></tr>
        ${users.map(u => `<tr><td><strong>${esc(u.name)}</strong><div class="small muted">${esc(u.email)}</div></td>
          <td><span class="pill ${u.role === "admin" ? "solid-blue" : u.role === "analyst" ? "" : "blue"}">${esc(u.role)}</span></td>
          <td>${u.is_active ? `<span class="pill">Active</span>` : `<span class="pill solid">Inactive</span>`}</td>
          <td><button class="btn secondary small-btn" data-toggle-user="${u.id}">${u.is_active ? "Deactivate" : "Activate"}</button></td></tr>`).join("")}
        </table></div></div>
    </div>
    <div class="card"><h2>Recent system activity (audit log)</h2>
      <div class="table-wrap"><table class="data">
      <tr><th>When (UTC)</th><th>User</th><th>Action</th><th>Detail</th></tr>
      ${audit.slice(0, 30).map(a => `<tr><td>${esc(a.created_at)}</td><td>${esc(a.user_email || "—")}</td>
        <td><strong>${esc(a.action)}</strong></td><td>${esc(a.detail || "")}</td></tr>`).join("")}
      </table></div></div>`;
    $("#backupBtn").onclick = () => downloadFile("/api/admin/backup.sqlite3");
    $$("[data-toggle-user]", el).forEach(b => b.onclick = async () => {
      try { await api(`/api/admin/users/${b.dataset.toggleUser}/toggle-active`, { method: "POST" });
        toast("User updated", true); renderAdmin(); } catch (e) { toast(e.message); } });
    $("#createUserForm").onsubmit = async ev => {
      ev.preventDefault();
      try { await api("/api/admin/users", { method: "POST", body: JSON.stringify({
              name: $("#cuName").value, email: $("#cuEmail").value,
              password: $("#cuPassword").value, role: $("#cuRole").value }) });
        toast("User created", true); renderAdmin(); } catch (e) { toast(e.message); } };
  } catch (e) { el.innerHTML = `<div class="card"><div class="error-box">${esc(e.message)}</div></div>`; }
}

function renderHelp() {
  $("#helpContent").innerHTML = `
  <h2>5-minute final test (do this in order)</h2>
  <ol style="line-height:1.7">
    <li>Sign in as <strong>analyst@demo.mw / Analyst123!</strong> — the Dashboard opens on the demo dataset.</li>
    <li>Note the four KPI cards, the monthly trend, and the district table. Find <strong>Mangochi</strong>:
        its completeness is ≈66% — deliberately planted, proving burden + quality are shown together.</li>
    <li>Open <strong>Data Quality</strong>: the overall score should be ≈93/100 “Good”, timeliness is the
        weakest dimension, and the top outlier is the planted Mangochi malaria spike (Feb 2024).</li>
    <li>Open <strong>Disease Patterns</strong>, filter <em>Disease = Malaria</em>, apply — every chart,
        KPI and the heatmap must change. Clear the filters.</li>
    <li>In <strong>Datasets</strong>, download the CSV template, then upload
        <em>sample_data/test_dirty_data.csv</em> from the project folder and confirm its planted
        errors are detected (expected results are in docs/TEST_PLAN_AND_RESULTS.md).</li>
    <li>In <strong>Reports</strong>, download the cleaned CSV and print the situation report to PDF.</li>
    <li>Sign out, sign in as <strong>viewer@demo.mw / Viewer123!</strong> — uploading must now be disabled.
        Sign in as <strong>admin@demo.mw / Admin123!</strong> to test user management and the SQLite backup.</li>
  </ol>
  <h2>Accepted column names</h2>
  <p>Headers are matched case-insensitively; spaces and hyphens are ignored. Accepted aliases include:
  <em>disease/condition/diagnosis</em>, <em>district</em>, <em>region</em>, <em>facility</em>,
  <em>period_date/date/month/reporting period</em>, <em>date_reported/report date/submission date</em>,
  <em>cases/value/count/total cases</em>, <em>deaths</em>, <em>sex/gender</em>, <em>age_group/age</em>.
  If there is no cases column, each row is counted as one case (line-list mode). Files containing
  personal identifiers (name, phone, national id, address) are refused.</p>
  <h2>How the data-quality score is calculated</h2>
  <p>Weighted mean of: completeness 30 (% of records with all key fields), validity 25
  (negative/non-numeric cases, future dates, unrecognised sex, districts outside the 28),
  uniqueness 20 (exact duplicates), timeliness 15 (reported within 15 days of month end —
  only when both dates exist; otherwise weights are re-normalised), consistency 10
  (deaths &gt; cases, conflicting re-submitted totals). Extreme outliers (3 × IQR within the
  same disease/district/sex/age group) are listed for human review and do not lower the score.</p>
  <h2>Design system (applied strictly)</h2>
  <div class="palette-row" style="margin:12px 0">
    <div style="background:#65524D;color:#FFFFFF">65524D<br><span class="small">Taupe grey — text, sidebar active</span></div>
    <div style="background:#5878E9;color:#FFFFFF">5878E9<br><span class="small">Blue — primary actions, main chart series</span></div>
    <div style="background:#7FC29B;color:#65524D">7FC29B<br><span class="small">Muted teal — secondary series, good status</span></div>
    <div style="background:#B5EF8A;color:#65524D">B5EF8A<br><span class="small">Light green — highlights, page tint</span></div>
    <div style="background:#D7F171;color:#65524D">D7F171<br><span class="small">Lime — insight &amp; demo accents</span></div>
  </div>
  <p>Only these five colours (+ white and flat tints of them) are used — no other hues and
  <strong>no gradients</strong>. One typeface (<strong>Arial</strong>) is used at every size and weight;
  layout follows the supplied dashboard inspiration: white left sidebar with pill navigation,
  four KPI cards, two-column chart grid, and a statistics table — with proposal content
  (data quality + disease patterns) instead of clinical patient widgets.</p>
  <h2>Python integration</h2>
  <p>Analyse any file directly in Python (no server needed):</p>
  <div class="code-box">import pandas as pd
from analysis import analyse_dataframe

df = pd.read_csv("sample_data/malawi_synthetic_health_data.csv")
result = analyse_dataframe(df)
print(result["quality"]["overall_score"], result["quality"]["rating"])</div>
  <p style="margin-top:14px">Or call the REST API from Python (requests), R, or DHIS2-side scripts:</p>
  <div class="code-box">GET  /api/health
POST /api/auth/login                 {email, password}
GET  /api/datasets
POST /api/datasets/upload            (multipart: file, name, description)
GET  /api/datasets/&lt;id&gt;/preview?page=1
GET  /api/datasets/&lt;id&gt;/quality
GET  /api/datasets/&lt;id&gt;/patterns?disease=Malaria&amp;district=Mangochi
GET  /api/datasets/&lt;id&gt;/cleaned.csv?drop_duplicates=1
GET  /api/admin/backup.sqlite3       (admin only)</div>
  <h2>Scope, ethics &amp; limitations</h2>
  <p>De-identified/aggregate data only. The system complements DHIS2/HMIS — it does not replace
  them, diagnose patients, or declare outbreaks. Correlations and visual patterns do not prove
  causation. Timeliness assumes period_date is the reporting month. District ranking uses
  reported counts, not population rates, unless a population denominator is added in future work.</p>`;
}

/* ============================ shell logic ============================ */
function switchView(view) {
  $$(".view").forEach(v => v.classList.add("hidden"));
  $(`#view-${view}`).classList.remove("hidden");
  $$(".nav-btn").forEach(b => b.classList.toggle("active", b.dataset.view === view));
  const names = { overview: "Dashboard", datasets: "Datasets", quality: "Data Quality",
                  patterns: "Disease Patterns", reports: "Reports & Export",
                  admin: "Administration", help: "Help & Test Guide" };
  $("#crumbView").textContent = names[view] || view;
  ({ overview: renderOverview, datasets: renderDatasets, quality: renderQuality,
     patterns: renderPatterns, reports: renderReports, admin: renderAdmin,
     help: renderHelp })[view]?.();
  window.scrollTo({ top: 0 });
}
window.switchView = switchView;

async function refreshDatasets(keepSelection = true) {
  const { datasets } = await api("/api/datasets");
  state.datasets = datasets;
  const prev = state.datasetId;
  state.datasetId = (keepSelection && datasets.some(d => d.id === prev)) ? prev :
                    (datasets.find(d => d.is_demo)?.id ?? datasets[0]?.id ?? null);
  $("#datasetSelect").innerHTML = datasets.length ?
    datasets.map(d => `<option value="${d.id}" ${d.id === state.datasetId ? "selected" : ""}>${esc(d.name)} (${fmt(d.row_count)} rows)</option>`).join("") :
    `<option value="">No datasets — upload one</option>`;
  syncCrumb();
}
function syncCrumb() {
  const ds = state.datasets.find(d => d.id === state.datasetId);
  $("#crumbDataset").textContent = ds ? `Active dataset: ${ds.name}` : "No dataset selected";
  $("#topScorePill").textContent = "Data quality —";
  state.overview = null; state.filtersBuiltFor = null; state.previewPage = 1;
}
function selectDataset(id) {
  state.datasetId = id; $("#datasetSelect").value = String(id); syncCrumb();
  toast("Active dataset changed", true);
  const visible = $$(".view").find(v => !v.classList.contains("hidden"));
  switchView(visible.id.replace("view-", ""));
}
async function deleteDataset(id) {
  if (!confirm("Delete this dataset permanently?")) return;
  try { await api(`/api/datasets/${id}`, { method: "DELETE" });
    toast("Dataset deleted", true); await refreshDatasets(false); renderDatasets();
  } catch (e) { toast(e.message); }
}

function showLogin(message) {
  $("#loginView").classList.remove("hidden"); $("#appView").classList.add("hidden");
  const box = $("#loginError");
  if (message) { box.textContent = message; box.classList.remove("hidden"); }
  else box.classList.add("hidden");
}
async function showApp(user) {
  state.user = user;
  $("#loginView").classList.add("hidden"); $("#appView").classList.remove("hidden");
  $("#sideUserName").textContent = user.name;
  $("#sideUserMeta").textContent = `${user.email} · ${user.role}`;
  $("#adminNav").classList.toggle("hidden", user.role !== "admin");
  try {
    await refreshDatasets(false);
  } catch (e) {
    // A 401 here has already routed us back to login via sessionExpired();
    // only surface other errors, and stay in the app if we still hold a token.
    if (!getToken()) return;
    toast(e.message);
  }
  switchView("overview");
}

/* events */
$("#loginForm").addEventListener("submit", async ev => {
  ev.preventDefault();
  try {
    const data = await api("/api/auth/login", { method: "POST", body: JSON.stringify({
      email: $("#loginEmail").value, password: $("#loginPassword").value }) });
    setToken(data.token);
    $("#loginError").classList.add("hidden");
    showApp(data.user);
  } catch (e) { const b = $("#loginError"); b.textContent = e.message; b.classList.remove("hidden"); }
});
$("#logoutBtn").addEventListener("click", async () => {
  // Revoke the token server-side, then forget it locally. No page reload:
  // reloading inside an embedded preview only re-runs the boot check.
  try { await api("/api/auth/logout", { method: "POST" }); } catch (e) { /* already out */ }
  setToken(null); state.user = null; state.datasets = []; state.datasetId = null;
  $("#loginPassword").value = "";
  showLogin();
});
$$(".nav-btn").forEach(b => b.addEventListener("click", () => switchView(b.dataset.view)));
$("#datasetSelect").addEventListener("change", e => { if (e.target.value) selectDataset(Number(e.target.value)); });
$("#refreshOverviewBtn").addEventListener("click", async () => { state.overview = null; renderOverview(); });
$("#applyFiltersBtn").addEventListener("click", renderPatterns);
$("#clearFiltersBtn").addEventListener("click", () => {
  $$("#filterBar select, #filterBar input").forEach(i => i.value = ""); renderPatterns(); });
const go = url => { if (!state.datasetId) return toast("Select a dataset first"); downloadFile(url); };
$("#templateBtn")?.addEventListener("click", () => downloadFile("/api/template.csv"));
$("#dqCsvBtn").addEventListener("click", () => go(`/api/datasets/${state.datasetId}/quality-summary.csv`));
$("#reportDqBtn").addEventListener("click", () => go(`/api/datasets/${state.datasetId}/quality-summary.csv`));
$("#patternCsvBtn").addEventListener("click", () =>
  go(`/api/datasets/${state.datasetId}/pattern-summary.csv?${new URLSearchParams(currentFilters())}`));
$("#reportPatternBtn").addEventListener("click", () => go(`/api/datasets/${state.datasetId}/pattern-summary.csv`));
$("#cleanedCsvBtn").addEventListener("click", async () => {
  await showCleaningLog();
  go(`/api/datasets/${state.datasetId}/cleaned.csv?drop_duplicates=${$("#dropDupCheck").checked ? 1 : 0}`); });
$("#printReportBtn").addEventListener("click", () => window.print());
$("#uploadForm")?.addEventListener("submit", async ev => {
  ev.preventDefault();
  const file = $("#uploadFile").files[0];
  if (!file) return toast("Choose a file first");
  const fd = new FormData();
  fd.append("file", file); fd.append("name", $("#uploadName").value);
  fd.append("description", $("#uploadDesc").value);
  try {
    const res = await fetch("/api/datasets/upload", {
      method: "POST", body: fd, headers: authHeaders(), credentials: "same-origin" });
    if (res.status === 401) { sessionExpired(); throw new Error("Session expired — please sign in again."); }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Upload failed");
    toast("Dataset uploaded and profiled", true);
    await refreshDatasets(false); state.datasetId = data.dataset_id;
    $("#datasetSelect").value = String(data.dataset_id); syncCrumb(); renderDatasets();
  } catch (e) { toast(e.message); }
});
const dz = $("#dropZone");
if (dz) { ["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", e => { if (e.dataTransfer.files.length) $("#uploadFile").files = e.dataTransfer.files; }); }

/* boot: a stored token (or the fallback session cookie) restores the
   session without showing the login page; a dead token is discarded. */
(async () => {
  try { const { user } = await api("/api/me"); showApp(user); }
  catch (e) { setToken(null); showLogin(); }
})();
