/* SupplyGraph frontend — vanilla JS, talks to the FastAPI backend. */
const API = window.SUPPLYGRAPH_API || "";
const $ = (id) => document.getElementById(id);
const state = { supplierId: null, detail: null, graphView: "ego", sim: null, portfolio: null };

const TYPE_COLORS = {
  Country: "#f5a524", Supplier: "#5b8cff", Contract: "#a78bfa", Facility: "#2dd4bf", Product: "#22c58b",
  ProductLine: "#f472b6", Site: "#94a3b8", Alternative: "#34d399", Event: "#ff4d6d",
};
const LEVEL_COLORS = { HIGH: "#ff4d6d", MEDIUM: "#f5a524", LOW: "#22c58b" };

async function api(path, body) {
  const res = await fetch(API + path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  } : undefined);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n).toLocaleString("en-US");
const duration = () => Number($("duration").value);

/* ------------------------------------------------------------------ boot */
async function boot() {
  try {
    const h = await api("/api/health");
    $("status-text").textContent = "SYSTEM READY";
    $("status").title = `${h.nodes} nodes • ${h.edges} edges in the digital twin`;
  } catch (e) {
    $("status").classList.add("err");
    $("status-text").textContent = "BACKEND OFFLINE";
    return;
  }
  const suppliers = await api("/api/suppliers");
  $("supplier-select").innerHTML = suppliers.map((s) => `<option value="${s.supplier_id}">${esc(s.name)}</option>`).join("");
  $("supplier-select").addEventListener("change", (e) => selectSupplier(e.target.value));
  bindUI();
  renderLegend();
  await selectSupplier(suppliers[0].supplier_id);
}

function bindUI() {
  document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => showTab(t.dataset.tab)));
  document.querySelectorAll(".seg-btn").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
    state.graphView = b.dataset.view;
    loadGraph();
  }));
  const slider = $("duration");
  const sync = () => {
    $("duration-value").textContent = slider.value;
    slider.style.setProperty("--p", `${((slider.value - slider.min) / (slider.max - slider.min)) * 100}%`);
  };
  slider.addEventListener("input", sync); sync();
  $("run-btn").addEventListener("click", runScenario);
  $("ask-btn").addEventListener("click", () => askAdvisor($("question").value));
  $("why-btn").addEventListener("click", () => { $("question").value = "Why am I exposed?"; askAdvisor("Why am I exposed?"); });
  document.querySelectorAll(".quick button").forEach((b) => b.addEventListener("click", () => {
    $("question").value = b.dataset.q; askAdvisor(b.dataset.q);
  }));
  $("question").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) askAdvisor($("question").value); });
  $("zoom-in").onclick = () => zoomBy(1.2);
  $("zoom-out").onclick = () => zoomBy(1 / 1.2);
  $("zoom-fit").onclick = fitGraph;
}

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  ["twin", "sim", "portfolio"].forEach((n) => ($(`tab-${n}`).hidden = n !== name));
  if (name === "twin") loadGraph();
  if (name === "portfolio") loadPortfolio();
}

async function selectSupplier(id) {
  state.supplierId = id;
  $("supplier-select").value = id;
  state.sim = null;
  $("sim-result").innerHTML = "";
  $("answer").innerHTML = "";
  state.detail = await api(`/api/suppliers/${id}`);
  renderProfile(state.detail);
  renderEvidence(state.detail.evidence);
  if (!$("tab-twin").hidden) loadGraph();
}

/* ------------------------------------------------------------------ profile */
function renderProfile(d) {
  $("p-name").textContent = d.name;
  $("p-chips").innerHTML = `<span class="chip">${esc(d.country)}</span><span class="chip ${d.criticality === "Critical" ? "crit" : ""}">${esc(d.criticality)}</span>`;
  $("p-spend").textContent = `${fmt(d.annual_spend_sek)} SEK`;
  $("p-category").textContent = d.category;
  $("p-dependency").textContent = `${d.dependency_pct}%`;
  $("p-inventory").textContent = `${d.inventory_cover_days} days`;
  $("p-score").textContent = d.risk.overall;
  $("p-score").className = `score lv-${d.risk.level}`;
  $("p-level").textContent = d.risk.level;
  $("p-level").className = `score-level lv-${d.risk.level}`;
  $("p-bars").innerHTML = d.risk.dimensions.map((dim) => `
    <div class="bar" title="Click to see why">
      <div class="bar-top"><span>${dim.label}</span><b>${dim.score}</b></div>
      <div class="track"><div class="fill ${dim.score >= 70 ? "hot" : ""}" style="width:0" data-w="${dim.score}"></div></div>
      <div class="bar-factors">${dim.factors.map((f) => `<div><span>${esc(f.name)}: ${esc(f.value)}</span><span>+${f.contribution}</span></div>`).join("")}</div>
    </div>`).join("");
  requestAnimationFrame(() => document.querySelectorAll("#p-bars .fill").forEach((el) => (el.style.width = el.dataset.w + "%")));
  document.querySelectorAll("#p-bars .bar").forEach((b) => b.addEventListener("click", () => b.classList.toggle("open")));
  const imp = d.impact;
  $("p-impact").innerHTML = `
    <div><b>${imp.products.length}</b> components • <b>${imp.product_lines.length}</b> product lines • <b>${imp.sites.length}</b> sites</div>
    ${imp.product_lines.map((l) => `<div>${esc(l.name)} — <b>${l.input_share_pct}%</b> of input</div>`).join("")}
    ${imp.same_country_suppliers.length ? `<div>Shares country risk with: <b>${imp.same_country_suppliers.map(esc).join(", ")}</b></div>` : ""}`;
}

function renderEvidence(items) {
  $("evidence").innerHTML = items.map((e, i) => `
    <div class="ev" data-i="${i}" style="${e.detail?.length ? "cursor:pointer" : ""}">
      <div><div class="t">${esc(e.label)}</div><div class="s">${esc(e.source)} • ${esc(e.tag)}</div>
        <div class="ev-detail" hidden>${(e.detail || []).map((x) => `${esc(x.date)} — ${esc(x.type)} (${x.severity}/10)`).join("<br>")}</div></div>
      <div class="v">${esc(e.value)}</div>
    </div>`).join("");
  document.querySelectorAll("#evidence .ev").forEach((el) => el.addEventListener("click", () => {
    const d = el.querySelector(".ev-detail"); if (d.innerHTML) d.hidden = !d.hidden;
  }));
}

/* ------------------------------------------------------------------ simulator */
async function runScenario() {
  const btn = $("run-btn");
  btn.disabled = true;
  try {
    const r = await api("/api/simulate", { supplier_id: state.supplierId, duration_days: duration() });
    state.sim = r;
    renderSim(r);
  } catch (e) {
    $("sim-result").innerHTML = `<div class="error">Simulation failed: ${esc(e.message)}</div>`;
  } finally { btn.disabled = false; }
}

function renderSim(r) {
  const D = r.duration_days;
  const pct = (x) => `${Math.min(100, (x / D) * 100)}%`;
  const segs = r.timeline.map((t) => t.kind === "marker"
    ? `<div class="tl-marker" style="left:${pct(t.at)}"><span>Alternative online · day ${t.at}</span></div>`
    : `<div class="tl-seg ${t.kind}" style="left:${pct(t.start)};width:calc(${pct(t.end)} - ${pct(t.start)})"></div>`).join("");
  const metric = (label, v) => `<div class="metric"><div class="tile-label">${label}</div><div class="v">${v}</div></div>`;
  $("sim-result").innerHTML = `
    <span class="badge ${r.exposure_level}">${r.exposure_level} EXPOSURE</span>
    <div class="note">⚠ Potential supply gap is the percentage of modeled supply dependency associated with this supplier. It is <b>not a financial loss</b> percentage.</div>
    <div class="metrics">
      ${metric("Potential supply gap", `${r.potential_supply_gap_pct}%`)}
      ${metric("Inventory cover", `${r.inventory_cover_days} days`)}
      ${metric("Uncovered period", `${r.uncovered_days} days`)}
      ${metric("Qualified alternatives", `${r.qualified_alternatives_pct}%`)}
      ${metric("Residual supply gap", `${r.residual_supply_gap_pct}%`)}
      ${metric("Termination", r.termination_notice_days != null ? `${r.termination_notice_days} days` : "—")}
    </div>
    <div class="timeline">
      <div class="tl-labels"><span>TODAY</span><span>DISRUPTION END · DAY ${D}</span></div>
      <div class="tl-track">${segs}</div>
      <div class="tl-legend"><span><i style="background:var(--accent-2)"></i>Inventory cover</span>
        <span><i style="background:var(--red)"></i>Uncovered</span>
        ${r.bridge_gap_days ? `<span>Bridge gap before first alternative: <b style="color:var(--text)">${r.bridge_gap_days} days</b></span>` : ""}</div>
    </div>
    <div class="card section">
      <h3>Recommended response</h3>
      ${r.recommendations.map((x, i) => `<div class="rec"><div class="rec-n">${i + 1}</div>
        <div><div class="rec-title">${esc(x.title)}</div><div class="rec-detail">${esc(x.detail)}</div></div>
        <div class="rec-h">${esc(x.horizon)}</div></div>`).join("")}
    </div>
    <div class="card section">
      <h3>Alternative sources</h3>
      <table><thead><tr><th>Supplier</th><th>Country</th><th>Qualified</th><th>Capacity</th><th>Ramp-up</th><th>Status</th></tr></thead>
      <tbody>${r.alternatives.map((a) => `<tr><td>${esc(a.name)}</td><td>${esc(a.country)}</td>
        <td class="${a.qualified ? "ok" : "no"}">${a.qualified ? "Yes" : "No"}</td><td>${a.spare_capacity_pct}%</td>
        <td>${a.ramp_up_days} d</td><td class="${a.usable_in_window ? "ok" : "no"}">${esc(a.reason)}</td></tr>`).join("") || `<tr><td colspan="6" class="no">No alternatives on file</td></tr>`}</tbody></table>
    </div>
    <div class="card section">
      <h3>Downstream impact (from the digital twin)</h3>
      <div class="impact small">
        <div>Components: <b>${r.impact.products.map(esc).join(", ")}</b></div>
        ${r.impact.product_lines.map((l) => `<div>${esc(l.name)}: <b>${l.input_share_pct}%</b> of modelled input</div>`).join("")}
        <div>Sites: <b>${r.impact.sites.map(esc).join(", ") || "—"}</b></div>
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ advisor */
async function askAdvisor(q) {
  if (!q.trim()) return;
  $("answer").innerHTML = `<div class="loading">Reasoning over evidence…</div>`;
  try {
    const a = await api("/api/advisor", { supplier_id: state.supplierId, question: q, duration_days: duration() });
    $("answer").innerHTML = `<div class="answer"><div class="h">${esc(a.headline)}</div>
      <ul>${a.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>
      ${a.evidence.length ? `<div class="used">${a.evidence.map((e) => `<span>${esc(e.label)}: ${esc(e.value)}</span>`).join("")}</div>` : ""}
      <div class="meta">Engine: ${esc(a.engine)} • ${esc(a.disclaimer)} • scenario ${duration()} days</div></div>`;
  } catch (e) {
    $("answer").innerHTML = `<div class="error">Advisor unavailable: ${esc(e.message)}</div>`;
  }
}

/* ------------------------------------------------------------------ portfolio */
function heat(v) {
  const c = v >= 70 ? "rgba(255,77,109,.22)" : v >= 40 ? "rgba(245,165,36,.18)" : "rgba(34,197,139,.15)";
  const t = v >= 70 ? "#ff8da1" : v >= 40 ? "#f5c26b" : "#5fe0b0";
  return `<span class="heat" style="background:${c};color:${t}">${v}</span>`;
}
async function loadPortfolio() {
  const rows = state.portfolio || (state.portfolio = await api("/api/portfolio"));
  const byCountry = {};
  rows.forEach((r) => {
    const c = (byCountry[r.country_code] ||= { spend: 0, n: 0, exp: 0 });
    c.spend += r.annual_spend_sek; c.n += 1; c.exp += r.overall * r.annual_spend_sek;
  });
  const total = rows.reduce((a, r) => a + r.annual_spend_sek, 0);
  const spendAtRisk = rows.filter((r) => r.level === "HIGH").reduce((a, r) => a + r.annual_spend_sek, 0);
  $("portfolio").innerHTML = `
    <div class="metrics" style="grid-template-columns:repeat(3,1fr);margin-bottom:16px">
      <div class="metric"><div class="tile-label">Suppliers modelled</div><div class="v">${rows.length}</div></div>
      <div class="metric"><div class="tile-label">Total annual spend</div><div class="v">${fmt(total)} SEK</div></div>
      <div class="metric"><div class="tile-label">Spend with HIGH-exposure suppliers</div><div class="v">${Math.round((spendAtRisk / total) * 100)}%</div></div>
    </div>
    <div class="card section" style="margin-top:0">
      <h3>Exposure heatmap</h3>
      <table><thead><tr><th>Supplier</th><th>Country</th><th>Spend (SEK)</th><th>Overall</th><th>Fin</th><th>Geo</th><th>Dep</th><th>Contract</th><th>Ops</th></tr></thead>
      <tbody>${rows.map((r) => `<tr class="click" data-id="${r.supplier_id}"><td>${esc(r.name)}</td><td>${r.country_code}</td>
        <td>${fmt(r.annual_spend_sek)}</td><td>${heat(r.overall)}</td>${["financial", "geopolitical", "dependency", "contract", "operational"].map((k) => `<td>${heat(r.dimensions[k])}</td>`).join("")}</tr>`).join("")}</tbody></table>
    </div>
    <div class="card section">
      <h3>Country concentration</h3>
      ${Object.entries(byCountry).sort((a, b) => b[1].spend - a[1].spend).map(([cc, c]) => `
        <div class="bar"><div class="bar-top"><span>${cc} · ${c.n} supplier(s) · spend-weighted exposure ${Math.round(c.exp / c.spend)}</span><b>${Math.round((c.spend / total) * 100)}%</b></div>
        <div class="track"><div class="fill" style="width:${(c.spend / total) * 100}%"></div></div></div>`).join("")}
    </div>`;
  document.querySelectorAll("#portfolio tr.click").forEach((tr) => tr.addEventListener("click", async () => {
    await selectSupplier(tr.dataset.id); showTab("sim");
  }));
}

/* ------------------------------------------------------------------ digital twin graph */
const NW = 200, NH = 56, HG = 34, VG = 104;
const view = { x: 0, y: 0, k: 1 };
let graphData = null;

function renderLegend() {
  $("legend").innerHTML = Object.entries(TYPE_COLORS).map(([t, c]) => `<span><i style="background:${c}"></i>${t}</span>`).join("");
}

async function loadGraph() {
  const svg = $("graph");
  svg.innerHTML = "";
  $("node-card").hidden = true;
  graphData = state.graphView === "ego" ? await api(`/api/suppliers/${state.supplierId}/graph`) : await api("/api/graph");
  if (state.graphView === "full") {
    const L = { Country: 0, Alternative: 1, Supplier: 2, Contract: 3, Facility: 3, Product: 3, ProductLine: 4, Site: 5 };
    graphData.nodes.forEach((n) => (n.layer = L[n.type] ?? 0));
    const byId = Object.fromEntries(graphData.nodes.map((n) => [n.id, n]));
    graphData.edges = graphData.edges.filter((e) => !(e.type === "LOCATED_IN" && byId[e.source]?.type === "Facility"));
  }
  layout(graphData);
  drawGraph(graphData);
  fitGraph();
}

function layout(g) {
  const rows = {};
  g.nodes.forEach((n) => (rows[n.layer] ||= []).push(n));
  const nb = {};
  g.edges.forEach((e) => { (nb[e.source] ||= []).push(e.target); (nb[e.target] ||= []).push(e.source); });
  const keys = Object.keys(rows).map(Number).sort((a, b) => a - b);
  const typeOrder = ["Country", "Event", "Supplier", "Alternative", "Contract", "Product", "Facility", "ProductLine", "Site"];
  keys.forEach((k) => rows[k].sort((a, b) => typeOrder.indexOf(a.type) - typeOrder.indexOf(b.type)));
  const horiz = state.graphView === "full"; // full network flows left → right
  const place = (k) => {
    const r = rows[k];
    if (horiz) {
      const h = r.length * NH + (r.length - 1) * 16;
      r.forEach((n, i) => { n.y = -h / 2 + i * (NH + 16); n.x = k * (NW + 110); });
    } else {
      const w = r.length * NW + (r.length - 1) * HG;
      r.forEach((n, i) => { n.x = -w / 2 + i * (NW + HG); n.y = k * (NH + VG); });
    }
  };
  const sec = (n) => (horiz ? n.y : n.x);
  keys.forEach(place);
  const anchor = state.graphView === "full" ? [2] : [0, 1];
  if (state.graphView === "ego") {
    // ego view: focus supplier & country centred, alternatives / events to the right
    [0, 1].forEach((k) => {
      if (!rows[k]) return;
      const [head, ...rest] = rows[k];
      head.x = -NW / 2;
      rest.forEach((n, i) => (n.x = NW / 2 + HG * 2 + i * (NW + HG)));
    });
  }
  // barycentric sweeps to reduce edge crossings
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  for (let s = 0; s < 4; s++) {
    const order = s % 2 ? [...keys].reverse() : keys;
    order.forEach((k) => {
      if (anchor.includes(k)) return;
      rows[k].forEach((n) => {
        const ns = (nb[n.id] || []).map((id) => byId[id]).filter((m) => m && m.layer !== k).map(sec);
        n.bc = ns.length ? ns.reduce((a, b) => a + b, 0) / ns.length : sec(n);
      });
      rows[k].sort((a, b) => a.bc - b.bc);
      place(k);
    });
  }
}

function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }

function drawGraph(g) {
  const svg = $("graph");
  const NS = "http://www.w3.org/2000/svg";
  const root = document.createElementNS(NS, "g");
  root.id = "viewport";
  const byId = Object.fromEntries(g.nodes.map((n) => [n.id, n]));
  let html = "";
  let sameRowIdx = 0;
  const labels = [];
  g.edges.forEach((e) => {
    const a = byId[e.source], b = byId[e.target];
    if (!a || !b) return;
    let d, lx, ly;
    if (state.graphView === "full") {
      const [u, v] = a.layer < b.layer ? [a, b] : [b, a];
      const x1 = u.x + NW, y1 = u.y + NH / 2, x2 = v.x, y2 = v.y + NH / 2, xm = x2 - 40;
      d = `M${x1},${y1} H${xm} V${y2} H${x2}`;
    } else if (a.layer === b.layer) {
      const lift = 22 + (sameRowIdx++ % 6) * 7;
      const x1 = a.x + NW / 2, x2 = b.x + NW * (a.x > b.x ? 0.75 : 0.25), y = a.y - lift;
      d = `M${x1},${a.y} V${y} H${x2} V${b.y}`;
      lx = (x1 + x2) / 2; ly = y;
    } else {
      const [u, v] = a.layer < b.layer ? [a, b] : [b, a];
      const x1 = u.x + NW / 2, y1 = u.y + NH, x2 = v.x + NW / 2, y2 = v.y, ym = (y1 + y2) / 2;
      d = `M${x1},${y1} V${ym} H${x2} V${y2}`;
      lx = Math.abs(x1 - x2) < 1 ? x1 : (x1 + x2) / 2 + (x2 - x1) * 0.25; ly = ym;
    }
    const cls = e.type === "ALTERNATIVE_FOR" ? `gedge alt ${e.qualified ? "" : "unq"}` : "gedge";
    html += `<path class="${cls}" d="${d}"/>`;
    if (state.graphView === "ego") labels.push({ lx, ly, t: e.type });
  });
  labels.forEach(({ lx, ly, t }) => {
    const w = t.length * 5.2 + 10;
    html += `<g class="elabel" transform="translate(${lx - w / 2},${ly - 7})"><rect width="${w}" height="14"/><text x="5" y="10">${t}</text></g>`;
  });
  g.nodes.forEach((n) => {
    const color = n.type === "Supplier" && n.level ? LEVEL_COLORS[n.level] : TYPE_COLORS[n.type] || "#888";
    const focus = n.id === `supplier:${state.supplierId}`;
    html += `<g class="gnode ${focus ? "focus" : ""}" data-id="${esc(n.id)}" transform="translate(${n.x},${n.y})" style="cursor:pointer">
      <rect width="${NW}" height="${NH}"/>
      <rect class="stripe" x="0" y="8" width="3" height="${NH - 16}" fill="${color}"/>
      <text class="type" x="12" y="15">${n.type.toUpperCase()}</text>
      <text class="label" x="12" y="31">${esc(trunc(n.label, 30))}</text>
      <text class="sub" x="12" y="45">${esc(trunc(n.subtitle || "", 42))}</text>
    </g>`;
  });
  root.innerHTML = html;
  svg.appendChild(root);
  root.querySelectorAll(".gnode").forEach((el) => el.addEventListener("click", (ev) => {
    ev.stopPropagation();
    root.querySelectorAll(".gnode.sel").forEach((x) => x.classList.remove("sel"));
    el.classList.add("sel");
    showNodeCard(byId[el.dataset.id], g, byId);
  }));
  applyView();
}

function showNodeCard(n, g, byId) {
  const rels = g.edges.filter((e) => e.source === n.id || e.target === n.id).map((e) => {
    const other = byId[e.source === n.id ? e.target : e.source];
    return `<div class="rel">${e.source === n.id ? "→" : "←"} ${e.type} <b>${esc(other?.label || "")}</b></div>`;
  }).join("");
  const card = $("node-card");
  card.innerHTML = `<span class="x" id="nc-x">✕</span>
    <div class="eyebrow" style="color:${TYPE_COLORS[n.type]}">${n.type}</div>
    <div class="strong" style="margin-bottom:4px">${esc(n.label)}</div>
    <div class="muted small" style="margin-bottom:8px">${esc(n.subtitle || "")}</div>
    ${n.description ? `<div class="small" style="margin-bottom:8px">${esc(n.description)}</div>` : ""}
    ${n.risk != null ? `<div class="small" style="margin-bottom:8px">Risk: <b>${n.risk}</b>/100</div>` : ""}
    ${rels}
    ${n.type === "Supplier" && n.ref !== state.supplierId ? `<button class="btn btn-primary wide" id="nc-open">Open supplier</button>` : ""}`;
  card.hidden = false;
  $("nc-x").onclick = () => (card.hidden = true);
  if ($("nc-open")) $("nc-open").onclick = () => { selectSupplier(n.ref); };
}

/* pan & zoom */
function applyView() {
  const vp = $("viewport");
  if (vp) vp.setAttribute("transform", `translate(${view.x},${view.y}) scale(${view.k})`);
}
function fitGraph() {
  const vp = $("viewport"), wrap = $("graph-wrap");
  if (!vp) return;
  const bb = vp.getBBox(), W = wrap.clientWidth, H = wrap.clientHeight, pad = 50;
  view.k = Math.min(1.4, (W - pad * 2) / bb.width, (H - pad * 2) / bb.height);
  view.x = W / 2 - (bb.x + bb.width / 2) * view.k;
  view.y = H / 2 - (bb.y + bb.height / 2) * view.k;
  applyView();
}
function zoomBy(f, cx, cy) {
  const wrap = $("graph-wrap");
  cx ??= wrap.clientWidth / 2; cy ??= wrap.clientHeight / 2;
  const k = Math.max(0.15, Math.min(3, view.k * f));
  view.x = cx - ((cx - view.x) * k) / view.k;
  view.y = cy - ((cy - view.y) * k) / view.k;
  view.k = k;
  applyView();
}
(() => {
  const wrap = $("graph-wrap");
  let drag = null;
  wrap.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = wrap.getBoundingClientRect();
    zoomBy(e.deltaY < 0 ? 1.1 : 1 / 1.1, e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  wrap.addEventListener("mousedown", (e) => {
    if (e.target.closest(".node-card,.zoom,.gnode")) return;
    drag = { x: e.clientX - view.x, y: e.clientY - view.y };
    wrap.classList.add("dragging");
  });
  window.addEventListener("mousemove", (e) => { if (drag) { view.x = e.clientX - drag.x; view.y = e.clientY - drag.y; applyView(); } });
  window.addEventListener("mouseup", () => { drag = null; wrap.classList.remove("dragging"); });
  window.addEventListener("resize", () => { if (!$("tab-twin").hidden) fitGraph(); });
})();

boot();
