import { formatDate, formatDateRange } from "./formatDate.js";

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
  const map = { ok: ["var(--chip-ok-bg)", "var(--good)"], watch: ["var(--chip-watch-bg)", "var(--ink)"], act: ["var(--chip-act-bg)", "var(--bad)"], na: ["var(--gridline)", "var(--muted)"] };
  const [bg, fg] = map[kind] || map.na;
  return `<span style="display:inline-block;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;padding:2px 6px;border-radius:3px;background:${bg};color:${fg}">${escapeHtml(label)}</span>`;
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
    <span>Completeness <b>${cov.completeness_pct}%</b> &mdash; ${mc.markets_reporting_at_least_once} of ${mc.markets_in_roster} active market yards reported at least one day</span>
    <span>Records processed <b>${cov.records_processed.toLocaleString()}</b></span>
    <span>Missing modal price <b>${cov.records_missing_price.toLocaleString()}</b></span>
  </div>`;
}

function kpiGridHtml(fs) {
  const oa = fs.overall_arrivals, mc = fs.market_compliance, tc = fs.top_commodities, pc = fs.price_change, alerts = fs.alerts;
  const top = tc.top_commodities[0];
  const compliancePct = mc.markets_in_roster ? (mc.markets_reporting_at_least_once / mc.markets_in_roster) * 100 : null;
  const topGainer = pc?.available ? pc.top_gainers[0] : null;
  const topDecliner = pc?.available ? pc.top_decliners[0] : null;
  const openAlerts = alerts ? alerts.counts.Critical + alerts.counts.High + alerts.counts.Watch : null;
  const tiles = [
    ["Total arrival", `${oa.total_arrivals.toLocaleString()} tonnes`, deltaSpan(oa.wow_pct_change)],
    ["Market yards reporting", `${mc.markets_reporting_at_least_once} / ${mc.markets_in_roster}`, `${mc.markets_not_reporting} non-reporting`],
    ["State compliance score", compliancePct != null ? `${compliancePct.toFixed(1)}%` : "—", ""],
    ["Commodities traded", tc.total_commodities_traded, ""],
    ["Top commodity by arrival", top ? top.commodity : "—", top ? `${top.arrival_value.toLocaleString()} tonnes` : ""],
    ["Largest price gain", topGainer ? topGainer.commodity : "—", topGainer ? deltaSpan(topGainer.pct_change) : chip("na", "n/a")],
    ["Largest price fall", topDecliner ? topDecliner.commodity : "—", topDecliner ? deltaSpan(topDecliner.pct_change) : chip("na", "n/a")],
    ["Open alerts", openAlerts ?? "—", alerts ? `${alerts.counts.Critical} Critical &middot; ${alerts.counts.High} High` : ""],
    ["Top reporting market", mc.top_reporting_market ?? "—", mc.top_reporting_market_days != null ? `${mc.top_reporting_market_days}/7 days` : ""],
    ["Markets reporting 5-6 days", mc.markets_reporting_5_to_6_days, `${mc.markets_reporting_all_7_days} at 7/7 days`],
  ];
  return `<div class="kpi-grid">${tiles.map(([label, value, sub]) => `
    <div class="kpi-cell">
      <span class="k">${escapeHtml(label)}</span>
      <span class="v">${escapeHtml(String(value))}</span>
      <span class="d">${sub}</span>
    </div>`).join("")}</div>`;
}

function narrativeHtml(text, meta) {
  const paragraphs = text.split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean).slice(1);
  const body = paragraphs.length ? paragraphs : text.split(/\n\s*\n/).filter(Boolean);
  const badge = meta?.accuracy_pct != null
    ? `<span class="score-pill">${meta.accuracy_pct}% numbers verified</span>`
    : "";
  return `
    <div class="narr">
      <div class="narr-h"><span>Executive Narrative</span>${badge}</div>
      ${body.map((p) => `<p>${boldNumbers(p)}</p>`).join("")}
    </div>`;
}

function topCommoditiesHtml(tc) {
  const rows = tc.top_commodities.map((r) => `
    <tr>
      <td>${escapeHtml(r.commodity)}</td>
      <td class="num">${r.arrival_value.toLocaleString()}</td>
      <td class="num">${r.share_pct_of_state_arrivals != null ? r.share_pct_of_state_arrivals + "%" : "—"}</td>
      <td class="num">${r.markets_trading}</td>
      <td class="num">${(r.modal_price_weighted ?? r.modal_price_mean) != null ? "Rs " + (r.modal_price_weighted ?? r.modal_price_mean).toLocaleString() : "—"}</td>
      <td class="num">${r.wow_arrival_pct_change == null ? '<span style="color:var(--muted)">n/a</span>' : deltaSpan(r.wow_arrival_pct_change)}</td>
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
      <thead><tr><th>Commodity</th><th class="num">Arrivals</th><th class="num">Share</th><th class="num">Markets</th><th class="num">Modal price</th><th class="num">WoW arrivals</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="footnote">Ranked by ${escapeHtml(rankingBasisLabel(tc.ranking_basis))}. ${tc.total_commodities_traded} commodities traded this week in total.</p>
    ${donutHtml(tc.donut_slices, tc.concentration_hhi)}
  </section>`;
}

const DONUT_COLORS = ["#1F5C3D", "#2E7D52", "#4E9670", "#1B3A5C", "#3D6489", "#B8791C", "#D0A054", "#A8321E", "#C9CFC7"];

function hhiLabel(hhi) {
  if (hhi < 0.15) return "Low concentration";
  if (hhi < 0.25) return "Moderate concentration";
  return "High concentration";
}

function donutHtml(slices, hhi) {
  if (!slices?.length) return "";
  let cumulative = 0;
  const stops = slices.map((s, i) => {
    const pct = s.share_pct_of_state_arrivals ?? 0;
    const start = cumulative;
    cumulative += pct;
    return `${DONUT_COLORS[i % DONUT_COLORS.length]} ${start}% ${cumulative}%`;
  }).join(", ");
  const legend = slices.map((s, i) => `
    <li><span class="donut-swatch" style="background:${DONUT_COLORS[i % DONUT_COLORS.length]}"></span>
      <span class="donut-legend-name">${escapeHtml(s.commodity)}</span>
      <span class="donut-legend-value">${s.share_pct_of_state_arrivals != null ? s.share_pct_of_state_arrivals + "%" : "—"}</span>
    </li>`).join("");
  return `
    <h3 class="panel-subheading">Share of state arrival</h3>
    <div class="donut-wrap">
      <div class="donut-chart" style="background:conic-gradient(${stops})">
        <div class="donut-hole">
          ${hhi != null ? `<span class="donut-hhi">${hhi}</span><span class="donut-hhi-label">HHI &middot; ${hhiLabel(hhi)}</span>` : ""}
        </div>
      </div>
      <ul class="donut-legend">${legend}</ul>
    </div>
    <p class="footnote">Concentration is measured by the Herfindahl&ndash;Hirschman Index over all commodities' arrival shares, not just those shown above.</p>`;
}

function priceBandsHtml(bands) {
  if (!bands?.length) return "";
  const globalMax = Math.max(...bands.map((b) => b.max_price), 1);
  const rows = bands.map((b) => {
    const minPct = (b.min_price / globalMax) * 100;
    const maxPct = (b.max_price / globalMax) * 100;
    const modPct = b.modal_price != null ? (b.modal_price / globalMax) * 100 : null;
    return `<div class="band-row">
      <div class="band-label">${escapeHtml(b.commodity)}</div>
      <div class="band-track" title="${escapeHtml(b.commodity)}: min Rs ${b.min_price.toLocaleString()} · max Rs ${b.max_price.toLocaleString()} per quintal">
        <div class="band-range" style="left:${minPct}%;width:${maxPct - minPct}%"></div>
        ${modPct != null ? `<div class="band-mod" style="left:${modPct}%"></div>` : ""}
      </div>
      <div class="band-value">${b.modal_price != null ? "Rs " + b.modal_price.toLocaleString() : "—"}</div>
    </div>`;
  }).join("");
  return `<section class="sec">
    ${sectionHead("03", "Price levels and bands", "Weekly range")}
    <div class="band-chart">${rows}</div>
    <p class="footnote">Bar ends = weekly minimum and maximum reported price. Marker = arrival-weighted modal price. Rupees per quintal.</p>
  </section>`;
}

function priceTrendHtml(pt) {
  if (!pt?.commodities?.length) return "";
  const cell = (p) => p.avg_price == null
    ? '<span style="color:var(--muted)">n/a</span>'
    : `Rs ${p.avg_price.toLocaleString()}<br/>${deltaSpan(p.pct_change_vs_this_week)}`;
  const rows = pt.commodities.map((c) => `
    <tr>
      <td>${escapeHtml(c.commodity)}</td>
      <td class="num">Rs ${c.this_week_avg_price.toLocaleString()}</td>
      <td class="num">${cell(c.last_week)}</td>
      <td class="num">${cell(c.last_month_same_week)}</td>
      <td class="num">${cell(c.last_year_same_week)}</td>
    </tr>`).join("");
  return `<section class="sec">
    ${sectionHead("04", "Price trends and comparisons", "vs prior periods")}
    <table>
      <thead><tr><th>Commodity</th><th class="num">This week avg</th><th class="num">Last week</th><th class="num">Same week last month</th><th class="num">Same week last year</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </section>`;
}

function priceMovementHtml(pc) {
  const inner = !pc?.available
    ? `<p class="footnote">Not available this week (${escapeHtml(pc?.reason ?? "no prior-week data")}).</p>`
    : (() => {
        const row = (r) => `<li>${escapeHtml(r.commodity)}: ${deltaSpan(r.pct_change)} <strong>Rs ${r.current_modal_price.toLocaleString()}</strong> (from Rs ${r.prior_modal_price.toLocaleString()})</li>`;
        const topGainer = pc.top_gainers[0], topDecliner = pc.top_decliners[0];
        const parts = [];
        if (topGainer) parts.push(`${escapeHtml(topGainer.commodity)} gained ${Math.abs(topGainer.pct_change)} per cent`);
        if (topDecliner) parts.push(`${escapeHtml(topDecliner.commodity)} declined ${Math.abs(topDecliner.pct_change)} per cent`);
        const highlight = parts.length ? `<div class="section-highlight">${parts.join(" and ")} against the previous week.</div>` : "";
        return `${highlight}
        <div class="two-col">
          <div><strong>Gainers</strong><ul>${pc.top_gainers.map(row).join("") || "<li>None</li>"}</ul></div>
          <div><strong>Decliners</strong><ul>${pc.top_decliners.map(row).join("") || "<li>None</li>"}</ul></div>
        </div>`;
      })();
  return `<section class="sec">
    ${sectionHead("05", "Price movement — gainers and decliners", "Week on week")}
    ${inner}
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
      <div class="per-row"><span class="l">Arrival</span><span class="v">${p.arrival_value.toLocaleString()} qtl</span></div>
      <div class="per-row"><span class="l">Arrival WoW</span><span class="v">${deltaSpan(p.arrival_wow_pct_change)}</span></div>
      <div class="per-row"><span class="l">Modal price</span><span class="v">${p.modal_price != null ? "Rs " + p.modal_price.toLocaleString() : "—"}</span></div>
      <div class="per-row"><span class="l">Price WoW</span><span class="v">${deltaSpan(p.price_wow_pct_change)}</span></div>
    </div>`).join("");
  return `<section class="sec">
    ${sectionHead("06", "Perishables and consumer watch", "Distress composite")}
    ${highlight}
    <div class="per-grid">${cards}</div>
    <p class="footnote">The distress composite flag is raised only when an arrival surge (WoW &ge; 15%) and a price fall (WoW &le; -15%) occur together in the same commodity and week.</p>
  </section>`;
}

function marketComplianceHtml(mc) {
  const parts = [];
  if (mc.markets_reporting_all_7_days) parts.push(`${mc.markets_reporting_all_7_days} market yards reported on all seven days`);
  if (mc.markets_reporting_5_to_6_days) parts.push(`${mc.markets_reporting_5_to_6_days} reported on five or six days`);
  let highlight = parts.join(" and ");
  highlight += mc.markets_not_reporting ? `, while ${mc.markets_not_reporting} yards filed no return at all.` : ".";
  return `<section class="sec">
    ${sectionHead("07", "Market participation and reporting compliance", "Coverage")}
    <p class="footnote">${mc.markets_reporting_at_least_once} of ${mc.markets_in_roster} registered market yards reported at least once this week.</p>
    <div class="section-highlight">${escapeHtml(highlight)}</div>
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
        <span class="xbig">${rx.partial_reporting_market_yards}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
      <div class="xbox non">
        <h4>Non-reporting</h4>
        <p class="def">Filed no return of any kind for the full reporting week.</p>
        <span class="xbig">${rx.non_reporting_market_yards}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
      <div class="xbox nil">
        <h4>Nil transactions reported</h4>
        <p class="def">A return declaring zero arrival for the week (compliant, distinct from not reporting).</p>
        <span class="xbig">${rx.nil_transactions_reported}</span> <span style="font-size:12px;color:var(--muted)">market yards</span>
      </div>
    </div>
    <p class="footnote">${escapeHtml(rx.note)}</p>
    <p class="footnote">${escapeHtml(rx.nil_transactions_note)}</p>
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
      <div class="ac c"><span class="n">${counts.Critical}</span><span class="l">Critical</span></div>
      <div class="ac h"><span class="n">${counts.High}</span><span class="l">High</span></div>
      <div class="ac w"><span class="n">${counts.Watch}</span><span class="l">Watch</span></div>
    </div>
    ${table}
    <p class="footnote">Severity is assigned by fixed business rule — never by the narrative engine.</p>
  </section>`;
}

function sevChip(sev) {
  const map = { Critical: ["var(--bad)", "#fff"], High: ["var(--warn)", "#1a1a19"], Watch: ["var(--gridline)", "var(--muted)"] };
  const [bg, fg] = map[sev] || map.Watch;
  return `<span style="display:inline-block;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;font-weight:700;padding:3px 7px;border-radius:3px;background:${bg};color:${fg}">${escapeHtml(sev)}</span>`;
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
          <td class="num">${escapeHtml(formatDate(a.target_date))}</td>
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
      <div>Source &nbsp;<b>${escapeHtml(fs.source ?? "agmarknet.gov.in")}</b></div>
      <div>Generated &nbsp;<b>${escapeHtml(fs.generated_at ?? "—")}</b></div>
      <div>Records processed &nbsp;<b>${cov?.records_processed?.toLocaleString() ?? "—"}</b></div>
      <div>Missing modal price &nbsp;<b>${cov?.records_missing_price?.toLocaleString() ?? "—"}</b></div>
      <div>Numeric grounding (EN) &nbsp;<b>${fs.narration_meta?.en?.accuracy_pct ?? "—"}% verified</b></div>
      <div>Numeric grounding (HI) &nbsp;<b>${fs.narration_meta?.hi?.accuracy_pct ?? "—"}% verified</b></div>
    </div>
  </div>
  <div class="disclaim">
    <b>Data source and generation</b>
    Every figure in this report is computed deterministically from the current week's raw Agmarknet 2.0 pull.
    The executive narrative is generated only from this fact sheet's own values and is machine-validated for
    numeric grounding before publication; when the check fails, a fixed, guaranteed-accurate template is
    published instead.
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
    --gridline:#e1e0d9; --border:rgba(11,11,11,.12); --good:#006300; --bad:#d03b3b;
    --accent:#2a78d6; --warn:#fab219; --chip-ok-bg:#cdeccd; --chip-watch-bg:#fde9c4;
    --chip-act-bg:#f6d3d3;
  }
  * { box-sizing: border-box; }
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: var(--ink); background: var(--page); max-width: 900px; margin: 0 auto; padding: 24px 20px 64px; }
  h1 { font-size: 24px; margin: 6px 0 2px; }
  h1 em { font-style: normal; display: block; font-size: 14px; font-weight: 500; color: var(--ink2); margin-top: 4px; }
  h2 { font-size: 17px; margin: 0; flex: 1; }
  h4 { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; margin: 0 0 10px; }
  .mast { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px 24px 16px; margin-bottom: 16px; }
  .mast-eyebrow { font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
  .mast-period { display: flex; gap: 20px; flex-wrap: wrap; margin-top: 14px; padding-top: 12px; border-top: 1px solid var(--border); }
  .mp-item .k { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); display: block; }
  .mp-item .v { font-size: 14px; font-weight: 600; }
  .cov { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin: 0 0 20px; padding: 11px 20px; display: flex; gap: 20px; flex-wrap: wrap; align-items: center; font-size: 12.5px; color: var(--ink2); }
  .cov-badge { font-size: 10.5px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; padding: 3px 9px; border-radius: 999px; background: var(--chip-watch-bg); color: var(--ink); }
  .sec { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 18px; padding: 20px 24px 22px; }
  .sec-head { display: flex; align-items: baseline; gap: 12px; border-bottom: 2px solid var(--ink); padding-bottom: 8px; margin-bottom: 14px; }
  .sec-num { font-size: 12px; font-weight: 700; color: var(--accent); }
  .sec-tag { font-size: 10px; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
  .tiles, .kpi-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 1px; background: var(--border); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 4px 0 20px; }
  .tile, .kpi-cell { background: var(--surface); padding: 12px 13px 11px; min-height: 92px; display: flex; flex-direction: column; justify-content: space-between; }
  .kpi-cell:nth-child(5n+1) { background: linear-gradient(135deg, color-mix(in oklab, var(--accent) 7%, var(--surface)), var(--surface)); }
  .kpi-cell:nth-child(5n+2) { background: linear-gradient(135deg, color-mix(in oklab, var(--good) 6%, var(--surface)), var(--surface)); }
  .kpi-cell:nth-child(5n+3) { background: linear-gradient(135deg, color-mix(in oklab, var(--bad) 5%, var(--surface)), var(--surface)); }
  .kpi-cell:nth-child(5n+4) { background: linear-gradient(135deg, color-mix(in oklab, var(--accent) 4%, var(--surface)), var(--surface)); }
  .kpi-cell:nth-child(5n+5) { background: linear-gradient(135deg, color-mix(in oklab, var(--warn) 6%, var(--surface)), var(--surface)); }
  .k, .tile-label { font-size: 10px; letter-spacing: .08em; color: var(--muted); text-transform: uppercase; margin-bottom: 6px; }
  .v, .tile-value { font-size: 19px; font-weight: 700; }
  .d, .tile-sub { margin-top: 4px; font-size: 12px; color: var(--ink2); display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .narr { border: 1px solid var(--accent); border-left: 5px solid var(--accent); background: var(--surface); border-radius: 6px; padding: 16px 20px; margin-top: 4px; }
  .narr-h { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
  .narr-h span { font-size: 10.5px; letter-spacing: .1em; text-transform: uppercase; color: var(--accent); font-weight: 700; }
  .narr p { margin: 0 0 10px; font-size: 14px; line-height: 1.6; }
  .narr p:last-child { margin-bottom: 0; }
  .narr b { font-weight: 700; }
  .score-pill { font-size: 11px; font-weight: 700; padding: 3px 9px; border-radius: 999px; background: var(--chip-ok-bg); color: var(--good); }
  table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 4px; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: 10.5px; text-transform: uppercase; border-bottom: 1px solid var(--gridline); padding: 6px 9px; }
  td { padding: 7px 9px; border-bottom: 1px solid var(--gridline); }
  .num { text-align: right; }
  .footnote { color: var(--muted); font-size: 11.5px; margin-top: 8px; }
  .panel-subheading { font-size: 13px; font-weight: 700; letter-spacing: .03em; text-transform: uppercase; color: var(--ink2); margin: 22px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--gridline); }
  .donut-wrap { display: grid; grid-template-columns: 220px 1fr; gap: 24px; align-items: center; margin-top: 4px; }
  .donut-chart { width: 200px; height: 200px; border-radius: 50%; position: relative; }
  .donut-hole { position: absolute; inset: 30px; border-radius: 50%; background: var(--surface); display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
  .donut-hhi { font-size: 22px; font-weight: 700; }
  .donut-hhi-label { font-size: 9.5px; letter-spacing: .06em; text-transform: uppercase; color: var(--muted); margin-top: 3px; }
  .donut-legend { list-style: none; margin: 0; padding: 0; font-size: 12.5px; }
  .donut-legend li { display: flex; align-items: center; gap: 9px; padding: 5px 0; border-bottom: 1px solid var(--gridline); }
  .donut-legend li:last-child { border-bottom: none; }
  .donut-swatch { width: 11px; height: 11px; flex-shrink: 0; border-radius: 2px; display: inline-block; }
  .donut-legend-name { flex: 1; }
  .donut-legend-value { font-weight: 600; }
  @media (max-width: 640px) { .donut-wrap { grid-template-columns: 1fr; justify-items: center; } }
  .section-highlight { background: color-mix(in oklab, var(--good) 12%, var(--surface)); border-left: 3px solid var(--good); border-radius: 4px; padding: 10px 14px; font-size: 13px; margin: 8px 0 14px; }
  .definition-box { margin-top: 12px; padding: 10px 14px; background: var(--page); border: 1px solid var(--border); border-radius: 6px; font-size: 12px; }
  .definition-row { margin-bottom: 6px; color: var(--ink2); }
  .definition-row strong { color: var(--ink); margin-right: 6px; }
  ul { padding-left: 20px; margin: 0; }
  li { margin-bottom: 6px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .per-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-top: 4px; }
  .per-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; }
  .per-card.action { border-top: 4px solid var(--bad); }
  .per-card.watch { border-top: 4px solid var(--warn); }
  .per-card.normal { border-top: 4px solid var(--good); }
  .per-h { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; font-weight: 700; }
  .per-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--gridline); font-size: 12px; }
  .per-row .l { color: var(--muted); }
  .xsplit { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; margin-top: 4px; }
  .xbox { border: 1px solid var(--border); border-radius: 8px; padding: 14px 16px; }
  .xbox.partial { border-top: 4px solid var(--accent); }
  .xbox.non { border-top: 4px solid var(--bad); }
  .xbox.nil { border-top: 4px solid var(--muted); }
  .xbox .def { font-size: 11.5px; color: var(--muted); margin: 0 0 10px; }
  .xbig { font-size: 28px; font-weight: 700; }
  .xbox.non .xbig { color: var(--bad); }
  .xbox.nil .xbig { color: var(--muted); }
  .alert-counts { display: flex; gap: 12px; margin: 4px 0 16px; flex-wrap: wrap; }
  .ac { flex: 1; min-width: 130px; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; display: flex; align-items: baseline; gap: 8px; }
  .ac .n { font-size: 22px; font-weight: 700; }
  .ac .l { font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  .ac.c { border-left: 5px solid var(--bad); } .ac.c .n { color: var(--bad); }
  .ac.h { border-left: 5px solid var(--warn); }
  .ac.w { border-left: 5px solid var(--accent); } .ac.w .n { color: var(--accent); }
  .band-chart { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
  .band-row { display: grid; grid-template-columns: 110px 1fr 70px; align-items: center; gap: 10px; font-size: 12px; }
  .band-label { text-align: right; color: var(--ink2); }
  .band-track { position: relative; height: 12px; background: var(--gridline); border-radius: 2px; }
  .band-range { position: absolute; top: 5px; height: 2px; background: var(--accent); opacity: .6; }
  .band-mod { position: absolute; top: 1px; width: 3px; height: 10px; background: var(--accent); }
  .band-value { font-weight: 600; }
  .lineage { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 18px 22px; margin-top: 20px; font-size: 11px; line-height: 1.9; color: var(--ink2); }
  .lineage .lg { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 30px; }
  .lineage b { color: var(--ink); }
  .disclaim { margin-top: 12px; padding: 14px 18px; background: var(--chip-watch-bg); border: 1px solid var(--border); border-left: 3px solid var(--warn); border-radius: 6px; font-size: 11.5px; color: var(--ink); line-height: 1.55; }
  .disclaim b { display: block; letter-spacing: .06em; text-transform: uppercase; font-size: 10.5px; margin-bottom: 4px; }
  .hindi { direction: ltr; margin-top: 8px; }
  @media (max-width: 820px) { .tiles, .kpi-grid { grid-template-columns: repeat(2, 1fr); } .xsplit, .per-grid, .two-col, .alert-counts { grid-template-columns: 1fr; } }
  @media print {
    * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    body { background: #fff; }
    /* A section that doesn't fit in the remaining page space moves whole
       onto the next page rather than splitting mid-table/mid-chart. */
    .sec, .mast, .cov, .lineage { break-inside: avoid; page-break-inside: avoid; }
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
  ${priceTrendHtml(factSheet.price_trend)}
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

export function downloadReportHtml(factSheet, briefEn, briefHi) {
  const html = buildReportHtml(factSheet, briefEn, briefHi);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `madhya_pradesh_weekly_report_${factSheet.week_start}_to_${factSheet.week_end}.html`;
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

// Backward-compatible alias.
export const downloadReport = downloadReportHtml;
