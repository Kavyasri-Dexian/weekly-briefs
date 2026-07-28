# Madhya Pradesh Weekly Mandi Summary

Automatically generates a bilingual (English/Hindi) weekly market summary report for
Madhya Pradesh's agricultural mandis, sourced live from Agmarknet — arrivals, prices,
and market reporting compliance, with every published number traceable back to raw
source data.

## Architecture

Four layers, each with one clear responsibility. Data flows one direction only — nothing
downstream ever feeds back into an earlier stage.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 1. SOURCE                                                                │
│    Agmarknet 2.0 public API (api.agmarknet.gov.in/v1)                   │
│    → raw row-level records: market, commodity, price, arrival qty       │
└───────────────────────────────────┬───────────────────────────────────-─┘
                                     │  fetched concurrently (pipeline.py)
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 2. COMPUTE  (backend/scripts/pipeline.py)                               │
│    Raw rows  →  every statistic computed in plain Python                │
│    (arrivals, price change/trend, compliance, alerts, ...)              │
│    →  fact_sheet.json               →  raw rows archived as CSV         │
│       (single source of truth)         (backend/dataset/<week>/, audit  │
│                                          trail for every published #)   │
└───────────────────────────────────┬───────────────────────────────────-─┘
                                     │
                     ┌───────────────┴────────────────┐
                     ▼                                 ▼
┌──────────────────────────────────┐   ┌──────────────────────────────────┐
│ 3a. TEMPLATE (deterministic)     │   │ 3b. AI PARAPHRASE (narration.py) │
│  pipeline.py's narrate_english/  │   │  Qwen2.5-0.5B-Instruct, local,   │
│  narrate_hindi — string-formats  │──▶│  rewords the template's own text │
│  the fact sheet into 3 correct   │   │  without touching any number.    │
│  paragraphs. Always correct by   │   │  Gated: numeric fidelity +       │
│  construction; never invented.   │   │  format + spelling/grammar.      │
└──────────────────────────────────┘   └────────────────┬─────────────────┘
                     ▲                                    │
                     │            gate fails / times out  │
                     └────────────────────────────────────┘
                                     │  gate passes → AI text published
                                     │  gate fails  → template published
                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. SERVE                                                                 │
│    server.js (Express) → GET /api/weekly-brief, POST /api/refresh       │
│    React app (frontend/) → report UI, EN/HI toggle, HTML/PDF export     │
└─────────────────────────────────────────────────────────────────────────┘
```

**Why stage 3 is two boxes, not one:** the template is generated *first* and is always
100% accurate (it's just formatted output of already-computed numbers). The AI model
never sees the raw fact sheet — it only ever rewords the template's already-correct
sentences, which removes the failure mode where a model has to extract and correctly
attribute dozens of numbers itself. Either way, the fact sheet's own numbers are the only
source of truth; the model's job is phrasing, never arithmetic.

- **Backend**: Python (`backend/scripts/`) owns every stage from fetch through narration;
  Node/Express (`backend/server.js`) is a thin serving layer — it triggers the Python
  pipeline as a subprocess and serves whatever it last wrote to disk.
- **Frontend**: React + Vite (`frontend/`), a single-page report with light/dark theme,
  bilingual toggle, and HTML/PDF export that mirrors the live view.

## Data source

Live data comes directly from Agmarknet 2.0's own public REST API —
`https://api.agmarknet.gov.in/v1` — no API key, login, or scraping involved. This is an
undocumented but genuinely public endpoint (found by inspecting the Agmarknet site's own
JS bundles), not an official partner API.

- `GET /daily-price-arrival/filters` — pulls the registered Madhya Pradesh market/district
  roster once per run.
- `POST /prices-and-arrivals/market-report/daily` — called once per market ID per day,
  fetched concurrently (max 6 requests in flight) across four date ranges every run:
  current week, prior week (for week-on-week comparison), the same week last month, and
  the same week last year.

Each fetch produces raw, row-level records (state, district, market, commodity, variety,
grade, arrival date, min/max/modal price, arrival quantity). These raw rows are archived
unmodified as CSV under `backend/dataset/<week>/` — the audit trail: every number in the
report can be traced back to the exact rows it was computed from.

### Week selection

By default (`pipeline.py`'s `most_recent_completed_week_end()`), the report always covers
the most recently **completed** Monday–Sunday calendar week — a fixed week, not a rolling
window, so refreshing on any day of the week returns the same week until the following
Monday. Pass `--week-end YYYY-MM-DD` to `pipeline.py` to target a specific week explicitly.

## How the numbers are computed

Every statistic in the report — total arrivals, week-on-week % change, top commodities,
price gainers/decliners, price trend vs. three comparison periods, market reporting
compliance bands, price bands, perishables distress-composite flags, reporting
exceptions, and a simple threshold-based alert register — is computed in plain Python
(`backend/scripts/pipeline.py`) directly from the raw fetched rows. This is a hard rule
throughout the codebase: **no AI model or template is ever allowed to calculate a new
number** — only phrase numbers that already exist in the computed "fact sheet."

## Alert register and action points

Both are a fixed, deterministic rules engine over numbers already computed elsewhere in
the fact sheet (`compute_alerts` / `compute_action_points` in `pipeline.py`) — never a
judgment call by the narration model, and never based on MSP (not fetched).

**Alert register** — three trigger types:

1. **Price volatility** — for every commodity in the top gainers/decliners list, the
   absolute week-on-week modal-price move: `≥ 20%` → Critical, `≥ 10%` (below 20%) →
   High, otherwise no alert.
2. **Distress composite** — any Perishables-watchlist commodity already flagged
   `distress_composite: true` (arrival WoW `≥ +15%` **and** price WoW `≤ -15%` in the
   same commodity/week — a classic "glut" signal) becomes a Critical alert.
3. **Reporting default** — if any market yards filed no return this week: `≥ 10%` of the
   roster not reporting → High, otherwise Watch.

Alerts are sorted Critical → High → Watch.

**Action points** are derived 1:1 from every Critical/High alert (Watch-severity alerts
don't generate one): `action` restates the alert's type/entity/trigger, `owner` carries
over from the alert, and `target` = `generated_at` + a fixed number of days per severity
(3 for Critical, 7 for High).

## The summarization model

The Executive Narrative (the prose summary at the top of the report) uses a two-stage,
accuracy-first design:

1. **Deterministic template** (`narrate_english` / `narrate_hindi` in `pipeline.py`)
   builds a guaranteed-correct 3-paragraph narrative directly from the fact sheet's own
   values via string formatting. No model involved — impossible for this step to state
   an unsupported number.
2. **AI paraphrase** (`narrate_by_paraphrase` in `backend/scripts/narration.py`) takes
   that already-correct template text and asks a small open-source language model to
   *reword* it — vary sentence structure and phrasing without touching any number, price,
   percentage, date, or name. This is deliberately **not** "generate prose from the raw
   JSON fact sheet" (an earlier design) — extracting and attributing dozens of numbers
   from structured JSON was found, through extensive testing, to cause real errors (wrong
   numbers, right numbers attached to the wrong claim, sign/direction mistakes). Asking
   the model to paraphrase an already-correct passage removes that failure class, since
   every number is already correctly bound to its claim before the model ever sees it.

**Model**: [`Qwen/Qwen2.5-0.5B-Instruct`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
(configurable via `LOCAL_NARRATION_MODEL`), an open-source instruction-tuned model small
enough to run entirely on CPU with no GPU. Runs locally via `backend/scripts/local_infer.py`
in an isolated Python virtual environment (`C:\venv\mlenv`) — no external API, no account,
no cost, no data leaves the machine.

### The accuracy gate

Every model draft — whether paraphrase or (in earlier designs) direct generation — must
pass a multi-stage gate before it can be published:

| Check | Catches |
|---|---|
| Numeric grounding | Any number in the draft that doesn't appear in the source |
| Number multiplicity | A real number reused in place of a *different* fact's real value (passes simple grounding but is still wrong) |
| Paraphrase fidelity | Any number added, dropped, or altered relative to the original template (used only by the paraphrase path) |
| Prose-shape | Markdown headers/bold/bullets, raw JSON echoes, or responses too short to be a real summary |
| Spelling/grammar | Offline English dictionary check (commodity/market names auto-whitelisted from that week's own data) + language-agnostic structural checks (doubled spaces, unbalanced parentheses, missing terminal punctuation) |

A draft gets up to 3 attempts (with corrective feedback each retry — e.g. "you wrote 3,
the source says 0.3"). If every attempt still fails, the pipeline **silently falls back
to the deterministic template** — the report is always published, always accurate, and
the UI shows an accuracy badge (numbers verified) plus a spelling/grammar badge so it's
never ambiguous which source authored the published text.

### Fine-tuning

`backend/scripts/build_training_data.py` + `train_lora.py` fine-tune a small LoRA adapter
per language (`backend/lora_adapter_en/`, `backend/lora_adapter_hi/`) via **self-
distillation** — training the model on the deterministic template's own guaranteed-correct
output, so it learns to reliably reproduce grounded structure. Adapters are optional; the
pipeline runs the plain base model if no adapter is present.

## Running it

```bash
# Backend
cd backend
npm install
cp .env.example .env      # fill in NARRATION_PROVIDER etc.
npm run dev                # starts the Express API on :4000

# Frontend
cd frontend
npm install
npm run dev                 # starts the Vite dev server
```

- `POST /api/refresh` triggers a fresh pull from Agmarknet and regenerates the report.
- `GET /api/weekly-brief` returns the most recently generated fact sheet + narratives.
- `POST /api/trigger-scheduled-job` manually fires the same job the Sunday-night schedule runs.
- Or run the pipeline directly: `python backend/scripts/pipeline.py --out-dir ../data/output`

See `backend/.env.example` for all configuration options (narration provider, model
paths, timeouts, `SCHEDULE_CRON`).

## Automated weekly generation

The reporting week is a fixed **Sunday-Saturday** calendar week. While the backend server
(`npm start`/`npm run dev`) is running, a cron job (`node-cron`, `server.js`) automatically
regenerates the report every Sunday night (default 9:00 PM, configurable via
`SCHEDULE_CRON`) — picking up the Saturday that just ended.

Each run writes two things:
- **`backend/data/output/`** — the "current" output the live app serves, overwritten on
  every run (manual refresh or scheduled).
- **`backend/data/archive/<week_start>_to_<week_end>/<snapshot_id>/`** — a durable, never-
  overwritten copy of that exact snapshot: `fact_sheet.json`, `brief_en.txt`, `brief_hi.txt`,
  and `report.html` (the same self-contained report the "Download as HTML" button produces,
  rendered server-side in Node by reusing `buildReportHtml.js` directly — no duplicate
  rendering logic).

`snapshot_id` follows `AGM-MP-<ISO year><ISO week>-<NN>` — `NN` increments each time that
same week is regenerated (`AGM-MP-2026W30-01`, then `-02` on the next regeneration for that
week), tracked in a small `backend/data/snapshot_counters.json` manifest.

This job only fires while the Node server process is actually running — it does not use
Windows Task Scheduler or any OS-level mechanism, so keeping the backend running (or under
a process manager) is required for the automation to actually happen unattended.

## Project layout

```
backend/
  scripts/
    pipeline.py         # data fetch, all computation, deterministic templates
    narration.py         # AI narration + accuracy gate
    local_infer.py        # standalone model-inference worker (runs in isolated venv)
    build_training_data.py  # builds LoRA self-distillation training data
    train_lora.py          # fine-tunes the per-language LoRA adapters
    backfill_dataset.py    # backfills historical weeks into dataset/
  dataset/                # archived raw weekly CSV pulls (one folder per week)
  lora_adapter_en/         # fine-tuned English adapter
  lora_adapter_hi/         # fine-tuned Hindi adapter
  data/output/            # latest generated fact sheet + briefs
  server.js               # Express API
frontend/
  src/
    components/            # one component per report section
    lib/buildReportHtml.js  # self-contained HTML/PDF export, mirrors the live UI
    App.jsx / App.css       # layout, masthead, theme system
```
