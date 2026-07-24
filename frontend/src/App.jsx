import { useEffect, useState, useCallback } from "react";
import { loadWeeklyBrief, refreshWeeklyBrief } from "./lib/loadData.js";
import StatTiles from "./components/StatTiles.jsx";
import TopCommodities from "./components/TopCommodities.jsx";
import PriceMovement from "./components/PriceMovement.jsx";
import MarketCompliance from "./components/MarketCompliance.jsx";
import Narrative from "./components/Narrative.jsx";
import "./App.css";

function getInitialTheme() {
  const stored = localStorage.getItem("theme");
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
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

  return (
    <div className="app">
      <header className="app-header">
        <div>
          <h1 className="app-title">Madhya Pradesh — Weekly Mandi Summary</h1>
          <p className="app-subtitle">
            {factSheet.week_start} to {factSheet.week_end}
          </p>
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
        </div>
      </header>

      {isSample ? (
        <div className="banner banner-demo">
          Demo data — backend not reached. Start it (see README) or click Refresh once it's running.
        </div>
      ) : null}
      {refreshError ? <div className="banner banner-error">Refresh failed: {refreshError}</div> : null}

      <StatTiles factSheet={factSheet} />
      <TopCommodities topCommodities={factSheet.top_commodities} />
      <PriceMovement priceChange={factSheet.price_change} />
      <MarketCompliance marketCompliance={factSheet.market_compliance} />
      <Narrative briefEn={briefEn} briefHi={briefHi} />

      <footer className="app-footer">
        Source: {factSheet.source ?? "agmarknet.gov.in"} · Generated {factSheet.generated_at ?? "—"}
      </footer>
    </div>
  );
}
