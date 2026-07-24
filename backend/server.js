import express from "express";
import cors from "cors";
import { fileURLToPath } from "url";
import path from "path";
import fs from "fs/promises";
import { spawn } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "data", "output");
const SCRIPTS_DIR = path.join(__dirname, "scripts");
const PORT = process.env.PORT || 4000;
const PYTHON_BIN = process.env.PYTHON_BIN || "python3";
const REFRESH_TIMEOUT_MS = 5 * 60 * 1000; // pipeline pulls 14 days of live data — budget generously

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
    const args = [path.join(SCRIPTS_DIR, "pipeline.py"), "--out-dir", OUTPUT_DIR];
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

app.listen(PORT, () => {
  console.log(`Backend listening on http://localhost:${PORT}`);
  console.log(`  GET  /api/weekly-brief  — serves the last generated output`);
  console.log(`  POST /api/refresh       — pulls fresh live data and regenerates it`);
});
