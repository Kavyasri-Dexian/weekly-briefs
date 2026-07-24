import { useEffect, useState, useCallback, useRef } from "react";
import { loadWeeklyBrief, refreshWeeklyBrief } from "./lib/loadData.js";
import { formatDateRange, formatDate } from "./lib/formatDate.js";
import { downloadReportHtml, openReportForPrint } from "./lib/buildReportHtml.js";
import SectionHeading from "./components/SectionHeading.jsx";
import StatTiles from "./components/StatTiles.jsx";
import Narrative from "./components/Narrative.jsx";
import TopCommodities from "./components/TopCommodities.jsx";
import PriceBands from "./components/PriceBands.jsx";
import PriceTrend from "./components/PriceTrend.jsx";
import PriceMovement from "./components/PriceMovement.jsx";
import Perishables from "./components/Perishables.jsx";
import MarketCompliance from "./components/MarketCompliance.jsx";
import ReportingExceptions from "./components/ReportingExceptions.jsx";
import AlertRegister from "./components/AlertRegister.jsx";
import ActionPoints from "./components/ActionPoints.jsx";
import "./App.css";

function getInitialTheme() {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function DownloadMenu({ factSheet, briefEn, briefHi }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  return (
    <div className="download-menu-wrap" ref={ref}>
      <button className="download-btn" onClick={() => setOpen((o) => !o)} title="Download the full report">
        ⬇ Download Report
      </button>
      {open ? (
        <div className="download-menu" role="menu">
          <button
            role="menuitem"
            onClick={() => {
              downloadReportHtml(factSheet, briefEn, briefHi);
              setOpen(false);
            }}
          >
            Download as HTML
          </button>
          <button
            role="menuitem"
            onClick={() => {
              openReportForPrint(factSheet, briefEn, briefHi);
              setOpen(false);
            }}
          >
            Download as PDF
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default function App() {
  const [state, setState] = useState({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState(null);
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);

  const load = useCallback(() => {
    setState({ status: "loading" });
    loadWeeklyBrief()
      .then((data) => setState({ status: "ready", data }))
      .catch((err) => setState({ status: "error", error: err.message }));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshError(null);
    try {
      const data = await refreshWeeklyBrief();
      setState({ status: "ready", data: { ...data, isSample: false } });
    } catch (err) {
      setRefreshError(err.message);
    } finally {
      setRefreshing(false);
    }
  };

  if (state.status === "loading") {
    return <div className="app-status">Loading weekly brief…</div>;
  }
  if (state.status === "error") {
    return <div className="app-status app-status-error">Failed to load: {state.error}</div>;
  }

  const { factSheet, briefEn, briefHi, isSample } = state.data;
  const cov = factSheet.coverage;
  const mc = factSheet.market_compliance;
  const generatedDate = factSheet.generated_at ? formatDate(factSheet.generated_at.slice(0, 10)) : "—";

  return (
    <div className="app">
      <header className="mast">
        <div className="mast-top">
          <div>
            <div className="mast-eyebrow">Agmarknet 2.0 · Decision Intelligence</div>
            <h1>
              Weekly Market Intelligence Summary
              <em>Madhya Pradesh — State Consolidated Brief</em>
            </h1>
          </div>
          <div className="header-actions">
            <button
              className="theme-toggle-btn"
              onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
              aria-label="Toggle theme"
              title="Toggle light/dark theme"
            >
              {theme === "light" ? "🌙" : "☀️"}
            </button>
            <button className="refresh-btn" onClick={handleRefresh} disabled={refreshing}>
              {refreshing ? "Pulling live data…" : "Refresh from Agmarknet"}
            </button>
            <DownloadMenu factSheet={factSheet} briefEn={briefEn} briefHi={briefHi} />
          </div>
        </div>
        <div className="mast-period">
          <div className="mp-item">
            <span className="k">Period</span>
            <span className="v">{formatDateRange(factSheet.week_start, factSheet.week_end)}</span>
          </div>
          <div className="mp-item">
            <span className="k">Market yards in scope</span>
            <span className="v">{mc.markets_in_roster}</span>
          </div>
          <div className="mp-item">
            <span className="k">Reported</span>
            <span className="v">{mc.markets_reporting_at_least_once}</span>
          </div>
          <div className="mp-item">
            <span className="k">Generated</span>
            <span className="v">{generatedDate}</span>
          </div>
        </div>
      </header>

      {isSample ? (
        <div className="banner banner-demo">
          Demo data — backend not reached. Start it (see README) or click Refresh once it's running.
        </div>
      ) : null}
      {refreshError ? <div className="banner banner-error">Refresh failed: {refreshError}</div> : null}

      {cov ? (
        <div className="cov">
          <span className="cov-badge">Coverage</span>
          <span>
            Completeness <b className="tabular">{cov.completeness_pct}%</b> — {mc.markets_reporting_at_least_once} of{" "}
            {mc.markets_in_roster} active market yards reported at least one day
          </span>
          <span>
            Records processed <b className="tabular">{cov.records_processed.toLocaleString()}</b>
          </span>
          <span>
            Missing modal price <b className="tabular">{cov.records_missing_price.toLocaleString()}</b>
          </span>
        </div>
      ) : null}

      <section className="panel">
        <SectionHeading n="01" title="State position at a glance" tag="KPIs + narrative" />
        <StatTiles factSheet={factSheet} />
        <Narrative
          briefEn={briefEn}
          briefHi={briefHi}
          narrationMeta={factSheet.narration_meta}
          generatedAt={factSheet.generated_at}
        />
      </section>

      <TopCommodities topCommodities={factSheet.top_commodities} />
      <PriceBands priceBands={factSheet.price_bands} />
      <PriceTrend priceTrend={factSheet.price_trend} />
      <PriceMovement priceChange={factSheet.price_change} />
      <Perishables perishables={factSheet.perishables} />
      <MarketCompliance marketCompliance={factSheet.market_compliance} />
      <ReportingExceptions reportingExceptions={factSheet.reporting_exceptions} />
      <AlertRegister alerts={factSheet.alerts} />
      <ActionPoints actionPoints={factSheet.action_points} />

      <div className="lineage">
        <h4>Data lineage and reproducibility</h4>
        <div className="lg">
          <div>Source &nbsp;<b>{factSheet.source ?? "agmarknet.gov.in"}</b></div>
          <div>Generated &nbsp;<b>{factSheet.generated_at ?? "—"}</b></div>
          <div>Records processed &nbsp;<b>{cov?.records_processed?.toLocaleString() ?? "—"}</b></div>
          <div>Missing modal price &nbsp;<b>{cov?.records_missing_price?.toLocaleString() ?? "—"}</b></div>
          <div>Numeric grounding (EN) &nbsp;<b>{factSheet.narration_meta?.en?.accuracy_pct ?? "—"}% verified</b></div>
          <div>Numeric grounding (HI) &nbsp;<b>{factSheet.narration_meta?.hi?.accuracy_pct ?? "—"}% verified</b></div>
        </div>
      </div>
      <div className="disclaim">
        <b>Data source and generation</b>
        Every figure in this report is computed deterministically from the current week's raw Agmarknet 2.0
        pull (see the raw dataset archived alongside this fact sheet). The executive narrative is generated
        only from this fact sheet's own values and is machine-validated for numeric grounding before
        publication; when the check fails, a fixed, guaranteed-accurate template is published instead.
      </div>

      <footer className="app-footer">
        Source: {factSheet.source ?? "agmarknet.gov.in"} · Generated {factSheet.generated_at ?? "—"}
      </footer>
    </div>
  );
}
