import SectionHeading from "./SectionHeading.jsx";

/** Weekly min/max price range + arrival-weighted modal marker per commodity
 * — a simplified div/CSS rendering of the reference design's SVG price-band
 * chart (avoids adding an SVG-layout engine for a report that already has
 * several bar-based charts using the same div/CSS approach). */
export default function PriceBands({ priceBands }) {
  if (!priceBands?.length) return null;
  const globalMax = Math.max(...priceBands.map((b) => b.max_price), 1);
  const widest = [...priceBands].sort((a, b) => (b.max_price - b.min_price) / b.min_price - (a.max_price - a.min_price) / a.min_price)[0];
  const spreadRatio = widest ? (widest.max_price / widest.min_price).toFixed(1) : null;

  return (
    <section className="panel">
      <SectionHeading n="03" title="Price levels and bands" tag="Weekly range" />
      {widest ? (
        <div className="section-highlight">
          The widest price band this week was {widest.commodity}, from Rs {widest.min_price.toLocaleString()} to
          Rs {widest.max_price.toLocaleString()} per quintal, a spread of {spreadRatio}&times; the minimum.
        </div>
      ) : null}
      <div className="band-chart">
        {priceBands.map((b) => {
          const minPct = (b.min_price / globalMax) * 100;
          const maxPct = (b.max_price / globalMax) * 100;
          const modPct = b.modal_price != null ? (b.modal_price / globalMax) * 100 : null;
          return (
            <div className="band-row" key={b.commodity}>
              <div className="band-label">{b.commodity}</div>
              <div
                className="band-track"
                title={`${b.commodity}: min Rs ${b.min_price.toLocaleString()} · max Rs ${b.max_price.toLocaleString()} per quintal`}
              >
                <div className="band-range" style={{ left: `${minPct}%`, width: `${maxPct - minPct}%` }} />
                <div className="band-cap" style={{ left: `${minPct}%` }} />
                <div className="band-cap" style={{ left: `${maxPct}%` }} />
                {modPct != null ? <div className="band-mod" style={{ left: `${modPct}%` }} /> : null}
              </div>
              <div className="band-value tabular">
                {b.modal_price != null ? `Rs ${b.modal_price.toLocaleString()}` : "—"}
              </div>
            </div>
          );
        })}
      </div>
      <p className="panel-footnote">
        Bar ends = weekly minimum and maximum reported price. Marker = arrival-weighted modal price. Rupees per quintal.
      </p>
    </section>
  );
}
