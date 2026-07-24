export default function TopCommodities({ topCommodities }) {
  const rows = topCommodities.top_commodities;
  const maxValue = Math.max(...rows.map((r) => r.arrival_value), 1);

  return (
    <section className="panel">
      <h2 className="panel-title">Top traded commodities by arrival volume</h2>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Commodity</th>
              <th className="num">Arrivals</th>
              <th>Share</th>
              <th className="num">Markets</th>
              <th className="num">Modal price</th>
              <th className="num">WoW arrivals</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.commodity}>
                <td>{r.commodity}</td>
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
        Ranked by arrival volume ({topCommodities.ranking_basis}). {topCommodities.total_commodities_traded} commodities traded this week in total.
      </p>
    </section>
  );
}
