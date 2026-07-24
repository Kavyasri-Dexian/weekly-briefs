import SectionHeading from "./SectionHeading.jsx";

const STATUS_CHIP = { action: "act", watch: "watch", normal: "ok" };
const STATUS_LABEL = { action: "Action", watch: "Watch", normal: "Normal" };

function DeltaText({ pct }) {
  if (pct == null) return <span className="delta delta-muted">n/a</span>;
  return (
    <span className={`delta ${pct >= 0 ? "delta-good" : "delta-bad"}`}>
      {pct >= 0 ? "▲" : "▼"} {Math.abs(pct)}%
    </span>
  );
}

/** Tomato/onion/potato watch cards — tracked separately from the top-10
 * arrival ranking because they drive consumer price sensitivity regardless
 * of rank. distress_composite (arrival surge + price fall together) is
 * computed in pipeline.py's compute_perishables; nothing here is derived
 * beyond what the fact sheet already carries. */
export default function Perishables({ perishables }) {
  if (!perishables?.length) return null;
  const flagged = perishables.filter((p) => p.distress_composite);

  return (
    <section className="panel">
      <SectionHeading n="06" title="Perishables and consumer watch" tag="Distress composite" />
      {flagged.length ? (
        <div className="section-highlight">
          {flagged.map((p) => `${p.commodity} arrivals ${p.arrival_wow_pct_change >= 0 ? "rose" : "fell"} ${Math.abs(p.arrival_wow_pct_change)}% while the modal price fell ${Math.abs(p.price_wow_pct_change)}%`).join("; ")}
          , satisfying the distress composite rule.
        </div>
      ) : null}
      <div className="per-grid">
        {perishables.map((p) => (
          <div className={`per-card ${p.status}`} key={p.commodity}>
            <div className="per-h">
              <span>{p.commodity}</span>
              <span className={`chip chip-${STATUS_CHIP[p.status]}`}>{STATUS_LABEL[p.status]}</span>
            </div>
            <div className="per-row">
              <span className="l">Arrival</span>
              <span className="v tabular">{p.arrival_value.toLocaleString()} qtl</span>
            </div>
            <div className="per-row">
              <span className="l">Arrival WoW</span>
              <span className="v"><DeltaText pct={p.arrival_wow_pct_change} /></span>
            </div>
            <div className="per-row">
              <span className="l">Modal price</span>
              <span className="v tabular">{p.modal_price != null ? `Rs ${p.modal_price.toLocaleString()}` : "—"}</span>
            </div>
            <div className="per-row">
              <span className="l">Price WoW</span>
              <span className="v"><DeltaText pct={p.price_wow_pct_change} /></span>
            </div>
          </div>
        ))}
      </div>
      <p className="panel-footnote">
        The distress composite flag is raised only when an arrival surge (WoW &ge; 15%) and a price fall
        (WoW &le; -15%) occur together in the same commodity and week.
      </p>
    </section>
  );
}
