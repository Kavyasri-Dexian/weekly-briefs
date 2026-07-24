const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:4000";

const SAMPLE_FACT_SHEET = "/data/sample_state_fact_sheet.json";
const SAMPLE_BRIEF_EN = "/data/sample_brief_en.txt";
const SAMPLE_BRIEF_HI = "/data/sample_brief_hi.txt";

async function fetchOk(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res;
}

async function loadSample() {
  const [factSheet, briefEn, briefHi] = await Promise.all([
    fetchOk(SAMPLE_FACT_SHEET).then((r) => r.json()),
    fetchOk(SAMPLE_BRIEF_EN).then((r) => r.text()),
    fetchOk(SAMPLE_BRIEF_HI).then((r) => r.text()),
  ]);
  return { factSheet, briefEn, briefHi, isSample: true };
}

/**
 * Loads the weekly brief from the backend (backend/server.js, which serves
 * whatever backend/scripts/pipeline.py last generated from the live
 * Agmarknet API). Falls back to the bundled sample if the backend isn't
 * running or hasn't generated data yet, so the UI is always demoable.
 * `isSample` drives the demo-data banner in App.jsx.
 */
export async function loadWeeklyBrief() {
  try {
    const res = await fetch(`${BACKEND_URL}/api/weekly-brief`);
    if (!res.ok) throw new Error(`backend: ${res.status}`);
    const data = await res.json();
    return { ...data, isSample: false };
  } catch {
    return loadSample();
  }
}

/** Triggers a live re-pull on the backend (POST /api/refresh) and returns the fresh result. */
export async function refreshWeeklyBrief(weekEnd) {
  const res = await fetch(`${BACKEND_URL}/api/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(weekEnd ? { weekEnd } : {}),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || body.error || `refresh failed: ${res.status}`);
  }
  return res.json();
}
