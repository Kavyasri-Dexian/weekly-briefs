import SectionHeading from "./SectionHeading.jsx";

const COUNT_CLASS = { Critical: "c", High: "h", Watch: "w" };

/** Simple deterministic rules engine, computed entirely in pipeline.py's
 * compute_alerts from numbers already published elsewhere in the fact sheet
 * (price-move thresholds, the perishables distress composite, non-reporting
 * share) — never MSP-based, since MSP data isn't fetched by this pipeline. */
export default function AlertRegister({ alerts }) {
  if (!alerts) return null;
  const { alerts: rows, counts } = alerts;

  return (
    <section className="panel">
      <SectionHeading n="09" title="Alert register" tag="Rules engine" />
      <div className="alert-counts">
        <div className="ac c"><span className="n tabular">{counts.Critical}</span><span className="l">Critical</span></div>
        <div className="ac h"><span className="n tabular">{counts.High}</span><span className="l">High</span></div>
        <div className="ac w"><span className="n tabular">{counts.Watch}</span><span className="l">Watch</span></div>
      </div>
      {rows.length ? (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Type</th>
                <th>Entity affected</th>
                <th>Trigger</th>
                <th>Owner</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a, i) => (
                <tr key={i}>
                  <td><span className={`sev sev-${a.severity}`}>{a.severity}</span></td>
                  <td>{a.type}</td>
                  <td>{a.entity}</td>
                  <td>{a.trigger}</td>
                  <td style={{ color: "var(--text-muted)" }}>{a.owner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="panel-empty">No alerts triggered this week under the current threshold rules.</p>
      )}
      <p className="panel-footnote">
        Severity is assigned by fixed business rule (price-move and non-reporting thresholds, and the
        perishables distress composite) — never by the narrative engine.
      </p>
    </section>
  );
}
