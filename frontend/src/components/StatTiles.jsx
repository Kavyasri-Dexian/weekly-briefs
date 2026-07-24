function Delta({ pct, chip }) {
  const body =
    pct === null || pct === undefined ? (
      <span className="delta delta-muted">n/a</span>
    ) : (
      <span className={`delta ${pct >= 0 ? "delta-good" : "delta-bad"}`}>
        {pct >= 0 ? "▲" : "▼"} {Math.abs(pct)}% WoW
      </span>
    );
  return (
    <span className="d">
      {body}
      {chip}
    </span>
  );
}

function Chip({ kind, children }) {
  return <span className={`chip chip-${kind}`}>{children}</span>;
}

/** KPI tile grid — "state position at a glance" (reference section 01). Only
 * includes figures the pipeline actually computes; the reference's seasonal-
 * norm index and MSP-linked tiles are omitted rather than fabricated (no
 * 3-year baseline or MSP data is fetched by this pipeline). */
export default function StatTiles({ factSheet }) {
  const oa = factSheet.overall_arrivals;
  const mc = factSheet.market_compliance;
  const tc = factSheet.top_commodities;
  const pc = factSheet.price_change;
  const alerts = factSheet.alerts;
  const top = tc.top_commodities[0];
  const unit = oa.total_arrivals_basis === "arrival_qty" ? " tonnes" : " (quote count)";
  const compliancePct = mc.markets_in_roster
    ? (mc.markets_reporting_at_least_once / mc.markets_in_roster) * 100
    : null;
  const topGainer = pc?.available ? pc.top_gainers[0] : null;
  const topDecliner = pc?.available ? pc.top_decliners[0] : null;
  const openAlerts = alerts ? alerts.counts.Critical + alerts.counts.High + alerts.counts.Watch : null;

  const tiles = [
    {
      label: "Total arrival",
      value: oa.total_arrivals.toLocaleString() + unit,
      delta: <Delta pct={oa.wow_pct_change} />,
    },
    {
      label: "Market yards reporting",
      value: `${mc.markets_reporting_at_least_once} / ${mc.markets_in_roster}`,
      sub: `${mc.markets_not_reporting} non-reporting`,
      chip: mc.markets_not_reporting > 0 ? <Chip kind="act">Action</Chip> : <Chip kind="ok">Normal</Chip>,
    },
    {
      label: "State compliance score",
      value: compliancePct != null ? `${compliancePct.toFixed(1)}%` : "—",
      chip: compliancePct != null && compliancePct < 85 ? <Chip kind="watch">Watch</Chip> : <Chip kind="ok">Normal</Chip>,
    },
    {
      label: "Commodities traded",
      value: tc.total_commodities_traded,
    },
    {
      label: "Top commodity by arrival",
      value: top ? top.commodity : "—",
      sub: top
        ? `${top.arrival_value.toLocaleString()} tonnes${top.share_pct_of_state_arrivals != null ? ` · ${top.share_pct_of_state_arrivals}%` : ""}`
        : null,
    },
    {
      label: "Largest price gain",
      value: topGainer ? topGainer.commodity : "—",
      sub: topGainer ? `Rs ${topGainer.current_modal_price.toLocaleString()}` : null,
      chip: topGainer ? <Chip kind="watch">▲ {topGainer.pct_change}%</Chip> : <Chip kind="na">n/a</Chip>,
    },
    {
      label: "Largest price fall",
      value: topDecliner ? topDecliner.commodity : "—",
      sub: topDecliner ? `Rs ${topDecliner.current_modal_price.toLocaleString()}` : null,
      chip: topDecliner ? <Chip kind="act">▼ {topDecliner.pct_change}%</Chip> : <Chip kind="na">n/a</Chip>,
    },
    {
      label: "Open alerts",
      value: openAlerts != null ? openAlerts : "—",
      sub: alerts ? `${alerts.counts.Critical} Critical · ${alerts.counts.High} High` : null,
      chip: alerts && alerts.counts.Critical > 0 ? <Chip kind="act">Action</Chip> : <Chip kind="ok">Normal</Chip>,
    },
    {
      label: "Top reporting market",
      value: mc.top_reporting_market ?? "—",
      sub: mc.top_reporting_market_days != null ? `${mc.top_reporting_market_days}/7 days` : null,
    },
    {
      label: "Markets reporting 5-6 days",
      value: mc.markets_reporting_5_to_6_days,
      sub: `${mc.markets_reporting_all_7_days} at 7/7 days`,
    },
  ];

  return (
    <div className="kpi-grid">
      {tiles.map((t) => (
        <div className="kpi-cell" key={t.label}>
          <span className="k">{t.label}</span>
          <span className="v tabular">{t.value}</span>
          <span className="d">
            {t.delta}
            {t.sub ? <span className="delta delta-muted">{t.sub}</span> : null}
            {t.chip}
          </span>
        </div>
      ))}
    </div>
  );
}
