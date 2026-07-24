const BAND_TOKENS = {
  "0 days": "seq-100",
  "1-2 days": "seq-250",
  "3-4 days": "seq-350",
  "5-6 days": "seq-450",
  "7 days": "seq-650",
};

export default function MarketCompliance({ marketCompliance: mc }) {
  const maxCount = Math.max(...mc.compliance_bands.map((b) => b.market_count), 1);

  return (
    <section className="panel">
      <h2 className="panel-title">Market reporting compliance</h2>
      <p className="panel-subtitle">
        {mc.markets_reporting_at_least_once} of {mc.markets_in_roster} registered market yards reported at least
        once this week.
      </p>
      <div className="compliance-chart">
        {mc.compliance_bands.map((b) => (
          <div className="compliance-col" key={b.band}>
            <div className="compliance-bar-track">
              <div
                className="compliance-bar-fill"
                style={{
                  height: `${(b.market_count / maxCount) * 100}%`,
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
      <p className="panel-footnote">{mc.roster_caveat}</p>
    </section>
  );
}
