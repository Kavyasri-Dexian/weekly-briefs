import SectionHeading from "./SectionHeading.jsx";

const BAND_STATUS = {
  "0 days": "critical",
  "1-2 days": "serious",
  "3-4 days": "warning",
  "5-6 days": "good-muted",
  "7 days": "good",
};

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const step = magnitude / 2;
  return Math.ceil(value / step) * step;
}

function Gauge({ pct }) {
  const r = 70;
  const circumference = Math.PI * r;
  const filled = Math.max(0, Math.min(100, pct)) / 100 * circumference;
  return (
    <div className="gauge">
      <svg viewBox="0 0 170 95" className="gauge-svg">
        <path d="M 15 90 A 70 70 0 0 1 155 90" className="gauge-track" />
        <path
          d="M 15 90 A 70 70 0 0 1 155 90"
          className="gauge-fill"
          style={{ strokeDasharray: `${filled} ${circumference}` }}
        />
      </svg>
      <div className="gauge-value tabular">{pct.toFixed(1)}%</div>
      <div className="gauge-label">Market yards reporting</div>
    </div>
  );
}

function sectionHighlight(mc) {
  const parts = [];
  if (mc.markets_reporting_all_7_days) {
    parts.push(`${mc.markets_reporting_all_7_days} market yards reported on all seven days`);
  }
  if (mc.markets_reporting_5_to_6_days) {
    parts.push(`${mc.markets_reporting_5_to_6_days} reported on five or six days`);
  }
  let sentence = parts.join(" and ");
  if (mc.markets_not_reporting) {
    sentence += `, while ${mc.markets_not_reporting} yards filed no return at all.`;
  } else {
    sentence += ".";
  }
  return sentence;
}

export default function MarketCompliance({ marketCompliance: mc }) {
  const rawMax = Math.max(...mc.compliance_bands.map((b) => b.market_count), 1);
  const axisMax = niceMax(rawMax);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(axisMax * f));
  const reportingPct = (mc.markets_reporting_at_least_once / mc.markets_in_roster) * 100;

  return (
    <section className="panel">
      <SectionHeading n="07" title="Market participation and reporting compliance" tag="Coverage" />
      <p className="panel-subtitle">
        {mc.markets_reporting_at_least_once} of {mc.markets_in_roster} registered market yards reported at least
        once this week.
      </p>
      <div className="section-highlight">{sectionHighlight(mc)}</div>
      <div className="compliance-layout">
        <Gauge pct={reportingPct} />
        <div className="compliance-plot">
          <div className="compliance-y-axis-label">Number of market yards</div>
          <div className="compliance-plot-body">
            <div className="compliance-y-ticks">
              {[...ticks].reverse().map((t) => (
                <div className="compliance-y-tick" key={t}>
                  {t}
                </div>
              ))}
            </div>
            <div className="compliance-chart">
              {[...ticks].reverse().map((t) => (
                <div
                  key={t}
                  className="compliance-gridline"
                  style={{ bottom: `${(t / axisMax) * 100}%` }}
                />
              ))}
              {mc.compliance_bands.map((b) => (
                <div className="compliance-col" key={b.band}>
                  <div className="compliance-bar-track">
                    <div
                      className={`compliance-bar-fill status-${BAND_STATUS[b.band]}`}
                      style={{ height: `${(b.market_count / axisMax) * 100}%` }}
                      title={`${b.band}: ${b.market_count} markets`}
                    />
                  </div>
                  <div className="compliance-count tabular">{b.market_count}</div>
                  <div className="compliance-band-label">{b.band}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
      <div className="compliance-x-axis-label">Reporting days (out of the 7-day week)</div>
      <p className="panel-footnote">{mc.roster_caveat}</p>
    </section>
  );
}
