import SectionHeading from "./SectionHeading.jsx";

export default function PriceMovement({ priceChange }) {
  if (!priceChange?.available) {
    return (
      <section className="panel">
        <SectionHeading n="05" title="Price movement — gainers and decliners" tag="Week on week" />
        <p className="panel-empty">
          Not available this week ({priceChange?.reason ?? "no prior-week data loaded"}).
        </p>
      </section>
    );
  }

  const { top_gainers: gainers, top_decliners: decliners } = priceChange;
  const maxAbs = Math.max(
    ...gainers.map((g) => Math.abs(g.pct_change)),
    ...decliners.map((d) => Math.abs(d.pct_change)),
    1
  );

  // Decliners first (most negative at top), then gainers (largest at bottom) —
  // reads top-to-bottom as "worst to best", matching the reference layout.
  const rows = [...decliners].reverse().concat([...gainers].reverse());

  const topGainer = gainers[0];
  const topDecliner = decliners[0];
  const highlightParts = [];
  if (topGainer) highlightParts.push(`${topGainer.commodity} gained ${Math.abs(topGainer.pct_change)} per cent`);
  if (topDecliner) highlightParts.push(`${topDecliner.commodity} declined ${Math.abs(topDecliner.pct_change)} per cent`);
  const highlight = highlightParts.length ? `${highlightParts.join(" and ")} against the previous week.` : null;

  return (
    <section className="panel">
      <SectionHeading n="05" title="Price movement — gainers and decliners" tag="Week on week" />
      {priceChange.min_trading_days_for_ranking ? (
        <p className="panel-subtitle">
          Only commodities traded on at least {priceChange.min_trading_days_for_ranking} days in both weeks are
          eligible{priceChange.commodities_excluded_thin_trade ? ` — ${priceChange.commodities_excluded_thin_trade} excluded as thin trade` : ""}.
        </p>
      ) : null}
      {highlight ? <div className="section-highlight">{highlight}</div> : null}
      <div className="diverging-chart">
        {rows.map((r) => {
          const good = r.pct_change >= 0;
          const widthPct = (Math.abs(r.pct_change) / maxAbs) * 50;
          return (
            <div className="diverging-row" key={r.commodity}>
              <div className="diverging-label">{r.commodity}</div>
              <div className="diverging-track">
                <div className="diverging-mid" />
                <div
                  className={`diverging-bar ${good ? "delta-good-bg" : "delta-bad-bg"}`}
                  style={
                    good
                      ? { left: "50%", width: `${widthPct}%` }
                      : { right: "50%", width: `${widthPct}%` }
                  }
                  title={`${r.commodity}: ${good ? "+" : ""}${r.pct_change}% (Rs ${r.prior_modal_price.toLocaleString()} → Rs ${r.current_modal_price.toLocaleString()})`}
                />
              </div>
              <div className={`diverging-value tabular ${good ? "delta-good" : "delta-bad"}`}>
                {good ? "+" : ""}
                {r.pct_change}%
              </div>
              <div className="diverging-price tabular">Rs {r.current_modal_price.toLocaleString()}</div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
