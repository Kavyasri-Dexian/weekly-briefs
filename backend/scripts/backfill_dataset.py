"""
Backfills historical Madhya Pradesh mandi data from the live Agmarknet API
into week-wise folders under dataset/ — the same raw row-level CSV format
pipeline.py writes for the current week (see write_raw_dataset there), run
repeatedly across a stretch of history instead of just the latest week.

Each week is fetched and written independently (not one giant batch), so a
failure partway through still leaves every already-completed week on disk —
re-running is safe and just re-fetches whichever weeks are missing by default.

Usage:
    python backfill_dataset.py --weeks 26 --end-date 2026-07-20 --dataset-dir ../dataset
    python backfill_dataset.py --weeks 26 --force   # re-fetch weeks that already have a file
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, date as date_cls, timezone

from pipeline import fetch_filters, mp_roster, fetch_days, write_raw_dataset, MAX_CONCURRENT_REQUESTS


def week_dir_and_file(dataset_dir: str, week_start: date_cls, week_end: date_cls):
    folder = os.path.join(dataset_dir, f"{week_start}_to_{week_end}")
    filename = f"madhya_pradesh_{week_start}_to_{week_end}.csv"
    return folder, os.path.join(folder, filename)


def backfill(end_date: date_cls, num_weeks: int, dataset_dir: str, force: bool = False):
    print("Fetching Agmarknet filters (market/district roster) ...", file=sys.stderr)
    filters = fetch_filters()
    market_ids, market_id_to_district, market_id_to_name = mp_roster(filters)
    print(f"Madhya Pradesh registered markets: {len(market_ids)}", file=sys.stderr)

    manifest = []
    t_start = time.time()

    for w in range(num_weeks):
        week_end = end_date - timedelta(days=7 * w)
        week_start = week_end - timedelta(days=6)
        folder, csv_path = week_dir_and_file(dataset_dir, week_start, week_end)

        if not force and os.path.exists(csv_path):
            print(f"[{w + 1}/{num_weeks}] {week_start} to {week_end}: already on disk, skipping "
                  f"(pass --force to re-fetch)", file=sys.stderr)
            manifest.append({"week_start": str(week_start), "week_end": str(week_end),
                              "status": "skipped_existing", "file": csv_path})
            continue

        days = [week_end - timedelta(days=6 - i) for i in range(7)]
        print(f"[{w + 1}/{num_weeks}] {week_start} to {week_end}: fetching 7 days "
              f"(max {MAX_CONCURRENT_REQUESTS} in flight) ...", file=sys.stderr)
        t0 = time.time()
        try:
            results = fetch_days(days, market_ids, market_id_to_district)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED: {exc}", file=sys.stderr)
            manifest.append({"week_start": str(week_start), "week_end": str(week_end),
                              "status": "failed", "error": str(exc)})
            continue

        rows, day_errors = [], []
        for day in days:
            day_rows, err = results[day]
            rows.extend(day_rows)
            if err is not None:
                day_errors.append((str(day), err))

        path = write_raw_dataset(rows, folder, week_start, week_end)
        elapsed = time.time() - t0
        print(f"  wrote {len(rows)} rows in {elapsed:.1f}s"
              + (f" — {len(day_errors)} day(s) had errors: {day_errors}" if day_errors else ""),
              file=sys.stderr)
        manifest.append({
            "week_start": str(week_start), "week_end": str(week_end),
            "status": "ok", "rows": len(rows), "file": path,
            "day_errors": day_errors, "fetch_seconds": round(elapsed, 1),
        })

    manifest_path = os.path.join(dataset_dir, "backfill_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "end_date": str(end_date),
            "num_weeks": num_weeks,
            "total_seconds": round(time.time() - t_start, 1),
            "weeks": manifest,
        }, f, indent=2, ensure_ascii=False)

    ok = sum(1 for m in manifest if m["status"] == "ok")
    skipped = sum(1 for m in manifest if m["status"] == "skipped_existing")
    failed = sum(1 for m in manifest if m["status"] == "failed")
    print(f"\nDone in {time.time() - t_start:.1f}s. {ok} weeks fetched, {skipped} already present, "
          f"{failed} failed. Manifest: {manifest_path}", file=sys.stderr)
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Backfill N weeks of Madhya Pradesh mandi data into week-wise dataset folders")
    parser.add_argument("--end-date", default=None,
                         help="YYYY-MM-DD, defaults to 2 days before today (matches pipeline.py's "
                              "own default — see there for why: Agmarknet's reporting lag).")
    parser.add_argument("--weeks", type=int, default=26, help="Number of weeks back to pull (26 ~= 6 months)")
    parser.add_argument("--dataset-dir", default="../dataset")
    parser.add_argument("--force", action="store_true", help="Re-fetch weeks that already have a file on disk")
    args = parser.parse_args()

    end_date = (
        datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date else (datetime.now(timezone.utc).date() - timedelta(days=1))
    )
    backfill(end_date, args.weeks, args.dataset_dir, force=args.force)


if __name__ == "__main__":
    main()
