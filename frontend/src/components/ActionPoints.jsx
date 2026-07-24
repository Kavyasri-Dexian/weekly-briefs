import SectionHeading from "./SectionHeading.jsx";
import { formatDate } from "../lib/formatDate.js";

/** Derived 1:1 from Critical/High alerts (see pipeline.py compute_action_
 * points) — target_date = generated_at + a fixed number of days per
 * severity, documented there. Never a separate editorial judgment call. */
export default function ActionPoints({ actionPoints }) {
  if (!actionPoints?.length) return null;

  return (
    <section className="panel">
      <SectionHeading n="10" title="Action points" tag="From alert register" />
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Priority</th>
              <th>Action</th>
              <th>Owner</th>
              <th className="num">Target</th>
            </tr>
          </thead>
          <tbody>
            {actionPoints.map((a, i) => (
              <tr key={i}>
                <td><span className={`sev sev-${a.priority}`}>{a.priority}</span></td>
                <td>{a.action}</td>
                <td style={{ color: "var(--text-muted)" }}>{a.owner}</td>
                <td className="num tabular">{formatDate(a.target_date)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="panel-footnote">
        Every action point traces to one triggered alert; target dates are generated-at plus a fixed
        number of days per severity (3 days for Critical, 7 for High).
      </p>
    </section>
  );
}
