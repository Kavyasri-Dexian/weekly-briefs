"""
Builds a supervised fine-tuning dataset from the backfilled dataset/ CSVs
(see backfill_dataset.py) — self-distillation from the deterministic
template: for each historical week, compute the exact same fact sheet
production uses (same functions, imported from pipeline.py), then use the
guaranteed-grounded template narrative as the target completion. The model
is trained to reliably reproduce grounded, gate-passing prose for a given
fact sheet — not to "know" anything new, just to imitate the always-correct
template's structure/content reliably instead of drifting into unsupported
numbers (which is what currently makes it fail the numeric gate so often).

Output: training_data_en.jsonl and training_data_hi.jsonl, each line
{"prompt": ..., "completion": ...} — completion is body-only (bulleted,
"- " prefixed) matching exactly what narrate_with_model asks the live model
to produce and how compose_briefs parses a model draft.

Usage:
    python build_training_data.py --dataset-dir ../dataset --out-dir .
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, date as date_cls

sys.path.insert(0, os.path.dirname(__file__))

from pipeline import (
    compute_overall_arrivals, compute_market_compliance, compute_top_commodities,
    compute_price_change, compute_price_trend, narrate_english, narrate_hindi,
    fetch_filters, mp_roster, TOP_N_COMMODITIES,
)
from pipeline import _body_only  # noqa: E402
from narration import PROMPT_INSTRUCTIONS, _slim_fact_sheet  # noqa: E402


def load_week_rows(csv_path: str):
    rows = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            d = dict(r)
            if d.get("arrival_date"):
                d["arrival_date"] = datetime.strptime(d["arrival_date"], "%Y-%m-%d").date()
            for k in ("min_price", "max_price", "modal_price", "arrival_qty"):
                d[k] = float(d[k]) if d.get(k) not in (None, "", "None") else None
            rows.append(d)
    return rows


def discover_weeks(dataset_dir: str):
    """Returns [(week_start_date, week_end_date, csv_path), ...] sorted oldest to newest."""
    weeks = []
    for name in os.listdir(dataset_dir):
        folder = os.path.join(dataset_dir, name)
        if not os.path.isdir(folder):
            continue
        try:
            start_s, end_s = name.split("_to_")
            start = datetime.strptime(start_s, "%Y-%m-%d").date()
            end = datetime.strptime(end_s, "%Y-%m-%d").date()
        except ValueError:
            continue
        csv_path = os.path.join(folder, f"madhya_pradesh_{name}.csv")
        if os.path.exists(csv_path):
            weeks.append((start, end, csv_path))
    weeks.sort(key=lambda w: w[0])
    return weeks


def build_examples(dataset_dir: str):
    weeks = discover_weeks(dataset_dir)
    print(f"Discovered {len(weeks)} weeks in {dataset_dir}", file=sys.stderr)
    if len(weeks) < 2:
        raise RuntimeError("Need at least 2 weeks to form current+prior pairs")

    print("Fetching authoritative MP market roster ...", file=sys.stderr)
    filters = fetch_filters()
    _, _, market_id_to_name = mp_roster(filters)
    full_market_names = sorted(market_id_to_name.values())

    rows_by_week = {}
    for start, end, path in weeks:
        rows_by_week[start] = load_week_rows(path)
        print(f"  loaded {path}: {len(rows_by_week[start])} rows", file=sys.stderr)

    examples_en, examples_hi = [], []
    for i in range(1, len(weeks)):
        week_start, week_end, _ = weeks[i]
        prior_start, prior_end, _ = weeks[i - 1]
        current_rows = rows_by_week[week_start]
        prior_rows = rows_by_week[prior_start]

        # Same week 4 weeks back, if present in the discovered set.
        last_month_rows = []
        if i >= 4:
            last_month_rows = rows_by_week[weeks[i - 4][0]]

        top_commodities = compute_top_commodities(current_rows, prior_rows, TOP_N_COMMODITIES)
        top_names = [c["commodity"] for c in top_commodities["top_commodities"]]

        fact_sheet = {
            "state": "Madhya Pradesh",
            "week_start": str(week_start),
            "week_end": str(week_end),
            "overall_arrivals": compute_overall_arrivals(current_rows, prior_rows),
            "market_compliance": compute_market_compliance(current_rows, full_market_names),
            "top_commodities": top_commodities,
            "price_change": compute_price_change(current_rows, prior_rows),
            "price_trend": {
                "commodities": compute_price_trend(
                    current_rows, prior_rows, last_month_rows, [], top_names[:5]
                ),
            },
        }

        for lang, narrate_fn, examples in (("en", narrate_english, examples_en), ("hi", narrate_hindi, examples_hi)):
            template_text = narrate_fn(fact_sheet)
            # narrate_english/narrate_hindi already emit the target register —
            # 3 "\n\n"-separated flowing-prose paragraphs — so the training
            # completion is just the title-stripped body, unmodified. Kept
            # as its own step (not inlined) because that's the exact value
            # the model must learn to reproduce; changing template shape
            # again should visibly break here rather than silently ship.
            completion = _body_only(template_text)

            # _slim_fact_sheet trims top_commodities/price_trend to what the
            # narration prompt actually needs — same function production
            # inference uses, so the training prompt shape can never drift
            # from what the model will actually see when serving.
            slim = _slim_fact_sheet(fact_sheet)
            prompt = f"{PROMPT_INSTRUCTIONS[lang]}\n\nJSON fact sheet:\n{json.dumps(slim, ensure_ascii=False)}"
            examples.append({"prompt": prompt, "completion": completion})

        print(f"  built example for week {week_start}..{week_end}", file=sys.stderr)

    return examples_en, examples_hi


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", default="../dataset")
    parser.add_argument("--out-dir", default=".")
    args = parser.parse_args()

    examples_en, examples_hi = build_examples(args.dataset_dir)

    for lang, examples in (("en", examples_en), ("hi", examples_hi)):
        path = os.path.join(args.out_dir, f"training_data_{lang}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")
        print(f"Wrote {len(examples)} examples to {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
