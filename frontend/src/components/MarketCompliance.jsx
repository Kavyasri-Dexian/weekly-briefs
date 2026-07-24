const BAND_TOKENS = {
  "0 days": "seq-100",
  "1-2 days": "seq-250",
  "3-4 days": "seq-350",
  "5-6 days": "seq-450",
  "7 days": "seq-650",
};

function niceMax(value) {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  const step = magnitude / 2;
  return Math.ceil(value / step) * step;
}

export default function MarketCompliance({ marketCompliance: mc }) {
  const rawMax = Math.max(...mc.compliance_bands.map((b) => b.market_count), 1);
  const axisMax = niceMax(rawMax);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(axisMax * f));

  return (
    <section className="panel">
      <h2 className="panel-title">Market Reporting Compliance</h2>
      <p className="panel-subtitle">
        {mc.markets_reporting_at_least_once} of {mc.markets_in_roster} registered market yards reported at least
        once this week.
      </p>
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
                    className="compliance-bar-fill"
                    style={{
                      height: `${(b.market_count / axisMax) * 100}%`,
                      background: `var(--${BAND_TOKENS[b.band]})`,
                    }}
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
      <div className="compliance-x-axis-label">Reporting days (out of the 7-day week)</div>
      <p className="panel-footnote">{mc.roster_caveat}</p>
    </section>
  );
}
