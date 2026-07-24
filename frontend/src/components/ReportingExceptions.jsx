import SectionHeading from "./SectionHeading.jsx";

/** Partial-vs-non-reporting split — see pipeline.py's compute_reporting_
 * exceptions for why this isn't the reference design's "nil transaction vs
 * non-reporting" split: the source API returns rows only for actual
 * transactions, so a compliant zero-arrival return can't be distinguished
 * from a missing one with the data this pipeline has. */
export default function ReportingExceptions({ reportingExceptions: rx }) {
  if (!rx) return null;
  return (
    <section className="panel">
      <SectionHeading n="08" title="Reporting exceptions" tag="Compliance" />
      <div className="xsplit">
        <div className="xbox partial">
          <h4>Partial reporting</h4>
          <p className="def">Reported on at least 1 but fewer than 7 of the 7 expected days this week.</p>
          <span className="xbig tabular">{rx.partial_reporting_market_yards}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}> market yards</span>
        </div>
        <div className="xbox non">
          <h4>Non-reporting</h4>
          <p className="def">Filed no return of any kind for the full reporting week.</p>
          <span className="xbig tabular">{rx.non_reporting_market_yards}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}> market yards</span>
        </div>
        <div className="xbox nil">
          <h4>Nil transactions reported</h4>
          <p className="def">A return declaring zero arrival for the week (compliant, distinct from not reporting).</p>
          <span className="xbig tabular">{rx.nil_transactions_reported}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}> market yards</span>
        </div>
      </div>
      <p className="panel-footnote">{rx.note}</p>
      <p className="panel-footnote">{rx.nil_transactions_note}</p>
    </section>
  );
}
