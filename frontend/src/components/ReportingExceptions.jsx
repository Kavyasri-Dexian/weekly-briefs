import SectionHeading from "./SectionHeading.jsx";

/** Reporting split is by reporting-day coverage (partial/non-reporting); nil
 * transactions reported is a separate, narrower count identified from rows
 * with an explicit arrival_qty of 0 — see pipeline.py's
 * compute_reporting_exceptions for the full derivation. */
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
          <p className="def">At least one row this week explicitly declared zero arrival quantity — compliant, and distinct from filing no return at all.</p>
          <span className="xbig tabular">{rx.nil_transactions_reported ?? 0}</span>
          <span style={{ fontSize: 12, color: "var(--text-muted)" }}> market yards</span>
        </div>
      </div>
      <p className="panel-footnote">{rx.note}</p>
      <p className="panel-footnote">{rx.nil_transactions_note}</p>
    </section>
  );
}
