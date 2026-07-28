import { formatDate, formatDateRange, formatDateTime } from "./formatDate.js";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function boldNumbers(text) {
  return escapeHtml(text).replace(/(\d[\d,]*\.?\d*%?)/g, "<b>$1</b>");
}

function rankingBasisLabel(basis) {
  if (basis === "arrival_qty") return "arrival volume (tonnes)";
  if (basis?.startsWith("price_quote_count")) return "number of price quotes (arrival volume unavailable this week)";
  return basis;
}

function deltaSpan(pct, { invert = false } = {}) {
  if (pct == null) return '<span style="color:var(--muted)">n/a</span>';
  const good = invert ? pct < 0 : pct >= 0;
  const color = good ? "var(--good)" : "var(--bad)";
  const arrow = pct >= 0 ? "&#9650;" : "&#9660;";
  return `<span style="color:${color};font-weight:600">${arrow} ${Math.abs(pct)}%</span>`;
}

function chip(kind, label) {
  const map = { ok: ["var(--chip-ok-bg)", "var(--good)"], watch: ["var(--chip-watch-bg)", "var(--warn)"], act: ["var(--chip-act-bg)", "var(--bad)"], na: ["var(--gridline)", "var(--muted)"] };
  const [bg, fg] = map[kind] || map.na;
  return `<span style="display:inline-block;font-size:9.5px;letter-spacing:.09em;text-transform:uppercase;font-weight:600;padding:2px 6px;border-radius:2px;background:${bg};color:${fg}">${escapeHtml(label)}</span>`;
}

function sectionHead(n, title, tag) {
  return `<div class="sec-head"><span class="sec-num">${n}</span><h2>${escapeHtml(title)}</h2>${tag ? `<span class="sec-tag">${escapeHtml(tag)}</span>` : ""}</div>`;
}

function mastHtml(fs) {
  const mc = fs.market_compliance;
  const generated = fs.generated_at ? formatDate(fs.generated_at.slice(0, 10)) : "—";
  return `
  <header class="mast">
    <div class="mast-eyebrow">Agmarknet 2.0 &middot; Decision Intelligence</div>
    <h1>Weekly Market Intelligence Summary<em>Madhya Pradesh &mdash; State Consolidated Brief</em></h1>
    <div class="mast-period">
      <div class="mp-item"><span class="k">Period</span><span class="v">${escapeHtml(formatDateRange(fs.week_start, fs.week_end))}</span></div>
      <div class="mp-item"><span class="k">Market yards in scope</span><span class="v">${mc.markets_in_roster}</span></div>
      <div class="mp-item"><span class="k">Reported</span><span class="v">${mc.markets_reporting_at_least_once}</span></div>
      <div class="mp-item"><span class="k">Generated</span><span class="v">${escapeHtml(generated)}</span></div>
      ${fs.snapshot_id ? `<div class="mp-item"><span class="k">Snapshot</span><span class="v">${escapeHtml(fs.snapshot_id)}</span></div>` : ""}
    </div>
  </header>`;
}

function coverageHtml(fs) {
  const cov = fs.coverage;
  if (!cov) return "";
  const mc = fs.market_compliance;
  return `
  <div class="cov">
    <span class="cov-badge">Coverage</span>
    <span>Completeness <b class="tabular">${cov.completeness_pct}%</b> &mdash; ${mc.markets_reporting_at_least_once} of ${mc.markets_in_roster} active market yards reported at least one day</span>
    <span>Records processed <b class="tabular">${cov.records_processed.toLocaleString()}</b></span>
  </div>`;
}

function muted(s) {
  return s ? `<span style="color:var(--ink2);font-weight:500">${s}</span>` : "";
}

function wowDelta(pct) {
  if (pct == null) return "";
  const good = pct >= 0;
  return `<span style="color:${good ? "var(--good)" : "var(--bad)"};font-weight:600">${good ? "&#9650;" : "&#9660;"} ${Math.abs(pct)}% WoW</span>`;
}

/** Mirrors StatTiles.jsx's tile set exactly — same chips (Action/Normal,
 * Watch/Normal), same "Rs price" sub for gainer/decliner tiles (not a
 * duplicate delta span), same WoW-suffixed delta on the arrival tile. */
function kpiGridHtml(fs) {
  const oa = fs.overall_arrivals, mc = fs.market_compliance, tc = fs.top_commodities, pc = fs.price_change, alerts = fs.alerts;
  const top = tc.top_commodities[0];
  const unit = oa.total_arrivals_basis === "arrival_qty" ? " tonnes" : " (quote count)";
  const compliancePct = mc.markets_in_roster ? (mc.markets_reporting_at_least_once / mc.markets_in_roster) * 100 : null;
  const topGainer = pc?.available ? pc.top_gainers[0] : null;
  const topDecliner = pc?.available ? pc.top_decliners[0] : null;
  const openAlerts = alerts ? alerts.counts.Critical + alerts.counts.High + alerts.counts.Watch : null;
  // Same order as StatTiles.jsx: yards reporting, compliance, arrival,
  // commodities traded, gainer, decliner first, then the rest unchanged.
  const tiles = [
    ["Market yards reporting", `${mc.markets_reporting_at_least_once} / ${mc.markets_in_roster}`,
      muted(`${mc.markets_not_reporting} non-reporting`) + chip(mc.markets_not_reporting > 0 ? "act" : "ok", mc.markets_not_reporting > 0 ? "Action" : "Normal")],
    ["State compliance score", compliancePct != null ? `${compliancePct.toFixed(1)}%` : "—",
      chip(compliancePct != null && compliancePct < 85 ? "watch" : "ok", compliancePct != null && compliancePct < 85 ? "Watch" : "Normal")],
    ["Total arrival", `${oa.total_arrivals.toLocaleString()}${unit}`, wowDelta(oa.wow_pct_change)],
    ["Commodities traded", tc.total_commodities_traded, ""],
    ["Largest price gain", topGainer ? topGainer.commodity : "—",
      topGainer ? muted(`Rs ${topGainer.current_modal_price.toLocaleString()}`) + chip("watch", `▲ ${topGainer.pct_change}%`) : chip("na", "n/a")],
    ["Largest price fall", topDecliner ? topDecliner.commodity : "—",
      topDecliner ? muted(`Rs ${topDecliner.current_modal_price.toLocaleString()}`) + chip("act", `▼ ${topDecliner.pct_change}%`) : chip("na", "n/a")],
    ["Top commodity by arrival", top ? top.commodity : "—",
      top ? muted(`${top.arrival_value.toLocaleString()} tonnes${top.share_pct_of_state_arrivals != null ? ` &middot; ${top.share_pct_of_state_arrivals}%` : ""}`) : ""],
    ["Open alerts", openAlerts ?? "—",
      (alerts ? muted(`${alerts.counts.Critical} Critical &middot; ${alerts.counts.High} High`) : "") + (alerts ? chip(alerts.counts.Critical > 0 ? "act" : "ok", alerts.counts.Critical > 0 ? "Action" : "Normal") : "")],
    ["Top reporting market", mc.top_reporting_market ?? "—", mc.top_reporting_market_days != null ? muted(`${mc.top_reporting_market_days}/7 days`) : ""],
    ["Markets reporting 5-6 days", mc.markets_reporting_5_to_6_days, muted(`${mc.markets_reporting_all_7_days} at 7/7 days`)],
  ];
  return `<div class="kpi-grid">${tiles.map(([label, value, d]) => `
    <div class="kpi-cell">
      <span class="k">${escapeHtml(label)}</span>
      <span class="v tabular">${escapeHtml(String(value))}</span>
      <span class="d">${d}</span>
    </div>`).join("")}</div>`;
}

function narrativeHtml(text, meta) {
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean).slice(1);
  const body = paragraphs.length ? paragraphs : text.split(/\n\s*\n/).filter(Boolean);
  const scoreGood = meta?.accuracy_pct != null && meta.accuracy_pct >= 99.9;
  const badge = meta?.accuracy_pct != null
    ? `<span class="score-pill ${scoreGood ? "score-good" : "score-warn"}">${meta.accuracy_pct}% numbers verified</span>`
    : "";
  return `
    <div class="narr">
      <div class="narr-h"><span>Executive Narrative</span>${badge}</div>
      ${body.map((p) => `<p>${boldNumbers(p)}</p>`).join("")}
    </div>`;
}

// See TopCommodities.jsx for why this set is hardcoded rather than sourced
// from the fact sheet, and why Coriander(Leaves) — confirmed Bundle-unit in
// the archived raw dataset — is the one real match.
const NON_WEIGHT_COMMODITIES = new Set(["coriander(leaves)", "egg", "coconut"]);
function isNonWeightCommodity(name) {
  return NON_WEIGHT_COMMODITIES.has(String(name ?? "").trim().toLowerCase());
}

function topCommoditiesHtml(tc) {
  const maxValue = Math.max(...tc.top_commodities.map((r) => r.arrival_value), 1);
  const hasNonWeightRow = tc.top_commodities.some((r) => isNonWeightCommodity(r.commodity));
  const rows = tc.top_commodities.map((r) => `
    <tr>
      <td>${escapeHtml(r.commodity)}${isNonWeightCommodity(r.commodity) ? "*" : ""}</td>
      <td class="num tabular">${r.arrival_value.toLocaleString()}</td>
      <td>
        <div class="bar-cell">
          <div class="bar-fill" style="width:${(r.arrival_value / maxValue) * 100}%"></div>
          <span class="bar-label tabular">${r.share_pct_of_state_arrivals != null ? r.share_pct_of_state_arrivals + "%" : "—"}</span>
        </div>
      </td>
      <td class="num tabular">${r.markets_trading}</td>
      <td class="num tabular">${(r.modal_price_weighted ?? r.modal_price_mean) != null ? "Rs " + (r.modal_price_weighted ?? r.modal_price_mean).toLocaleString() : "—"}</td>
      <td class="num tabular">${r.wow_arrival_pct_change == null ? '<span style="color:var(--muted)">n/a</span>' : deltaSpan(r.wow_arrival_pct_change)}</td>
    </tr>`).join("");
  const top = tc.top_commodities[0];
  const highlight = top
    ? `<div class="section-highlight">${escapeHtml(top.commodity)} led state arrivals at ${top.arrival_value.toLocaleString()} tonnes${
        top.share_pct_of_state_arrivals != null ? ` or ${top.share_pct_of_state_arrivals} per cent` : ""
      } of total volume.</div>`
    : "";
  return `<section class="sec">
    ${sectionHead("02", "Commodity arrivals", "By arrival volume")}
    ${highlight}
    <table>
      <thead><tr><th>Commodity</th><th class="num">Arrivals (Quintals/Tonnes)</th><th>Share</th><th class="num">Markets</th><th class="num">Modal price</th><th class="num">WoW arrivals</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="footnote">Ranked by ${escapeHtml(rankingBasisLabel(tc.ranking_basis))}. ${tc.total_commodities_traded} commodities traded this week in total.</p>
    ${hasNonWeightRow ? '<p class="footnote">* Not measured in Quintals/Tonnes for this commodity — reported in its own unit of sale (e.g. bundles).</p>' : ""}
    ${donutHtml(tc.donut_slices, tc.concentration_hhi)}
  </section>`;
}

const DONUT_COLORS = ["#1F5C3D", "#2E7D52", "#4E9670", "#1B3A5C", "#3D6489", "#B8791C", "#D0A054", "#A8321E", "#C9CFC7"];

function hhiLabel(hhi) {
  if (hhi < 0.15) return "Low concentration";
  if (hhi < 0.25) return "Moderate concentration";
  return "High concentration";
}

// html2canvas (the engine behind the PDF export) has no support at all for
// conic-gradient — verified against its source (zero references to "conic"
// anywhere in it) — so a donut built from `background: conic-gradient(...)`
// renders as a blank circle in the PDF even though it displays fine in a
// live browser. Built as stacked SVG <circle> strokes (stroke-dasharray per
// slice) instead, which html2canvas does render correctly, and which looks
// identical on screen.
function donutHtml(slices, hhi) {
  if (!slices?.length) return "";
  const R = 78, CX = 100, CY = 100, SW = 44;
  const CIRC = 2 * Math.PI * R;
  let cumulative = 0;
  const arcs = slices.map((s, i) => {
    const pct = s.share_pct_of_state_arrivals ?? 0;
    const len = (pct / 100) * CIRC;
    const offset = -(cumulative / 100) * CIRC;
    cumulative += pct;
    return `<circle cx="${CX}" cy="${CY}" r="${R}" fill="none" stroke="${DONUT_COLORS[i % DONUT_COLORS.length]}" stroke-width="${SW}" stroke-dasharray="${len.toFixed(3)} ${(CIRC - len).toFixed(3)}" stroke-dashoffset="${offset.toFixed(3)}" transform="rotate(-90 ${CX} ${CY})" />`;
  }).join("");
  const legend = slices.map((s, i) => `
    <li><span class="donut-swatch" style="background:${DONUT_COLORS[i % DONUT_COLORS.length]}"></span>
      <span class="donut-legend-name">${escapeHtml(s.commodity)}</span>
      <span class="donut-legend-value tabular">${s.share_pct_of_state_arrivals != null ? s.share_pct_of_state_arrivals + "%" : "—"}</span>
    </li>`).join("");
  return `
    <h3 class="panel-subheading">Share of state arrival</h3>
    <div class="donut-wrap">
      <div class="donut-chart">
        <svg viewBox="0 0 200 200" width="200" height="200">${arcs}</svg>
        <div class="donut-hole">
          ${hhi != null ? `<span class="donut-hhi tabular">${hhi}</span><span class="donut-hhi-label">HHI &middot; ${hhiLabel(hhi)}</span>` : ""}
        </div>
      </div>
      <ul class="donut-legend">${legend}</ul>
    </div>
    <p class="footnote">Concentration is measured by the Herfindahl&ndash;Hirschman Index over all commodities' arrival shares, not just those shown above.</p>`;
}

const AXIS_TICK_COUNT = 6; // 0..globalMax in 5 even steps -> 6 labeled ticks

function priceBandsHtml(bands) {
  if (!bands?.length) return "";
  const globalMax = Math.max(...bands.map((b) => b.max_price), 1);
  const widest = [...bands].sort((a, b) => (b.max_price - b.min_price) / b.min_price - (a.max_price - a.min_price) / a.min_price)[0];
  const spreadRatio = widest ? (widest.max_price / widest.min_price).toFixed(1) : null;
  const ticks = Array.from({ length: AXIS_TICK_COUNT }, (_, i) => {
    const pct = (i / (AXIS_TICK_COUNT - 1)) * 100;
    return { pct, value: Math.round((pct / 100) * globalMax) };
  });
  const gridlines = ticks.map((t) => `<div class="band-gridline" style="left:${t.pct}%"></div>`).join("");
  const axisTicks = ticks.map((t) => `<span class="band-axis-tick" style="left:${t.pct}%">${t.value.toLocaleString()}</span>`).join("");
  const highlight = widest
    ? `<div class="section-highlight">The widest price band this week was ${escapeHtml(widest.commodity)}, from Rs ${widest.min_price.toLocaleString()} to Rs ${widest.max_price.toLocaleString()} per quintal, a spread of ${spreadRatio}&times; the minimum.</div>`
    : "";
  const rows = bands.map((b) => {
    const minPct = (b.min_price / globalMax) * 100;
    const maxPct = (b.max_price / globalMax) * 100;
    const modPct = b.modal_price != null ? (b.modal_price / globalMax) * 100 : null;
    return `<div class="band-row">
      <div class="band-label">${escapeHtml(b.commodity)}</div>
      <div class="band-track" title="${escapeHtml(b.commodity)}: min Rs ${b.min_price.toLocaleString()} · max Rs ${b.max_price.toLocaleString()} per quintal">
        <div class="band-range" style="left:${minPct}%;width:${maxPct - minPct}%"></div>
        <div class="band-cap" style="left:${minPct}%"></div>
        <div class="band-cap" style="left:${maxPct}%"></div>
        ${modPct != null ? `<div class="band-mod" style="left:${modPct}%"></div>` : ""}
      </div>
      <div class="band-value tabular">${b.modal_price != null ? "Rs " + b.modal_price.toLocaleString() : "—"}</div>
    </div>`;
  }).join("");
  return `<section class="sec">
    ${sectionHead("03", "Price levels and bands", "Weekly range")}
    ${highlight}
    <div class="band-chart">
      <div class="band-gridlines">${gridlines}</div>
      ${rows}
      <div class="band-axis">${axisTicks}</div>
    </div>
    <p class="footnote">Bar ends = weekly minimum and maximum reported price. Marker = arrival-weighted modal price. Rupees per quintal. X-axis shows the price scale (Rs per quintal) shared by all commodities above.</p>
  </section>`;
}

function priceTrendHtml(pt, totalCommoditiesTraded) {
  if (!pt?.commodities?.length) return "";
  const cell = (p) => p.avg_price == null
    ? '<span style="color:var(--muted)">n/a</span>'
    : `<span class="tabular">Rs ${p.avg_price.toLocaleString()}</span><br/>${deltaSpan(p.pct_change_vs_this_week)}`;
  const rows = pt.commodities.map((c) => `
    <tr>
      <td>${escapeHtml(c.commodity)}</td>
      <td class="num tabular">Rs ${c.this_week_avg_price.toLocaleString()}</td>
      <td class="num">${cell(c.last_week)}</td>
      <td class="num">${cell(c.last_month_same_week)}</td>
      <td class="num">${cell(c.last_year_same_week)}</td>
    </tr>`).join("");
  return `<section class="sec">
    ${sectionHead("04", "Price trends and comparisons", "vs prior periods")}
    <table class="price-trend-table">
      <thead><tr><th>Commodity</th><th class="num">This week avg</th><th class="num">Last week</th><th class="num">Same week last month</th><th class="num">Same week last year</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="footnote">${totalCommoditiesTraded != null ? `Showing ${pt.commodities.length} of ${totalCommoditiesTraded} commodities traded this week<span class="footnote-sep">&middot;</span>` : ""}All prices in Rs/quintal.</p>
  </section>`;
}

/** Mirrors PriceMovement.jsx's single diverging bar chart (decliners reversed
 * on top, gainers reversed at bottom — "worst to best") rather than a
 * separate two-column gainers/decliners list, which is a different visual
 * altogether from what the live app renders for this section. */
function priceMovementHtml(pc) {
  if (!pc?.available) {
    return `<section class="sec">
      ${sectionHead("05", "Price movement — gainers and decliners", "Week on week")}
      <p class="footnote">Not available this week (${escapeHtml(pc?.reason ?? "no prior-week data loaded")}).</p>
    </section>`;
  }
  const { top_gainers: gainers, top_decliners: decliners } = pc;
  const maxAbs = Math.max(...gainers.map((g) => Math.abs(g.pct_change)), ...decliners.map((d) => Math.abs(d.pct_change)), 1);
  const rows = [...decliners].reverse().concat([...gainers].reverse());
  const topGainer = gainers[0], topDecliner = decliners[0];
  const parts = [];
  if (topGainer) parts.push(`${escapeHtml(topGainer.commodity)} gained ${Math.abs(topGainer.pct_change)} per cent`);
  if (topDecliner) parts.push(`${escapeHtml(topDecliner.commodity)} declined ${Math.abs(topDecliner.pct_change)} per cent`);
  const highlight = parts.length ? `<div class="section-highlight">${parts.join(" and ")} against the previous week.</div>` : "";
  const subtitle = pc.min_trading_days_for_ranking
    ? `<p class="footnote" style="margin-top:0">Only commodities traded on at least ${pc.min_trading_days_for_ranking} days in both weeks are eligible${pc.commodities_excluded_thin_trade ? ` — ${pc.commodities_excluded_thin_trade} excluded as thin trade` : ""}.</p>`
    : "";
  const chartRows = rows.map((r) => {
    const good = r.pct_change >= 0;
    const widthPct = (Math.abs(r.pct_change) / maxAbs) * 50;
    const barStyle = good ? `left:50%;width:${widthPct}%` : `right:50%;width:${widthPct}%`;
    return `<div class="diverging-row">
      <div class="diverging-label">${escapeHtml(r.commodity)}</div>
      <div class="diverging-track">
        <div class="diverging-mid"></div>
        <div class="diverging-bar ${good ? "delta-good-bg" : "delta-bad-bg"}" style="${barStyle}" title="${escapeHtml(r.commodity)}: ${good ? "+" : ""}${r.pct_change}% (Rs ${r.prior_modal_price.toLocaleString()}/quintal &rarr; Rs ${r.current_modal_price.toLocaleString()}/quintal)"></div>
      </div>
      <div class="diverging-value tabular" style="color:${good ? "var(--good)" : "var(--bad)"}">${good ? "+" : ""}${r.pct_change}%</div>
      <div class="diverging-price tabular">Rs ${r.current_modal_price.toLocaleString()}/quintal</div>
    </div>`;
  }).join("");
  return `<section class="sec">
    ${sectionHead("05", "Price movement — gainers and decliners", "Week on week")}
    ${subtitle}
    ${highlight}
    <div class="diverging-chart">${chartRows}</div>
  </section>`;
}

function perishablesHtml(rows) {
  if (!rows?.length) return "";
  const statusChip = { action: "act", watch: "watch", normal: "ok" };
  const statusLabel = { action: "Action", watch: "Watch", normal: "Normal" };
  const flagged = rows.filter((p) => p.distress_composite);
  const highlight = flagged.length
    ? `<div class="section-highlight">${flagged.map((p) => `${escapeHtml(p.commodity)} arrivals ${p.arrival_wow_pct_change >= 0 ? "rose" : "fell"} ${Math.abs(p.arrival_wow_pct_change)}% while the modal price fell ${Math.abs(p.price_wow_pct_change)}%`).join("; ")}, satisfying the distress composite rule.</div>`
    : "";
  const cards = rows.map((p) => `
    <div class="per-card ${escapeHtml(p.status)}">
      <div class="per-h"><span>${escapeHtml(p.commodity)}</span>${chip(statusChip[p.status], statusLabel[p.status])}</div>
      <div class="per-row"><span class="l">Arrival</span><span class="v tabular">${p.arrival_value.toLocaleString()} qtl</span></div>
      <div class="per-row"><span class="l">Arrival WoW</span><span class="v">${deltaSpan(p.arrival_wow_pct_change)}</span></div>
      <div class="per-row"><span class="l">Modal price</span><span class="v tabular">${p.modal_price != null ? "Rs " + p.modal_price.toLocaleString() : "—"}</span></div>
      <div class="per-row"><span class="l">Price WoW</span><span class="v">${deltaSpan(p.price_wow_pct_change)}</span></div>
    </div>`).join("");
  return `<section class="sec">
    ${sectionHead("06", "Perishables and consumer watch", "Distress composite")}
    ${highlight}
    <div class="per-grid">${cards}</div>
    <p class="footnote">The distress composite flag is raised only when an arrival surge (WoW &ge; 15%) and a price fall (WoW &le; -15%) occur together in the same commodity and week.</p>
  </section>`;
}

const BAND_STATUS = { "0 days": "critical", "1-2 days": "serious", "3-4 days": "warning", "5-6 days": "good-muted", "7 days": "good" };

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const step = magnitude / 2;
  return Math.ceil(value / step) * step;
}

function gaugeHtml(pct) {
  const r = 70;
  const circumference = Math.PI * r;
  const filled = (Math.max(0, Math.min(100, pct)) / 100) * circumference;
  return `<div class="gauge">
    <svg viewBox="0 0 170 95" class="gauge-svg">
      <path d="M 15 90 A 70 70 0 0 1 155 90" class="gauge-track" />
      <path d="M 15 90 A 70 70 0 0 1 155 90" class="gauge-fill" style="stroke-dasharray:${filled} ${circumference}" />
    </svg>
    <div class="gauge-value tabular">${pct.toFixed(1)}%</div>
    <div class="gauge-label">Market yards reporting</div>
  </div>`;
}

/** Mirrors MarketCompliance.jsx's gauge + reporting-band bar chart — the
 * live app's section 07 is this chart, not just the highlight/footnote text
 * that used to be all this builder produced. */
function marketComplianceHtml(mc) {
  const parts = [];
  if (mc.markets_reporting_all_7_days) parts.push(`${mc.markets_reporting_all_7_days} market yards reported on all seven days`);
  if (mc.markets_reporting_5_to_6_days) parts.push(`${mc.markets_reporting_5_to_6_days} reported on five or six days`);
  let highlight = parts.join(" and ");
  highlight += mc.markets_not_reporting ? `, while ${mc.markets_not_reporting} yards filed no return at all.` : ".";

  const rawMax = Math.max(...mc.compliance_bands.map((b) => b.market_count), 1);
  const axisMax = niceMax(rawMax);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(axisMax * f));
  const reportingPct = (mc.markets_reporting_at_least_once / mc.markets_in_roster) * 100;
  const gridlines = [...ticks].reverse().map((t) => `<div class="compliance-gridline" style="bottom:${(t / axisMax) * 100}%"></div>`).join("");
  const cols = mc.compliance_bands.map((b) => `
    <div class="compliance-col">
      <div class="compliance-bar-track">
        <div class="compliance-bar-fill status-${BAND_STATUS[b.band]}" style="height:${(b.market_count / axisMax) * 100}%" title="${escapeHtml(b.band)}: ${b.market_count} markets"></div>
      </div>
      <div class="compliance-count tabular">${b.market_count}</div>
      <div class="compliance-band-label">${escapeHtml(b.band)}</div>
    </div>`).join("");
  const yTicks = [...ticks].reverse().map((t) => `<div class="compliance-y-tick">${t}</div>`).join("");

  return `<section class="sec">
    ${sectionHead("07", "Market participation and reporting compliance", "Coverage")}
    <p class="footnote">${mc.markets_reporting_at_least_once} of ${mc.markets_in_roster} registered market yards reported at least once this week.</p>
    <div class="section-highlight">${escapeHtml(highlight)}</div>
    <div class="compliance-layout">
      ${gaugeHtml(reportingPct)}
      <div class="compliance-plot">
        <div class="compliance-y-axis-label">Number of market yards</div>
        <div class="compliance-plot-body">
          <div class="compliance-y-ticks">${yTicks}</div>
          <div class="compliance-chart">${gridlines}${cols}</div>
        </div>
      </div>
    </div>
    <div class="compliance-x-axis-label">Reporting days (out of the 7-day week)</div>
    <p class="footnote">${escapeHtml(mc.roster_caveat)}</p>
  </section>`;
}

function reportingExceptionsHtml(rx) {
  if (!rx) return "";
  return `<section class="sec">
    ${sectionHead("08", "Reporting exceptions", "Compliance")}
    <div class="xsplit">
      <div class="xbox partial">
        <h4>Partial reporting</h4>
        <p class="def">Reported on at least 1 but fewer than 7 of the 7 expected days this week.</p>
        <span class="xbig tabular">${rx.partial_reporting_market_yards}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
      <div class="xbox non">
        <h4>Non-reporting</h4>
        <p class="def">Filed no return of any kind for the full reporting week.</p>
        <span class="xbig tabular">${rx.non_reporting_market_yards}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
      <div class="xbox nil">
        <h4>Nil transactions reported</h4>
        <p class="def">At least one row this week explicitly declared zero arrival quantity — compliant, and distinct from filing no return at all.</p>
        <span class="xbig tabular">${rx.nil_transactions_reported ?? 0}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
    </div>
    <p class="footnote">${escapeHtml(rx.note || "")}</p>
    ${rx.nil_transactions_note ? `<p class="footnote">${escapeHtml(rx.nil_transactions_note)}</p>` : ""}
  </section>`;
}

function alertRegisterHtml(alerts) {
  if (!alerts) return "";
  const { alerts: rows, counts } = alerts;
  const table = rows.length ? `
    <table>
      <thead><tr><th>Severity</th><th>Type</th><th>Entity affected</th><th>Trigger</th><th>Owner</th></tr></thead>
      <tbody>${rows.map((a) => `
        <tr>
          <td>${sevChip(a.severity)}</td>
          <td>${escapeHtml(a.type)}</td>
          <td>${escapeHtml(a.entity)}</td>
          <td>${escapeHtml(a.trigger)}</td>
          <td style="color:var(--muted)">${escapeHtml(a.owner)}</td>
        </tr>`).join("")}</tbody>
    </table>` : `<p class="footnote">No alerts triggered this week under the current threshold rules.</p>`;
  return `<section class="sec">
    ${sectionHead("09", "Alert register", "Rules engine")}
    <div class="alert-counts">
      <div class="ac c"><span class="n tabular">${counts.Critical}</span><span class="l">Critical</span></div>
      <div class="ac h"><span class="n tabular">${counts.High}</span><span class="l">High</span></div>
      <div class="ac w"><span class="n tabular">${counts.Watch}</span><span class="l">Watch</span></div>
    </div>
    ${table}
    <p class="footnote">Severity is assigned by fixed business rule — never by the narrative engine.</p>
  </section>`;
}

function sevChip(sev) {
  const map = { Critical: ["var(--bad)", "#fff"], High: ["var(--warn)", "var(--ink)"], Watch: ["var(--accent)", "#fff"] };
  const [bg, fg] = map[sev] || map.Watch;
  return `<span style="display:inline-block;font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;font-weight:600;padding:3px 7px;border-radius:2px;background:${bg};color:${fg}">${escapeHtml(sev)}</span>`;
}

function actionPointsHtml(rows) {
  if (!rows?.length) return "";
  return `<section class="sec">
    ${sectionHead("10", "Action points", "From alert register")}
    <table>
      <thead><tr><th>Priority</th><th>Action</th><th>Owner</th><th class="num">Target</th></tr></thead>
      <tbody>${rows.map((a) => `
        <tr>
          <td>${sevChip(a.priority)}</td>
          <td>${escapeHtml(a.action)}</td>
          <td style="color:var(--muted)">${escapeHtml(a.owner)}</td>
          <td class="num tabular">${escapeHtml(formatDate(a.target_date))}</td>
        </tr>`).join("")}</tbody>
    </table>
    <p class="footnote">Every action point traces to one triggered alert; target dates are generated-at plus a fixed number of days per severity (3 for Critical, 7 for High).</p>
  </section>`;
}

function lineageHtml(fs) {
  const cov = fs.coverage;
  return `
  <div class="lineage">
    <h4>Data lineage and reproducibility</h4>
    <div class="lg">
      <div class="lg-full">Source: <b>${escapeHtml(fs.source ?? "agmarknet.gov.in")}</b></div>
      <div>Generated: <b>${escapeHtml(fs.generated_at ? formatDateTime(fs.generated_at) : "—")}</b></div>
      ${fs.snapshot_id ? `<div>Snapshot: <b>${escapeHtml(fs.snapshot_id)}</b></div>` : ""}
      <div>Records processed: <b>${cov?.records_processed?.toLocaleString() ?? "—"}</b></div>
      <div>Numeric grounding (EN): <b>${fs.narration_meta?.en?.accuracy_pct ?? "—"}% verified</b></div>
      <div>Numeric grounding (HI): <b>${fs.narration_meta?.hi?.accuracy_pct ?? "—"}% verified</b></div>
    </div>
  </div>
  <div class="disclaim">
    <b>Data source and generation</b>
    Every figure in this report is computed deterministically from the current week's raw Agmarknet 2.0 pull.
    The executive narrative is generated only from this fact sheet's own values and is machine-validated for
    numeric grounding before publication.
  </div>`;
}

const STYLE = `
  /* Downloaded/printed report is always light mode, regardless of the
     viewer's OS/browser dark-mode preference — a distributed document
     shouldn't shift appearance depending on who opens it or how. No
     prefers-color-scheme override here on purpose. */
  :root {
    color-scheme: light;
    --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e; --muted:#898781;
    --gridline:#e1e0d9; --border:rgba(11,11,11,.12); --good:#006300; --good2:#0ca30c; --good-bg:#cdeccd;
    --bad:#d03b3b; --bad-bg:#f6d3d3; --warn:#fab219; --warn-bg:#fde9c4;
    --accent:#2a78d6; --accent-bg:#dbe8f8; --serious:#ec835a;
    --chip-ok-bg:var(--good-bg); --chip-watch-bg:var(--warn-bg); --chip-act-bg:var(--bad-bg);
  }
  * { box-sizing: border-box; outline: none !important; caret-color: transparent; }
  .tabular { font-variant-numeric: tabular-nums; }
  /* Pure white, not the app's own off-white --page tint — a downloaded
     report should read as a real printed/typed document, not a screen UI.
     (The @media print block below also sets this, but that block never
     actually applies during the html2canvas/html2pdf capture — verified —
     so the base rule has to carry this directly, not just the print copy.) */
  body { font-size: 14px; color: var(--ink); background: #fff; max-width: 735px; margin: 0 auto; padding: 0 22px 64px; font-feature-settings: "tnum" 1; }
  h1, h2, h3, h4 { }
  h1 { font-weight: 700; font-size: 30px; line-height: 1.08; margin: 6px 0 2px; letter-spacing: -.01em; }
  h1 em { font-style: normal; display: block; font-size: 16px; font-weight: 500; opacity: .9; margin-top: 4px; }
  h2 { font-size: 22px; font-weight: 600; margin: 0; flex: 1; letter-spacing: -.005em; }
  h4 { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; margin: 0 0 10px; }
  .mast { background: var(--good); color: #fff; border-radius: 10px; padding: 22px 26px 18px; margin: 0 0 16px; position: relative; overflow: hidden; }
  .mast:after { content: ""; position: absolute; inset: auto 0 0 0; height: 4px; background: repeating-linear-gradient(90deg in srgb, var(--warn) 0 32px, var(--good2) 32px 64px); }
  .mast-eyebrow { font-size: 11px; letter-spacing: .16em; text-transform: uppercase; color: #fff; opacity: .82; font-weight: 500; }
  .mast-period { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px 20px; margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,.24); }
  .mp-item .k { font-size: 10px; letter-spacing: .14em; text-transform: uppercase; color: #fff; opacity: .72; display: block; }
  .mp-item .v { font-size: 14px; font-weight: 500; color: #fff; }
  .cov { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin: 0 0 26px; padding: 13px 30px; display: flex; gap: 20px; flex-wrap: wrap; align-items: center; font-size: 12.5px; color: var(--ink2); }
  .cov-badge { font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; font-weight: 600; padding: 3px 9px; border-radius: 2px; background: var(--warn-bg); color: var(--warn); }
  .sec { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 26px; padding: 20px 24px 22px; }
  .sec-head { display: flex; align-items: baseline; gap: 14px; padding-bottom: 9px; margin-bottom: 14px; }
  .sec-num { font-size: 12px; font-weight: 600; color: var(--good); letter-spacing: .04em; }
  .sec-tag { font-size: 10.5px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  .tiles, .kpi-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin: 4px 0 20px; }
  .tile, .kpi-cell { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 1px 2px rgba(0,0,0,.05); padding: 13px 13px 12px; min-height: 140px; display: flex; flex-direction: column; justify-content: space-between; }
  /* Precomputed hex blends, not color-mix() — this stylesheet feeds the PDF
     export path (html2canvas can't parse color-mix at all, not just oklab;
     see PDF_COLOR_MIX_FALLBACKS above), so every tint here is a plain sRGB
     blend of the same token/percentage pairs computed ahead of time. */
  .kpi-cell:nth-child(5n+1) { background: linear-gradient(135deg in srgb, #bdd4f0, var(--surface)); }
  .kpi-cell:nth-child(5n+2) { background: linear-gradient(135deg in srgb, #bad4ba, var(--surface)); }
  .kpi-cell:nth-child(5n+3) { background: linear-gradient(135deg in srgb, #f8dace, var(--surface)); }
  .kpi-cell:nth-child(5n+4) { background: linear-gradient(135deg in srgb, #fbe9c0, var(--surface)); }
  .kpi-cell:nth-child(5n+5) { background: linear-gradient(135deg in srgb, #c2d2e6, var(--surface)); }
  .kpi-cell:nth-child(5n+1) .k { color: var(--accent); }
  .kpi-cell:nth-child(5n+2) .k { color: var(--good); }
  .kpi-cell:nth-child(5n+3) .k { color: var(--serious); }
  .kpi-cell:nth-child(5n+4) .k { color: #be8816; }
  .kpi-cell:nth-child(5n+5) .k { color: #1e4c85; }
  .kpi-cell .k { font-weight: 700; }
  .k, .tile-label { font-size: 10px; letter-spacing: .11em; color: var(--muted); text-transform: uppercase; line-height: 1.35; }
  .v, .tile-value { font-size: 20px; font-weight: 600; letter-spacing: -.02em; margin: 6px 0 2px; }
  .d, .tile-sub { margin-top: 4px; font-size: 11.5px; font-weight: 500; color: var(--ink2); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .narr { border: 1px solid var(--good); border-left: 5px solid var(--good); background: var(--surface); padding: 16px 20px; margin-top: 4px; }
  .narr-h { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
  .narr-h span { font-size: 10.5px; letter-spacing: .13em; text-transform: uppercase; color: var(--good); font-weight: 600; }
  .narr p { margin: 0 0 10px; font-size: 14px; line-height: 1.6; text-align: justify; }
  .narr p:last-child { margin-bottom: 0; }
  .narr b { font-weight: 600; }
  .score-pill { font-size: 10.5px; font-weight: 600; letter-spacing: .04em; padding: 3px 9px; border-radius: 2px; }
  .score-good { background: var(--good-bg); color: var(--good); }
  .score-warn { background: var(--warn-bg); color: var(--warn); }
  .bar-cell { position: relative; background: var(--surface); border: 1px solid var(--border); border-radius: 2px; height: 18px; min-width: 90px; }
  .bar-fill { position: absolute; inset: 0 auto 0 0; background: #86b6ef; border-radius: 2px; }
  .bar-label { position: relative; z-index: 1; font-size: 11px; font-weight: 700; padding: 0 6px; line-height: 18px; color: var(--ink); }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 4px; }
  /* A table row must never split across a PDF page boundary — a cell like
     the price-trend table's (price line + delta-% line stacked) would
     otherwise show only its top half on one page and the rest on the next,
     orphaned with no commodity name/price for context. */
  tr { break-inside: avoid; page-break-inside: avoid; }
  /* Same reasoning as tr above — a Perishables card is small/bounded (like a
     table row, not a whole .sec panel), so avoid here is low-risk and
     prevents a card's bottom rows getting orphaned without its header. */
  /* NOT .per-card/.xbox directly — those are CSS Grid *items*, and
     html2pdf's page-break mechanism works by inserting a plain block-level
     spacer <div> as a sibling to push the target down to the next page.
     Inside a grid container that spacer just becomes another grid cell
     (breaking the track layout) instead of actually pushing anything —
     verified empirically: marking the cards themselves avoid did not stop
     them splitting. .sec itself (see below) now correctly carries this same
     protection for the section as a whole — heading included — now that the
     windowWidth-vs-container-width mismatch is fixed (see the windowWidth
     option below), so a dedicated per-grid/xsplit rule is no longer needed
     on top of that; it was tried and reverted once the whole-.sec fix made
     it redundant (and it had its own problem regardless: it moved the grid
     but left the section heading behind on the prior page). */
  th { text-align: left; color: #fff; background: var(--ink); font-weight: 600; font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; vertical-align: bottom; padding: 8px 9px; }
  td { padding: 7px 9px; border-bottom: 1px solid var(--gridline); }
  .num { text-align: right; }
  th.num { text-align: right; }
  tbody tr:nth-child(even) td { background: #FAFBF9; }
  .footnote { color: var(--ink2); font-size: 11.5px; margin-top: 8px; line-height: 1.5; }
  .panel-subheading { font-size: 13px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--ink2); margin: 22px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--gridline); }
  .donut-wrap { display: grid; grid-template-columns: 220px 1fr; gap: 24px; align-items: center; margin-top: 4px; }
  .donut-chart { width: 200px; height: 200px; border-radius: 50%; position: relative; }
  .donut-hole { position: absolute; inset: 44px; border-radius: 50%; background: var(--surface); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .donut-hhi { font-size: 22px; font-weight: 700; }
  .donut-hhi-label { font-size: 9.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-top: 3px; }
  .donut-legend { list-style: none; margin: 0; padding: 0; font-size: 12.5px; }
  .donut-legend li { display: flex; align-items: center; gap: 9px; padding: 5px 0; border-bottom: 1px solid var(--gridline); }
  .donut-legend li:last-child { border-bottom: none; }
  .donut-swatch { width: 11px; height: 11px; flex-shrink: 0; border-radius: 2px; display: inline-block; }
  .donut-legend-name { flex: 1; }
  .donut-legend-value { font-weight: 600; }
  @media (max-width: 640px) { .donut-wrap { grid-template-columns: 1fr; justify-items: center; } }
  .section-highlight { background: var(--good-bg); border-left: 4px solid var(--good); padding: 12px 15px; font-size: 14.5px; font-weight: 450; line-height: 1.5; margin: 8px 0 16px; }
  .definition-box { margin-top: 12px; padding: 10px 14px; background: var(--page); border: 1px solid var(--border); font-size: 12px; }
  .definition-row { margin-bottom: 6px; color: var(--ink2); }
  .definition-row strong { color: var(--ink); margin-right: 6px; }
  ul { padding-left: 20px; margin: 0; }
  li { margin-bottom: 6px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .diverging-chart { display: flex; flex-direction: column; gap: 6px; margin-top: 4px; }
  .diverging-row { display: grid; grid-template-columns: 140px 1fr 70px 108px; align-items: center; gap: 10px; font-size: 13px; break-inside: avoid; page-break-inside: avoid; }
  .diverging-label { text-align: right; color: var(--ink); font-weight: 600; }
  .diverging-track { position: relative; height: 16px; }
  .diverging-mid { position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; background: var(--muted); }
  .diverging-bar { position: absolute; top: 2px; bottom: 2px; border-radius: 2px; }
  .delta-good-bg { background: var(--good2); }
  .delta-bad-bg { background: var(--bad); }
  .diverging-value { font-size: 12px; font-weight: 600; }
  .diverging-price { font-size: 12px; font-weight: 600; color: var(--ink); text-align: right; }
  .gauge { flex: 0 0 200px; text-align: center; }
  .gauge-svg { width: 100%; height: auto; }
  .gauge-track { fill: none; stroke: var(--gridline); stroke-width: 14; stroke-linecap: round; }
  .gauge-fill { fill: none; stroke: var(--good); stroke-width: 14; stroke-linecap: round; }
  .gauge-value { font-size: 26px; font-weight: 600; margin-top: -28px; }
  .gauge-label { font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .12em; margin-top: 2px; }
  .compliance-layout { display: flex; align-items: center; gap: 24px; flex-wrap: wrap; margin-top: 12px; }
  .compliance-plot { display: flex; align-items: stretch; gap: 8px; flex: 1; min-width: 280px; }
  .compliance-y-axis-label { writing-mode: vertical-rl; transform: rotate(180deg); font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; white-space: nowrap; padding: 8px 0; }
  .compliance-plot-body { display: flex; flex: 1; gap: 8px; }
  .compliance-y-ticks { display: flex; flex-direction: column; justify-content: space-between; height: 160px; padding-top: 8px; font-size: 10px; color: var(--muted); text-align: right; }
  .compliance-chart { position: relative; display: flex; align-items: flex-end; gap: 16px; height: 160px; padding-top: 8px; flex: 1; border-left: 1px solid var(--ink); border-bottom: 1px solid var(--ink); }
  .compliance-gridline { position: absolute; left: 0; right: 0; border-top: 1px solid var(--gridline); }
  .compliance-col { position: relative; z-index: 1; flex: 1; display: flex; flex-direction: column; align-items: center; height: 100%; }
  .compliance-bar-track { flex: 1; width: 100%; display: flex; align-items: flex-end; }
  .compliance-bar-fill { width: 100%; border-radius: 0; min-height: 2px; }
  .compliance-count { margin-top: 6px; font-size: 12.5px; font-weight: 600; }
  .compliance-band-label { margin-top: 2px; font-size: 10px; color: var(--muted); text-align: center; }
  .compliance-x-axis-label { margin-top: 6px; margin-left: 34px; font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; text-align: center; }
  .status-critical { background: var(--bad); }
  .status-serious { background: var(--serious); }
  .status-warning { background: var(--warn); }
  .status-good-muted { background: var(--good-bg); }
  .status-good { background: var(--good2); }
  .per-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 4px; }
  @media (max-width: 960px) { .per-grid { grid-template-columns: repeat(2, 1fr); } }
  .per-card { border: 2px solid var(--border); padding: 12px 14px; }
  .per-card.action { border-color: #a62f2f; border-top: 4px solid var(--bad); }
  .per-card.watch { border-color: #bc8513; border-top: 4px solid var(--warn); }
  .per-card.normal { border-color: #0a820a; border-top: 4px solid var(--good); }
  .per-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 600; }
  .per-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--gridline); font-size: 12px; }
  .per-row:last-of-type { border-bottom: none; }
  .per-row .l { color: var(--muted); }
  .per-row .v { font-weight: 500; }
  .xsplit { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; margin-top: 4px; }
  .xbox { border: 1px solid var(--border); padding: 14px 16px; }
  .xbox.partial { border-top: 4px solid var(--accent); }
  .xbox.non { border-top: 4px solid var(--bad); }
  .xbox.nil { border-top: 4px solid var(--muted); }
  .xbox .def { font-size: 11.5px; color: var(--muted); margin: 0 0 10px; }
  .xbig { font-size: 28px; font-weight: 600; }
  .xbox.non .xbig { color: var(--bad); }
  .xbox.nil .xbig { color: var(--muted); }
  .alert-counts { display: flex; gap: 12px; margin: 4px 0 16px; flex-wrap: wrap; }
  .ac { flex: 1; min-width: 130px; border: 1px solid var(--border); padding: 10px 12px; display: flex; align-items: baseline; gap: 8px; }
  .ac .n { font-size: 22px; font-weight: 600; }
  .ac .l { font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .ac.c { border-left: 5px solid var(--bad); } .ac.c .n { color: var(--bad); }
  .ac.h { border-left: 5px solid var(--warn); } .ac.h .n { color: var(--warn); }
  .ac.w { border-left: 5px solid var(--accent); } .ac.w .n { color: var(--accent); }
  .band-chart { position: relative; display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
  .band-gridlines { position: absolute; left: 120px; right: 80px; top: 0; bottom: 20px; pointer-events: none; }
  .band-gridline { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--gridline); }
  .band-axis { position: relative; height: 14px; margin: 4px 80px 0 120px; }
  .band-axis-tick { position: absolute; transform: translateX(-50%); font-size: 10px; color: var(--muted); white-space: nowrap; }
  .band-axis-tick:first-child { transform: translateX(0); }
  .band-axis-tick:last-child { transform: translateX(-100%); }
  /* Same reasoning as tr elsewhere in this stylesheet — a single commodity's
     price-band row is small/bounded, so protecting it from being sliced in
     half at a page boundary is safe (unlike a whole .sec, which can be
     taller than one page and may still need to split SOMEWHERE — this just
     makes sure that split never lands mid-row). */
  .band-row { display: grid; grid-template-columns: 110px 1fr 70px; align-items: center; gap: 10px; font-size: 12px; break-inside: avoid; page-break-inside: avoid; }
  .band-label { text-align: right; color: var(--ink2); }
  .band-track { position: relative; height: 12px; }
  .band-range { position: absolute; top: 5px; height: 2.5px; background: var(--accent); opacity: .35; }
  .band-cap { position: absolute; top: 2px; width: 2px; height: 10px; background: var(--accent); opacity: .6; }
  .band-mod { position: absolute; top: 1px; width: 4px; height: 12px; border-radius: 1px; background: var(--accent); }
  .band-value { font-weight: 600; }
  .lineage { background: var(--ink); color: #C9D3CD; margin: 0 0 16px; border-radius: 10px; padding: 22px 30px; font-size: 10.5px; line-height: 1.9; }
  .lineage h4 { color: #fff; }
  .lineage .lg { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 30px; }
  .lineage .lg-full { grid-column: 1 / -1; }
  .lineage b { color: #fff; font-weight: 500; }
  .disclaim { margin: 0 0 16px; border-radius: 10px; padding: 16px 30px; background: var(--warn-bg); border-top: 3px solid var(--warn); font-size: 11.5px; color: var(--ink); line-height: 1.55; }
  .disclaim b { display: block; letter-spacing: .08em; text-transform: uppercase; font-size: 10.5px; margin-bottom: 4px; }
  .hindi { direction: ltr; margin-top: 8px; }
  /* Thresholds deliberately below 735 (the PDF/iframe capture's fixed
     canvas width — see windowWidth in the html2pdf options below) so these
     mobile-narrow-screen fallbacks never trigger there and only apply when
     someone opens the raw "Download as HTML" file on an actually small
     screen. */
  @media (max-width: 700px) { .tiles, .kpi-grid { grid-template-columns: repeat(2, 1fr); } .xsplit, .per-grid, .two-col, .alert-counts { grid-template-columns: 1fr; } }
  /* A section that doesn't fit in the remaining page space moves whole onto
     the next page rather than splitting mid-table/mid-chart. Applies outside
     any @media print block on purpose — the html2pdf/html2canvas capture
     path renders in a normal screen context, not an actual print-media
     emulation, so a rule scoped to @media print would silently never apply
     to the PDF export (only to a literal browser print of this HTML). */
  /* .sec deliberately NOT included here (tried it, reverted). Once the
     windowWidth-vs-container-width mismatch was fixed elsewhere in this
     file, avoiding a whole .sec split DID work correctly — but "correctly"
     means moving the ENTIRE next section to a fresh page the moment it
     doesn't fit the remaining space, however much space that is. For a
     mid-size section (Reporting exceptions, Market participation, etc.)
     that routinely leaves a large, awkward-looking blank gap at the bottom
     of the previous page — confirmed the actual cause of a real complaint
     ("so much gap between Perishables and Market participation"). Natural
     flow (a section's heading sitting near a page bottom with its body
     continuing on the next page, same as an article in a magazine) reads
     far better than that wasted whitespace, so .sec relies on natural flow
     here; mast/cov/lineage keep the protection since they're small, bounded
     blocks unlikely to leave a big gap even when it fires. */
  .mast, .cov, .lineage { break-inside: avoid; page-break-inside: avoid; }
  /* Every section starts on its own page (except the first, which stays
     right after the masthead/coverage bar rather than leaving a near-empty
     leading page). This was tried once before and reverted for producing
     near-full-page blank gaps — but that was BEFORE windowWidth (below) was
     fixed to match the container's actual natural width; the gap was a
     symptom of that mismatch (html2pdf's break padding was computed against
     a layout different from what actually got rendered), not a flaw in
     forced breaks themselves. With the widths aligned, this is reliable. */
  .sec:not(:first-of-type) { break-before: page; page-break-before: always; }
  @media print {
    * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    body { background: #fff; }
    /* Force the fixed layouts below regardless of the print viewport width
       the browser reports — a narrow print preview would otherwise collapse
       these to fewer columns via the responsive rules above. */
    .per-grid { grid-template-columns: repeat(3, 1fr) !important; }
    .xsplit { grid-template-columns: repeat(3, 1fr) !important; }
  }
`;

/** Builds a self-contained HTML document (inline CSS, no external assets)
 * mirroring the full report — masthead, coverage bar, every numbered
 * section, and the lineage/disclaimer footer — so the downloaded file (or
 * the print/PDF path, which reuses this exact document) is accurate offline
 * and doesn't depend on this app being open. */
export function buildReportHtml(factSheet, briefEn, briefHi) {
  const title = `Weekly Market Intelligence Summary — Madhya Pradesh — ${formatDateRange(factSheet.week_start, factSheet.week_end)}`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>${escapeHtml(title)}</title>
<style>${STYLE}</style>
</head>
<body>
  ${mastHtml(factSheet)}
  ${coverageHtml(factSheet)}

  <section class="sec">
    ${sectionHead("01", "State position at a glance", "KPIs + narrative")}
    ${kpiGridHtml(factSheet)}
    ${narrativeHtml(briefEn, factSheet.narration_meta?.en)}
  </section>

  ${topCommoditiesHtml(factSheet.top_commodities)}
  ${priceBandsHtml(factSheet.price_bands)}
  ${priceTrendHtml(factSheet.price_trend, factSheet.top_commodities?.total_commodities_traded)}
  ${priceMovementHtml(factSheet.price_change)}
  ${perishablesHtml(factSheet.perishables)}
  ${marketComplianceHtml(factSheet.market_compliance)}
  ${reportingExceptionsHtml(factSheet.reporting_exceptions)}
  ${alertRegisterHtml(factSheet.alerts)}
  ${actionPointsHtml(factSheet.action_points)}

  <section class="sec hindi">
    ${sectionHead("11", "कार्यकारी नैरेटिव (हिन्दी)", "Hindi")}
    ${narrativeHtml(briefHi, factSheet.narration_meta?.hi)}
  </section>

  ${lineageHtml(factSheet)}
</body>
</html>`;
}

/** "wr" = weekly report. Keyed off generated_at (not the week range) so the
 * filename reflects when the report was produced, filesystem-safe (date-only,
 * no colons/slashes from a full timestamp). */
function reportFileBase(factSheet) {
  const generatedDate = factSheet.generated_at ? factSheet.generated_at.slice(0, 10) : factSheet.week_end;
  return `mp_agmarknet_wr_${generatedDate}`;
}

export function downloadReportHtml(factSheet, briefEn, briefHi) {
  const html = buildReportHtml(factSheet, briefEn, briefHi);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${reportFileBase(factSheet)}.html`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** "Download as PDF" — no PDF-generation dependency is added; instead this
 * opens the same self-contained report HTML in a new tab and triggers the
 * browser's native print dialog (Save as PDF), relying on the print
 * stylesheet above (color-adjust:exact, break-inside:avoid) to preserve the
 * report's colors and section spacing in the output. This is the most
 * reliable cross-browser path without a new npm dependency. */
export function openReportForPrint(factSheet, briefEn, briefHi) {
  const html = buildReportHtml(factSheet, briefEn, briefHi);
  const win = window.open("", "_blank");
  if (!win) {
    alert("Pop-up blocked — allow pop-ups for this site to download as PDF.");
    return;
  }
  win.document.open();
  win.document.write(html);
  win.document.close();
  // Chromium/Firefox print-to-PDF suggest document.title as the save
  // filename — set it to the desired report filename (browser appends .pdf).
  win.document.title = reportFileBase(factSheet);
  win.addEventListener("load", () => {
    win.focus();
    win.print();
  });
  // Some browsers fire 'load' before styles paint; a short fallback timer
  // covers that without depending on any print-specific browser API.
  setTimeout(() => {
    win.focus();
    win.print();
  }, 400);
}

// html2canvas (1.4.x) predates the CSS Color 4 spec and throws on any
// computed color function it can't parse. Confirmed via direct testing that
// this fires even for colors we never authored as oklab/color-mix — per the
// CSS Color 4 spec, color-mix() is a *computed*-value-time function (not
// resolved to rgb until paint time), so getComputedStyle() can return the
// literal "oklab(...)"/"color-mix(...)" text for browser-internal defaults
// (recent Chrome's default outline color, or its default gradient
// interpolation space) even though nothing we wrote uses those functions.
// Fix: walk every computed property on every cloned element and round-trip
// any oklab/oklch/lab/lch/color-mix/color() substring found through a canvas
// 2D pixel read — verified this Chrome's fillStyle *getter* re-serializes as
// oklab too (a naive fillStyle set/get round-trip is a no-op), so the only
// representation it can't turn back into oklab is raw decoded pixel bytes.
function fixUnsupportedColorFunctions(clonedDoc) {
  const view = clonedDoc.defaultView || window;
  const probeCanvas = document.createElement("canvas");
  probeCanvas.width = 1;
  probeCanvas.height = 1;
  const probe = probeCanvas.getContext("2d", { willReadFrequently: true });
  // "color(" (bare, no dash) matches the CSS Color 4 color() function (e.g.
  // "color(srgb 1 0 0)") without also matching "color-mix(" — that
  // alternative is listed separately and still needs its own dedicated match.
  const HAS_COLOR_FN = /(?:oklab|oklch|lab|lch|color-mix|color)\(/i;
  const COLOR_FN = /(?:oklab|oklch|lab|lch|color-mix|color)\((?:[^()]|\([^()]*\))*\)/gi;
  const resolveOne = (match) => {
    try {
      probe.clearRect(0, 0, 1, 1);
      probe.fillStyle = match;
      probe.fillRect(0, 0, 1, 1);
      const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
      return a === 255 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${(a / 255).toFixed(3)})`;
    } catch {
      return "rgb(0,0,0)";
    }
  };
  clonedDoc.querySelectorAll("*").forEach((el) => {
    el.style.outline = "none";
    el.style.caretColor = "transparent";
    const cs = view.getComputedStyle(el);
    for (let i = 0; i < cs.length; i++) {
      const prop = cs[i];
      const value = cs.getPropertyValue(prop);
      if (value && HAS_COLOR_FN.test(value)) {
        try {
          el.style.setProperty(prop, value.replace(COLOR_FN, resolveOne));
        } catch {
          /* non-settable computed property (e.g. an SVG geometry property)
             — leave it, it's not a color source anyway */
        }
      }
    }
  });
}

// A4 in points (jsPDF's "a4" format), and the page margin around every
// placed image — kept in sync with PDF_CAPTURE_WIDTH_PX below.
const PDF_PAGE_WIDTH_PT = 595.28;
const PDF_PAGE_HEIGHT_PT = 841.89;
const PDF_MARGIN_PT = { top: 24, right: 22, bottom: 24, left: 22 };
// The capture width every group below renders at — must match body's own
// max-width in STYLE (735px) so nothing reflows between what's authored and
// what's captured. Not derived from the PDF margins the way it once was:
// this function no longer depends on html2pdf's own page-size math at all.
const PDF_CAPTURE_WIDTH_PX = 735;
// Elements that must never be sliced in half across a page boundary — a
// table row or KPI tile cut mid-box reads as broken/missing data. Anything
// NOT in this list (e.g. a whole .sec) is allowed to split, since forcing an
// oversized block whole onto one page is what produced ~half-page blank
// gaps in earlier testing (see the removed break-before approach).
const PDF_UNSPLITTABLE_SELECTOR = "tr, .band-row, .diverging-row, .per-card, .kpi-cell, .xbox";

/** Slice a tall canvas into page-height chunks, nudging each cut point
 * earlier so it never lands inside an unsplittable element's own bounding
 * box (measured from the live DOM before capture, in the same coordinate
 * space the capture used — no separate "measure now, render later at a
 * different width" step, which is what let earlier approaches drift). */
function computeSliceBoundaries(wrapperEl, canvasHeightPx, pageHeightPx, scale) {
  const wrapperTop = wrapperEl.getBoundingClientRect().top;
  const protectedRanges = Array.from(wrapperEl.querySelectorAll(PDF_UNSPLITTABLE_SELECTOR)).map((el) => {
    const r = el.getBoundingClientRect();
    return { top: (r.top - wrapperTop) * scale, bottom: (r.bottom - wrapperTop) * scale };
  });
  const boundaries = [];
  let cursor = 0;
  while (cursor < canvasHeightPx) {
    let cut = Math.min(cursor + pageHeightPx, canvasHeightPx);
    if (cut < canvasHeightPx) {
      const hit = protectedRanges.find((r) => cut > r.top && cut < r.bottom);
      if (hit && hit.top > cursor) cut = hit.top;
    }
    boundaries.push(cut);
    cursor = cut;
  }
  return boundaries;
}

/** Render one "page group" (an array of sibling elements meant to flow
 * together, e.g. [masthead, coverage bar, first section]) to its own
 * canvas, then add it to the PDF as one or more pages. */
async function addGroupToPdf(pdf, html2canvas, contentDoc, wrapper, isFirstPageOverall) {
  const canvas = await html2canvas(wrapper, {
    scale: 2,
    useCORS: true,
    backgroundColor: "#ffffff",
    windowWidth: PDF_CAPTURE_WIDTH_PX,
    onclone: fixUnsupportedColorFunctions,
  });

  const usableWidthPt = PDF_PAGE_WIDTH_PT - PDF_MARGIN_PT.left - PDF_MARGIN_PT.right;
  const usableHeightPt = PDF_PAGE_HEIGHT_PT - PDF_MARGIN_PT.top - PDF_MARGIN_PT.bottom;
  const pxPerPt = canvas.width / usableWidthPt;
  const pageHeightPx = Math.floor(usableHeightPt * pxPerPt);

  const boundaries = computeSliceBoundaries(wrapper, canvas.height, pageHeightPx, canvas.width / PDF_CAPTURE_WIDTH_PX);

  let sliceTop = 0;
  for (let i = 0; i < boundaries.length; i++) {
    const sliceBottom = boundaries[i];
    const sliceHeightPx = sliceBottom - sliceTop;
    if (sliceHeightPx <= 0) {
      sliceTop = sliceBottom;
      continue;
    }
    const sliceCanvas = document.createElement("canvas");
    sliceCanvas.width = canvas.width;
    sliceCanvas.height = sliceHeightPx;
    sliceCanvas.getContext("2d").drawImage(canvas, 0, sliceTop, canvas.width, sliceHeightPx, 0, 0, canvas.width, sliceHeightPx);

    if (!(isFirstPageOverall && i === 0)) pdf.addPage();
    const sliceHeightPt = sliceHeightPx / pxPerPt;
    pdf.addImage(sliceCanvas.toDataURL("image/jpeg", 0.95), "JPEG", PDF_MARGIN_PT.left, PDF_MARGIN_PT.top, usableWidthPt, sliceHeightPt);
    sliceTop = sliceBottom;
  }
}

/** "Download as PDF" — true one-click auto-download (no print-dialog
 * interaction). Renders the report HTML into an off-screen iframe, then
 * captures and places each "page group" — masthead+coverage+first section
 * together, then each subsequent numbered section on its own, then the
 * lineage/disclaimer footer — as its own independent html2canvas capture,
 * placed on its own PDF page(s) via jsPDF directly.
 *
 * This replaced an earlier html2pdf.js-based implementation that rendered
 * the WHOLE document as one tall canvas and relied on html2pdf's own
 * pre-render DOM padding (toContainer()'s pagebreak plugin) to align section
 * boundaries with page boundaries. That padding is computed from
 * jsPDF's point-based page math converted at a fixed 96dpi, entirely
 * separate from the arithmetic that later slices the real canvas into pages
 * — the two calculations only ever agreed to within about a pixel per
 * page, and that tiny per-page error compounded across many sections in a
 * real-sized report into a highly visible near-half-page blank gap before
 * some sections (confirmed via multiple rounds of screenshot testing on the
 * full 442-market-yard dataset — a small test dataset never showed enough
 * cumulative drift to reproduce it). Capturing each section independently
 * and placing it on a guaranteed-fresh page removes that whole class of bug
 * by construction: there is no multi-section canvas for drift to accumulate
 * across, and no separate measure-then-render-at-a-different-width step for
 * the two calculations to disagree about. */
export function downloadReportPdf(factSheet, briefEn, briefHi) {
  const html = buildReportHtml(factSheet, briefEn, briefHi);
  const iframe = document.createElement("iframe");
  iframe.style.position = "fixed";
  iframe.style.left = "-99999px";
  iframe.style.top = "0";
  iframe.style.width = `${PDF_CAPTURE_WIDTH_PX}px`;
  iframe.style.height = "0";
  iframe.setAttribute("aria-hidden", "true");
  document.body.appendChild(iframe);

  const cleanup = () => {
    if (iframe.parentNode) document.body.removeChild(iframe);
  };

  iframe.onload = () => {
    const contentDoc = iframe.contentDocument;
    const body = contentDoc?.body;
    if (!body) {
      cleanup();
      alert("Could not prepare the PDF — please try \"Download as HTML\" instead.");
      return;
    }

    Promise.all([import("jspdf"), import("html2canvas")])
      .then(async ([jsPDFMod, html2canvasMod]) => {
        const jsPDF = jsPDFMod.jsPDF || jsPDFMod.default;
        const html2canvas = html2canvasMod.default || html2canvasMod;
        if (typeof jsPDF !== "function" || typeof html2canvas !== "function") {
          throw new Error("PDF libraries loaded but no callable export was found");
        }

        const secs = Array.from(body.querySelectorAll("section.sec"));
        const lineageEl = body.querySelector(".lineage");
        const disclaimEl = body.querySelector(".disclaim");
        const groups = [
          [body.querySelector(".mast"), body.querySelector(".cov"), secs[0]].filter(Boolean),
          ...secs.slice(1).map((el) => [el]),
          [lineageEl, disclaimEl].filter(Boolean),
        ].filter((g) => g.length > 0);

        const pdf = new jsPDF({ unit: "pt", format: "a4", orientation: "portrait" });

        for (let i = 0; i < groups.length; i++) {
          const wrapper = contentDoc.createElement("div");
          wrapper.style.width = `${PDF_CAPTURE_WIDTH_PX}px`;
          groups[i].forEach((el) => wrapper.appendChild(el));
          body.appendChild(wrapper);
          await addGroupToPdf(pdf, html2canvas, contentDoc, wrapper, i === 0);
        }

        pdf.save(`${reportFileBase(factSheet)}.pdf`);
      })
      .catch((err) => {
        console.error("PDF generation failed:", err);
        alert(`PDF generation failed — please try "Download as HTML" instead.\n(${err?.message || err})`);
      })
      .finally(cleanup);
  };
  iframe.srcdoc = html;
}

// Backward-compatible alias.
export const downloadReport = downloadReportHtml;
