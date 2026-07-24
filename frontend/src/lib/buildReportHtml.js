import { formatDate, formatDateRange } from "./formatDate.js";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function deltaSpan(pct, { invert = false } = {}) {
  if (pct == null) return '<span style="color:#898781">n/a</span>';
  const good = invert ? pct < 0 : pct >= 0;
  const color = good ? "#006300" : "#d03b3b";
  const arrow = pct >= 0 ? "&#9650;" : "&#9660;";
  return `<span style="color:${color};font-weight:600">${arrow} ${Math.abs(pct)}%</span>`;
}

function statTilesHtml(fs) {
  const oa = fs.overall_arrivals;
  const mc = fs.market_compliance;
  const top = fs.top_commodities.top_commodities[0];
  const unit = oa.total_arrivals_basis === "arrival_qty" ? "" : " (quote count)";
  const tiles = [
    ["Total arrivals", `${oa.total_arrivals.toLocaleString()}${unit}`, deltaSpan(oa.wow_pct_change)],
    ["Top commodity by arrival", top ? top.commodity : "—", top ? `${top.arrival_value.toLocaleString()} tonnes · ${top.share_pct_of_state_arrivals ?? "—"}% share` : ""],
    ["Market yards reporting", `${mc.markets_reporting_at_least_once} / ${mc.markets_in_roster}`, `${mc.markets_not_reporting} yards filed No Return`],
    ["Top reporting market", mc.top_reporting_market ?? "—", mc.top_reporting_market_days != null ? `${mc.top_reporting_market_days}/7 days reported` : ""],
    ["Markets reporting 5-6 days", mc.markets_reporting_5_to_6_days, `${mc.markets_reporting_all_7_days} at 7/7 days`],
  ];
  return `<div class="tiles">${tiles.map(([label, value, sub]) => `
    <div class="tile">
      <div class="tile-label">${escapeHtml(label)}</div>
      <div class="tile-value">${escapeHtml(value)}</div>
      <div class="tile-sub">${sub}</div>
    </div>`).join("")}</div>`;
}

function topCommoditiesHtml(tc) {
  const rows = tc.top_commodities.map((r) => `
    <tr>
      <td>${escapeHtml(r.commodity)}</td>
      <td class="num">${r.arrival_value.toLocaleString()}</td>
      <td class="num">${r.share_pct_of_state_arrivals != null ? r.share_pct_of_state_arrivals + "%" : "—"}</td>
      <td class="num">${r.markets_trading}</td>
      <td class="num">${(r.modal_price_weighted ?? r.modal_price_mean) != null ? "Rs " + (r.modal_price_weighted ?? r.modal_price_mean).toLocaleString() : "—"}</td>
      <td class="num">${r.wow_arrival_pct_change == null ? '<span style="color:#898781">n/a</span>' : deltaSpan(r.wow_arrival_pct_change)}</td>
    </tr>`).join("");
  return `
    <h2>Top Traded Commodities by Arrival Volume</h2>
    <table>
      <thead><tr><th>Commodity</th><th class="num">Arrivals</th><th class="num">Share</th><th class="num">Markets</th><th class="num">Modal price</th><th class="num">WoW arrivals</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="footnote">Ranked by ${escapeHtml(tc.ranking_basis)}. ${tc.total_commodities_traded} commodities traded this week in total.</p>`;
}

function priceTrendHtml(pt) {
  if (!pt?.commodities?.length) return "";
  const cell = (p) => p.avg_price == null
    ? '<span style="color:#898781">n/a</span>'
    : `Rs ${p.avg_price.toLocaleString()}<br/>${deltaSpan(p.pct_change_vs_this_week)}`;
  const rows = pt.commodities.map((c) => `
    <tr>
      <td>${escapeHtml(c.commodity)}</td>
      <td class="num">Rs ${c.this_week_avg_price.toLocaleString()}</td>
      <td class="num">${cell(c.last_week)}</td>
      <td class="num">${cell(c.last_month_same_week)}</td>
      <td class="num">${cell(c.last_year_same_week)}</td>
    </tr>`).join("");
  return `
    <h2>Price Trends & Comparisons</h2>
    <p class="footnote">
      Same week last month: ${formatDateRange(pt.last_month_same_week_range.start, pt.last_month_same_week_range.end)}
      &middot; Same week last year: ${formatDateRange(pt.last_year_same_week_range.start, pt.last_year_same_week_range.end)}
    </p>
    <table>
      <thead><tr><th>Commodity</th><th class="num">This week avg</th><th class="num">Last week</th><th class="num">Same week last month</th><th class="num">Same week last year</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function priceMovementHtml(pc) {
  if (!pc?.available) {
    return `<h2>Weekly Price Movement — Gainers & Decliners</h2><p class="footnote">Not available this week (${escapeHtml(pc?.reason ?? "no prior-week data")}).</p>`;
  }
  const row = (r) => `<li>${escapeHtml(r.commodity)}: ${deltaSpan(r.pct_change)} (Rs ${r.prior_modal_price.toLocaleString()} &rarr; Rs ${r.current_modal_price.toLocaleString()})</li>`;
  return `
    <h2>Weekly Price Movement — Gainers & Decliners</h2>
    <div class="two-col">
      <div><strong>Gainers</strong><ul>${pc.top_gainers.map(row).join("") || "<li>None</li>"}</ul></div>
      <div><strong>Decliners</strong><ul>${pc.top_decliners.map(row).join("") || "<li>None</li>"}</ul></div>
    </div>`;
}

function marketComplianceHtml(mc) {
  const rows = mc.compliance_bands.map((b) => `<tr><td>${escapeHtml(b.band)}</td><td class="num">${b.market_count}</td></tr>`).join("");
  return `
    <h2>Market Reporting Compliance</h2>
    <p class="footnote">${mc.markets_reporting_at_least_once} of ${mc.markets_in_roster} registered market yards reported at least once this week.</p>
    <table><thead><tr><th>Reporting band</th><th class="num">Markets</th></tr></thead><tbody>${rows}</tbody></table>
    <p class="footnote">${escapeHtml(mc.roster_caveat)}</p>`;
}

function narrativeHtml(label, text, meta) {
  const lines = text.split("\n").map((l) => l.trim()).filter(Boolean);
  const [lead, ...points] = lines;
  const badge = meta?.accuracy_pct != null
    ? `<p class="score-badge">
        <strong>${meta.accuracy_pct}% numbers verified</strong>
        (${meta.numbers_verified}/${meta.numbers_checked} checked &middot; ${meta.used_model ? "model draft" : "template"}${meta.used_model ? `, ${meta.attempts} attempt${meta.attempts === 1 ? "" : "s"}` : ""})
        &mdash; ${escapeHtml(meta.confidence || "")}
      </p>`
    : "";
  return `
    <h2>Executive Summary (${escapeHtml(label)})</h2>
    ${badge}
    <p class="lead">${escapeHtml(lead)}</p>
    <ul>${points.map((p) => `<li>${escapeHtml(p)}</li>`).join("")}</ul>`;
}

/** Builds a self-contained HTML document (inline CSS, no external assets)
 * capturing the full report — every section rendered in the app — so the
 * downloaded file is accurate offline and can be opened, printed, or
 * converted to PDF (browser print dialog) without depending on this app. */
export function buildReportHtml(factSheet, briefEn, briefHi) {
  const title = `Madhya Pradesh Weekly Mandi Summary — ${formatDateRange(factSheet.week_start, factSheet.week_end)}`;
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; color: #0b0b0b; max-width: 900px; margin: 0 auto; padding: 32px 20px 64px; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  h2 { font-size: 16px; margin: 32px 0 10px; border-top: 1px solid #e1e0d9; padding-top: 20px; }
  .subtitle { color: #52514e; margin: 0 0 24px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
  .tile { border: 1px solid #e1e0d9; border-radius: 8px; padding: 14px 16px; }
  .tile-label { font-size: 11px; letter-spacing: .04em; color: #898781; text-transform: uppercase; margin-bottom: 6px; }
  .tile-value { font-size: 20px; font-weight: 600; }
  .tile-sub { margin-top: 4px; font-size: 13px; color: #52514e; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: #898781; font-weight: 600; font-size: 11px; text-transform: uppercase; border-bottom: 1px solid #e1e0d9; padding: 6px 10px; }
  td { padding: 8px 10px; border-bottom: 1px solid #e1e0d9; }
  .num { text-align: right; }
  .footnote { color: #898781; font-size: 12px; }
  .score-badge { font-size: 12px; color: #52514e; background: #f0efec; border-radius: 6px; padding: 6px 10px; display: inline-block; }
  .lead { color: #eb6834; font-weight: 600; }
  ul { padding-left: 20px; }
  li { margin-bottom: 6px; }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .hindi { direction: ltr; }
  @media print { h2 { break-inside: avoid; } table { break-inside: avoid; } }
</style>
</head>
<body>
  <h1>${escapeHtml(title)}</h1>
  <p class="subtitle">Source: ${escapeHtml(factSheet.source ?? "agmarknet.gov.in")} &middot; Generated ${escapeHtml(formatDate((factSheet.generated_at || "").slice(0, 10)) || factSheet.generated_at)}</p>

  ${statTilesHtml(factSheet)}
  ${topCommoditiesHtml(factSheet.top_commodities)}
  ${priceTrendHtml(factSheet.price_trend)}
  ${priceMovementHtml(factSheet.price_change)}
  ${marketComplianceHtml(factSheet.market_compliance)}
  ${narrativeHtml("English", briefEn, factSheet.narration_meta?.en)}
  <div class="hindi">${narrativeHtml("हिन्दी", briefHi, factSheet.narration_meta?.hi)}</div>
</body>
</html>`;
}

export function downloadReport(factSheet, briefEn, briefHi) {
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
