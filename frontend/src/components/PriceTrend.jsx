import SectionHeading from "./SectionHeading.jsx";

function DeltaCell({ period }) {
  if (period.avg_price == null) {
    return <span className="delta delta-muted">n/a</span>;
  }
  const pct = period.pct_change_vs_this_week;
  return (
    <div>
      <div className="tabular">Rs {period.avg_price.toLocaleString()}</div>
      {pct == null ? (
        <span className="delta delta-muted">n/a</span>
      ) : (
        <span className={`delta ${pct >= 0 ? "delta-good" : "delta-bad"}`}>
          {pct >= 0 ? "▲" : "▼"} {Math.abs(pct)}%
        </span>
      )}
    </div>
  );
}

export default function PriceTrend({ priceTrend }) {
  if (!priceTrend?.commodities?.length) return null;

  return (
    <section className="panel">
      <SectionHeading n="04" title="Price trends and comparisons" tag="vs prior periods" />
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Commodity</th>
              <th className="num">This week avg</th>
              <th className="num">Last week</th>
              <th className="num">Same week last month</th>
              <th className="num">Same week last year</th>
            </tr>
          </thead>
          <tbody>
            {priceTrend.commodities.map((c) => (
              <tr key={c.commodity}>
                <td>{c.commodity}</td>
                <td className="num tabular">Rs {c.this_week_avg_price.toLocaleString()}</td>
                <td className="num">
                  <DeltaCell period={c.last_week} />
                </td>
                <td className="num">
                  <DeltaCell period={c.last_month_same_week} />
                </td>
                <td className="num">
                  <DeltaCell period={c.last_year_same_week} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
