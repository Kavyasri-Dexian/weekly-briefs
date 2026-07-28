import { useState } from "react";
import SectionHeading from "./SectionHeading.jsx";

const PAGE_SIZE = 5;

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

export default function PriceTrend({ priceTrend, totalCommoditiesTraded }) {
  const [page, setPage] = useState(0);
  if (!priceTrend?.commodities?.length) return null;
  const shown = priceTrend.commodities.length;
  const pageCount = Math.ceil(shown / PAGE_SIZE);
  const clampedPage = Math.min(page, pageCount - 1);
  const pageRows = priceTrend.commodities.slice(clampedPage * PAGE_SIZE, clampedPage * PAGE_SIZE + PAGE_SIZE);

  return (
    <section className="panel">
      <SectionHeading n="04" title="Price trends and comparisons" tag="vs prior periods" />
      <div className="table-scroll">
        <table className="data-table price-trend-table">
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
            {pageRows.map((c) => (
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
      {pageCount > 1 ? (
        <div className="pagination">
          <button
            type="button"
            className="pagination-btn"
            onClick={() => setPage((p) => Math.max(0, p - 1))}
            disabled={clampedPage === 0}
          >
            ← Previous
          </button>
          <span className="pagination-status tabular">
            {clampedPage * PAGE_SIZE + 1}–{Math.min(shown, clampedPage * PAGE_SIZE + PAGE_SIZE)} of {shown}
          </span>
          <button
            type="button"
            className="pagination-btn"
            onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
            disabled={clampedPage >= pageCount - 1}
          >
            Next →
          </button>
        </div>
      ) : null}
      <p className="panel-footnote">
        {totalCommoditiesTraded != null ? (
          <>
            Showing {shown} of {totalCommoditiesTraded} commodities traded this week
            <span className="footnote-sep">·</span>
          </>
        ) : null}
        All prices in Rs/quintal.
      </p>
    </section>
  );
}
