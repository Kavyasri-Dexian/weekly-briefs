import SectionHeading from "./SectionHeading.jsx";

function rankingBasisLabel(basis) {
  if (basis === "arrival_qty") return "arrival volume (tonnes)";
  if (basis?.startsWith("price_quote_count")) return "number of price quotes (arrival volume unavailable this week)";
  return basis;
}

// Real Agmarknet MP data is overwhelmingly weight-based (arrival_unit =
// "Metric Tonnes"), with one confirmed exception found in the archived raw
// dataset: Coriander(Leaves), reported in Bundles. Hardcoded rather than
// carried through the fact sheet since the pipeline doesn't currently emit
// a per-commodity arrival_unit field — matched case-insensitively so raw
// casing differences (see display_commodity_name in pipeline.py) don't
// silently drop the flag.
const NON_WEIGHT_COMMODITIES = new Set(["coriander(leaves)", "egg", "coconut"]);
function isNonWeightCommodity(name) {
  return NON_WEIGHT_COMMODITIES.has(String(name ?? "").trim().toLowerCase());
}

// Fixed hex swatches (not theme tokens) so donut segments keep consistent
// contrast against each other regardless of light/dark mode, same rationale
// as the bar-fill colors elsewhere in this file.
const DONUT_COLORS = ["#1F5C3D", "#2E7D52", "#4E9670", "#1B3A5C", "#3D6489", "#B8791C", "#D0A054", "#A8321E", "#C9CFC7"];

function hhiLabel(hhi) {
  if (hhi == null) return null;
  if (hhi < 0.15) return "Low concentration";
  if (hhi < 0.25) return "Moderate concentration";
  return "High concentration";
}

function CommodityDonut({ slices, hhi }) {
  if (!slices?.length) return null;
  let cumulative = 0;
  const stops = slices.map((s, i) => {
    const pct = s.share_pct_of_state_arrivals ?? 0;
    const start = cumulative;
    cumulative += pct;
    return `${DONUT_COLORS[i % DONUT_COLORS.length]} ${start}% ${cumulative}%`;
  });
  return (
    <div className="donut-wrap">
      <div className="donut-chart" style={{ background: `conic-gradient(${stops.join(", ")})` }}>
        <div className="donut-hole">
          {hhi != null ? (
            <>
              <span className="donut-hhi tabular">{hhi}</span>
              <span className="donut-hhi-label">HHI · {hhiLabel(hhi)}</span>
            </>
          ) : null}
        </div>
      </div>
      <ul className="donut-legend">
        {slices.map((s, i) => (
          <li key={s.commodity}>
            <span className="donut-swatch" style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
            <span className="donut-legend-name">{s.commodity}</span>
            <span className="donut-legend-value tabular">
              {s.share_pct_of_state_arrivals != null ? `${s.share_pct_of_state_arrivals}%` : "—"}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function TopCommodities({ topCommodities }) {
  const rows = topCommodities.top_commodities;
  const maxValue = Math.max(...rows.map((r) => r.arrival_value), 1);
  const top = rows[0];
  const hasNonWeightRow = rows.some((r) => isNonWeightCommodity(r.commodity));
  const highlight = top
    ? `${top.commodity} led state arrivals at ${top.arrival_value.toLocaleString()} tonnes${
        top.share_pct_of_state_arrivals != null ? ` or ${top.share_pct_of_state_arrivals} per cent` : ""
      } of total volume.`
    : null;

  return (
    <section className="panel">
      <SectionHeading n="02" title="Commodity arrivals" tag="By arrival volume" />
      {highlight ? <div className="section-highlight">{highlight}</div> : null}
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Commodity</th>
              <th className="num">Arrivals (Quintals/Tonnes)</th>
              <th>Share</th>
              <th className="num">Markets</th>
              <th className="num">Modal price</th>
              <th className="num">WoW arrivals</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.commodity}>
                <td>{r.commodity}{isNonWeightCommodity(r.commodity) ? "*" : ""}</td>
                <td className="num tabular">{r.arrival_value.toLocaleString()}</td>
                <td>
                  <div className="bar-cell">
                    <div
                      className="bar-fill"
                      style={{ width: `${(r.arrival_value / maxValue) * 100}%` }}
                    />
                    <span className="bar-label tabular">
                      {r.share_pct_of_state_arrivals != null ? `${r.share_pct_of_state_arrivals}%` : "—"}
                    </span>
                  </div>
                </td>
                <td className="num tabular">{r.markets_trading}</td>
                <td className="num tabular">
                  {(r.modal_price_weighted ?? r.modal_price_mean) != null
                    ? `Rs ${(r.modal_price_weighted ?? r.modal_price_mean).toLocaleString()}`
                    : "—"}
                </td>
                <td className="num tabular">
                  {r.wow_arrival_pct_change == null ? (
                    <span className="delta delta-muted">n/a</span>
                  ) : (
                    <span className={`delta ${r.wow_arrival_pct_change >= 0 ? "delta-good" : "delta-bad"}`}>
                      {r.wow_arrival_pct_change >= 0 ? "▲" : "▼"} {Math.abs(r.wow_arrival_pct_change)}%
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="panel-footnote">
        Ranked by {rankingBasisLabel(topCommodities.ranking_basis)}. {topCommodities.total_commodities_traded} commodities traded this week in total.
      </p>
      {hasNonWeightRow ? (
        <p className="panel-footnote">* Not measured in Quintals/Tonnes for this commodity — reported in its own unit of sale (e.g. bundles).</p>
      ) : null}
      {topCommodities.donut_slices?.length ? (
        <>
          <h3 className="panel-subheading">Share of state arrival</h3>
          <CommodityDonut slices={topCommodities.donut_slices} hhi={topCommodities.concentration_hhi} />
          <p className="panel-footnote">
            Concentration is measured by the Herfindahl–Hirschman Index over all commodities' arrival shares, not
            just those shown above.
          </p>
        </>
      ) : null}
    </section>
  );
}
