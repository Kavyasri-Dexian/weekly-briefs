import "dotenv/config";
import express from "express";
import cors from "cors";
import cron from "node-cron";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs/promises";
import { spawn } from "child_process";
// buildReportHtml() is pure string-templating (no DOM/browser APIs — only
// the download/print wrapper functions around it use `document`), so it
// can run directly under Node exactly as it does in the browser, producing
// byte-identical HTML — reused here rather than reimplementing report
// rendering server-side.
import { buildReportHtml } from "../frontend/src/lib/buildReportHtml.js";
import { sendReportEmail } from "./emailReport.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "data", "output");
const DATASET_DIR = path.join(__dirname, "dataset");
const ARCHIVE_DIR = path.join(__dirname, "data", "archive");
const SCRIPTS_DIR = path.join(__dirname, "scripts");
const PORT = process.env.PORT || 4000;
const PYTHON_BIN = process.env.PYTHON_BIN || "python3";
const REFRESH_TIMEOUT_MS = 10 * 60 * 1000; // a real measured refresh took 271s; generous margin above that
// Cron syntax: minute hour day-of-month month day-of-week (0=Sunday). Default
// 9:00 PM every Sunday — the night after the Sunday-Saturday week's own
// Saturday close, matching most_recent_completed_week_end's own logic in
// pipeline.py exactly (a Sunday-night run picks up the Saturday that just
// ended, not a week-old one).
const SCHEDULE_CRON = process.env.SCHEDULE_CRON || "0 21 * * 0";

const FACT_SHEET_FILE = "madhya_pradesh_state_fact_sheet.json";
const BRIEF_EN_FILE = "madhya_pradesh_weekly_brief_en.txt";
const BRIEF_HI_FILE = "madhya_pradesh_weekly_brief_hi.txt";

const app = express();
app.use(cors());
app.use(express.json());

async function readCurrentOutput() {
  const factSheetPath = path.join(OUTPUT_DIR, FACT_SHEET_FILE);
  const briefEnPath = path.join(OUTPUT_DIR, BRIEF_EN_FILE);
  const briefHiPath = path.join(OUTPUT_DIR, BRIEF_HI_FILE);

  const [factSheetRaw, briefEn, briefHi] = await Promise.all([
    fs.readFile(factSheetPath, "utf-8"),
    fs.readFile(briefEnPath, "utf-8"),
    fs.readFile(briefHiPath, "utf-8"),
  ]);

  return { factSheet: JSON.parse(factSheetRaw), briefEn, briefHi };
}

function runPipeline({ weekEnd } = {}) {
  return new Promise((resolve, reject) => {
    const args = [
      path.join(SCRIPTS_DIR, "pipeline.py"),
      "--out-dir", OUTPUT_DIR,
      "--dataset-dir", DATASET_DIR,
      "--archive-dir", ARCHIVE_DIR,
    ];
    if (weekEnd) args.push("--week-end", weekEnd);

    const proc = spawn(PYTHON_BIN, args, { cwd: SCRIPTS_DIR });
    let stderr = "";
    const timer = setTimeout(() => {
      proc.kill();
      reject(new Error(`Pipeline timed out after ${REFRESH_TIMEOUT_MS}ms`));
    }, REFRESH_TIMEOUT_MS);

    proc.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      process.stderr.write(`[pipeline] ${text}`);
    });
    proc.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    proc.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve();
      else reject(new Error(`Pipeline exited with code ${code}\n${stderr.slice(-2000)}`));
    });
  });
}

// Writes the same self-contained HTML the live app's "Download as HTML"
// button produces into the archive snapshot folder pipeline.py's
// archive_snapshot() already created (keyed by week range + snapshot_id) —
// so a fully-formed, standalone report file sits next to the raw
// fact_sheet.json/briefs from the moment the scheduled job finishes, not
// just data someone has to re-render later.
async function archiveReportHtml(factSheet, briefEn, briefHi) {
  const weekKey = `${factSheet.week_start}_to_${factSheet.week_end}`;
  const snapshotDir = path.join(ARCHIVE_DIR, weekKey, factSheet.snapshot_id);
  await fs.mkdir(snapshotDir, { recursive: true });
  const html = buildReportHtml(factSheet, briefEn, briefHi);
  await fs.writeFile(path.join(snapshotDir, "report.html"), html, "utf-8");
  return path.join(snapshotDir, "report.html");
}

let scheduledJobRunning = false;

// The Sunday-night automated job: pulls fresh data for the just-completed
// Sunday-Saturday week, regenerates the live output AND a durable archive
// snapshot (fact sheet + briefs, via pipeline.py's own --archive-dir), then
// additionally renders and archives the self-contained HTML report here in
// Node (pipeline.py can't do this part — buildReportHtml.js is JS). Guarded
// against overlap: if a manual trigger or a slow-running previous job is
// still in flight, a new scheduled fire is skipped rather than queued
// (running two pipeline.py processes concurrently was tested earlier this
// session and pushed system memory into a genuine near-crash state).
async function runScheduledJob() {
  if (scheduledJobRunning) {
    console.log("[scheduler] skipped — a run is already in progress");
    return;
  }
  scheduledJobRunning = true;
  const startedAt = new Date().toISOString();
  console.log(`[scheduler] starting scheduled weekly report generation (${startedAt})`);
  try {
    await runPipeline({});
    const { factSheet, briefEn, briefHi } = await readCurrentOutput();
    const htmlPath = await archiveReportHtml(factSheet, briefEn, briefHi);
    console.log(`[scheduler] done — snapshot ${factSheet.snapshot_id}, report saved to ${htmlPath}`);
    // Backend-only — no route/UI triggers this. No-ops safely if SMTP/
    // recipient env vars aren't set (see emailReport.js), so an unconfigured
    // mailer never fails the generation+archival that already succeeded above.
    try {
      await sendReportEmail(factSheet, htmlPath);
    } catch (emailErr) {
      console.error(`[email] send failed (report generation itself still succeeded): ${emailErr.message}`);
    }
  } catch (err) {
    console.error(`[scheduler] FAILED: ${err.message}`);
  } finally {
    scheduledJobRunning = false;
  }
}

cron.schedule(SCHEDULE_CRON, runScheduledJob);
console.log(`[scheduler] registered — will run on cron "${SCHEDULE_CRON}" (set SCHEDULE_CRON to change; "0 21 * * 0" = 9:00 PM every Sunday, server's local time)`);

app.get("/api/health", (_req, res) => {
  res.json({ ok: true });
});

// Serves whatever the pipeline last generated. Does NOT fall back to fake
// data — an empty output/ dir means "run POST /api/refresh first", not
// "serve a placeholder as if it were real."
app.get("/api/weekly-brief", async (_req, res) => {
  try {
    const data = await readCurrentOutput();
    res.json({ ...data, isSample: false });
  } catch (err) {
    res.status(503).json({
      error: "No generated data yet. POST /api/refresh to pull live data from Agmarknet, or run scripts/pipeline.py directly.",
      detail: err.message,
    });
  }
});

// Triggers a fresh live pull from Agmarknet (scripts/pipeline.py) and
// returns the regenerated fact sheet + briefs. Optional body: { "weekEnd": "YYYY-MM-DD" }.
app.post("/api/refresh", async (req, res) => {
  try {
    await runPipeline({ weekEnd: req.body?.weekEnd });
    const data = await readCurrentOutput();
    res.json({ ...data, isSample: false });
  } catch (err) {
    res.status(502).json({ error: "Pipeline run failed.", detail: err.message });
  }
});

// Manually fires the same job the Sunday-night cron schedule runs, without
// waiting for Sunday — for testing the scheduler/archival path on demand.
// Returns immediately (202) since a full run takes several minutes; check
// server logs or the archive folder for the actual result, same as the
// real scheduled job.
app.post("/api/trigger-scheduled-job", (_req, res) => {
  if (scheduledJobRunning) {
    return res.status(409).json({ error: "A scheduled/triggered run is already in progress." });
  }
  runScheduledJob();
  res.status(202).json({ message: "Scheduled job triggered — check server logs and the archive/ folder for progress." });
});

app.listen(PORT, () => {
  console.log(`Backend listening on http://localhost:${PORT}`);
  console.log(`  GET  /api/weekly-brief          — serves the last generated output`);
  console.log(`  POST /api/refresh               — pulls fresh live data and regenerates it`);
  console.log(`  POST /api/trigger-scheduled-job — manually fires the same job the Sunday-night schedule runs`);
});
