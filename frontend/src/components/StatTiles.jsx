function Delta({ pct }) {
  if (pct === null || pct === undefined) {
    return <span className="delta delta-muted">n/a</span>;
  }
  const good = pct >= 0;
  return (
    <span className={`delta ${good ? "delta-good" : "delta-bad"}`}>
      {good ? "▲" : "▼"} {Math.abs(pct)}% WoW
    </span>
  );
}

export default function StatTiles({ factSheet }) {
  const oa = factSheet.overall_arrivals;
  const mc = factSheet.market_compliance;
  const tc = factSheet.top_commodities;
  const top = tc.top_commodities[0];
  const unit = oa.total_arrivals_basis === "arrival_qty" ? "" : " (quote count)";

  const tiles = [
    {
      label: "TOTAL ARRIVALS",
      value: oa.total_arrivals.toLocaleString() + unit,
      delta: <Delta pct={oa.wow_pct_change} />,
    },
    {
      label: "TOP COMMODITY BY ARRIVAL",
      value: top ? top.commodity : "—",
      sub: top ? `${top.arrival_value.toLocaleString()} · ${top.share_pct_of_state_arrivals}% share` : null,
    },
    {
      label: "MARKET YARDS REPORTING",
      value: `${mc.markets_reporting_at_least_once} / ${mc.markets_in_roster}`,
      sub: `${mc.markets_not_reporting} filed no return`,
    },
    {
      label: "TOP REPORTING MARKET",
      value: mc.top_reporting_market ?? "—",
      sub: mc.top_reporting_market_days != null ? `${mc.top_reporting_market_days} of the week` : null,
    },
    {
      label: "MARKETS REPORTING 5-6 DAYS",
      value: mc.markets_reporting_5_to_6_days,
      sub: `${mc.markets_reporting_all_7_days} reported all 7 days`,
    },
  ];

  return (
    <div className="tile-row">
      {tiles.map((t) => (
        <div className="tile" key={t.label}>
          <div className="tile-label">{t.label}</div>
          <div className="tile-value tabular">{t.value}</div>
          {t.delta ? <div className="tile-sub">{t.delta}</div> : null}
          {t.sub ? <div className="tile-sub tile-sub-muted">{t.sub}</div> : null}
        </div>
      ))}
    </div>
  );
}
