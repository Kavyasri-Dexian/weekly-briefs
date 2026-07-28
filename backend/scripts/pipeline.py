"""
Madhya Pradesh Weekly Mandi Summary — headless live-data pipeline (backend).

Pulls real price + arrival-quantity data directly from Agmarknet 2.0's own
public API (api.agmarknet.gov.in/v1) — no API key, no login, no scraping.
Verified endpoint: POST /prices-and-arrivals/market-report/daily, called once
per day with every Madhya Pradesh market ID, returns full state coverage
(price + arrivals in tonnes) for that day in one call.

This mirrors pipeline.ipynb's aggregation/narrative logic but is a plain
script (no notebook/kernel needed) so the Express backend can invoke it as a
subprocess on a schedule or on demand ("POST /api/refresh").

Usage:
    python pipeline.py --out-dir ../data/output [--week-end 2026-07-23]
"""

import argparse
import calendar
import csv
import json
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, date as date_cls, timezone

import requests

from narration import narrate_by_paraphrase, score_grounding, check_spelling_grammar, _slim_fact_sheet


def format_date_readable(iso_date) -> str:
    """"2026-07-14" -> "July 14, 2026" — matches the frontend's
    toLocaleDateString formatting (no zero-padded day), used everywhere a
    date is shown in narrative text rather than machine-parsed."""
    d = iso_date if isinstance(iso_date, date_cls) else datetime.strptime(iso_date, "%Y-%m-%d").date()
    return f"{calendar.month_name[d.month]} {d.day}, {d.year}"

API_BASE = "https://api.agmarknet.gov.in/v1"
STATE_ID = 19  # Madhya Pradesh, per /daily-price-arrival/filters
STATE_NAME = "Madhya Pradesh"
TOP_N_COMMODITIES = 10
REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _retry_wait_seconds(attempt: int, response) -> float:
    """A 429 means the server is explicitly telling us to slow down — worth
    a longer, Retry-After-aware wait than a generic transient network
    error, which a short exponential backoff already handles fine. Real
    failure seen in production: this endpoint returned 429 after this
    session's own heavy testing volume, so this path is exercised for
    real, not hypothetical."""
    if response is not None and response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return min(60, 10 * attempt)  # 10s, 20s, 30s... capped at 60s
    return 2 ** attempt


def fetch_filters(retries: int = 4):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(f"{API_BASE}/daily-price-arrival/filters", headers=HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.json()["data"]
        except Exception as exc:  # noqa: BLE001 — surfaced via last_err below
            last_err = exc
            response = getattr(exc, "response", None)
            wait = _retry_wait_seconds(attempt, response)
            print(f"  [warn] filters fetch attempt {attempt}/{retries} failed: {exc} — retrying in {wait}s", file=sys.stderr)
            if attempt < retries:
                time.sleep(wait)
    raise RuntimeError(f"Failed to fetch filters after {retries} attempts: {last_err}")


def mp_roster(filters: dict):
    """Authoritative MP market roster + market_id -> district_name lookup,
    straight from Agmarknet's own market list — not inferred from which
    markets happen to show up in a data pull."""
    district_by_id = {d["id"]: d["district_name"] for d in filters["district_data"]}
    markets = [m for m in filters["market_data"] if m.get("state_id") == STATE_ID]
    market_ids = [m["id"] for m in markets]
    market_id_to_district = {
        m["id"]: district_by_id.get(m.get("district_id"), None) for m in markets
    }
    market_id_to_name = {m["id"]: m["mkt_name"] for m in markets}
    return market_ids, market_id_to_district, market_id_to_name


def fetch_market_report_daily(day: date_cls, market_ids: list, retries: int = 3):
    body = {
        "date": day.strftime("%Y-%m-%d"),
        "marketIds": market_ids,
        "stateIds": [STATE_ID],
        "includeExcel": False,
    }
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(
                f"{API_BASE}/prices-and-arrivals/market-report/daily",
                json=body, headers=HEADERS, timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
            if not payload.get("success"):
                raise RuntimeError(payload.get("message", "API returned success=false"))
            return payload
        except Exception as exc:  # noqa: BLE001 — surfaced via last_err below
            last_err = exc
            wait = _retry_wait_seconds(attempt, getattr(exc, "response", None))
            print(f"  [warn] {day} attempt {attempt}/{retries} failed: {exc} — retrying in {wait}s", file=sys.stderr)
            if attempt < retries:
                time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {day} after {retries} attempts: {last_err}")


def rows_from_response(day: date_cls, payload: dict, market_id_to_district: dict):
    rows = []
    for state_entry in payload.get("states", []):
        if state_entry.get("stateName") != STATE_NAME:
            continue
        for market in state_entry.get("markets", []):
            market_id = market.get("marketId")
            market_name = market.get("marketName")
            district = market_id_to_district.get(market_id)
            for commodity in market.get("commodities", []):
                commodity_name = commodity.get("commodityName")
                for rec in commodity.get("data", []):
                    rows.append({
                        "state": STATE_NAME,
                        "district": district,
                        "market": market_name,
                        "commodity": commodity_name,
                        "variety": rec.get("variety"),
                        "grade": rec.get("grade"),
                        "arrival_date": day,
                        "min_price": rec.get("minimumPrice"),
                        "max_price": rec.get("maximumPrice"),
                        "modal_price": rec.get("modalPrice"),
                        "arrival_qty": rec.get("arrivals"),
                        "price_unit": rec.get("unitOfPrice"),
                        "arrival_unit": rec.get("unitOfArrivals"),
                    })
    return rows


MAX_CONCURRENT_REQUESTS = 6  # each day's request is independent — fetch them in parallel rather
# than one at a time (14 sequential ~7s calls was the whole latency of a refresh); kept modest
# rather than maximal to stay a well-behaved client of a public government API.


def fetch_days(days: list, market_ids: list, market_id_to_district: dict):
    """Fetches every date in `days` concurrently. Returns {day: (rows, error_or_None)}."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}

    def _fetch_one(day):
        payload = fetch_market_report_daily(day, market_ids)
        return rows_from_response(day, payload, market_id_to_district)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_REQUESTS) as pool:
        future_to_day = {pool.submit(_fetch_one, day): day for day in days}
        for future in as_completed(future_to_day):
            day = future_to_day[future]
            try:
                day_rows = future.result()
                results[day] = (day_rows, None)
                print(f"  {day}: {len(day_rows)} rows", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                results[day] = ([], str(exc))
                print(f"  {day}: FAILED — {exc}", file=sys.stderr)
    return results


def fetch_live_range(week_end: date_cls, num_days: int, market_ids: list, market_id_to_district: dict):
    days = [week_end - timedelta(days=num_days - 1 - i) for i in range(num_days)]
    results = fetch_days(days, market_ids, market_id_to_district)
    rows, fetch_errors = [], []
    for day in days:
        day_rows, err = results[day]
        rows.extend(day_rows)
        if err is not None:
            fetch_errors.append((str(day), err))
    return rows, fetch_errors


# ---------------------------------------------------------------------------
# Aggregation — identical rules to pipeline.ipynb, applied to live-API rows.
# ---------------------------------------------------------------------------

def display_commodity_name(name: str) -> str:
    """Title-cases a commodity name for display (e.g. "mango powder" ->
    "Mango Powder") — Agmarknet's own data is inconsistently cased (most
    entries are properly capitalized, a handful like "mango powder" or
    "nigella seeds" are not). Applied only at the aggregation-output layer,
    never to the raw rows written to dataset/ — the archived audit trail
    stays exactly what the source returned."""
    if not name:
        return name
    return name.title()


def reporting_band(days: int) -> str:
    if days <= 0:
        return "0 days"
    if days <= 2:
        return "1-2 days"
    if days <= 4:
        return "3-4 days"
    if days <= 6:
        return "5-6 days"
    return "7 days"


def compute_market_compliance(current_rows: list, full_market_names: list):
    days_by_market = defaultdict(set)
    for r in current_rows:
        days_by_market[r["market"]].add(r["arrival_date"])

    per_market_days = {name: len(days_by_market.get(name, set())) for name in full_market_names}
    band_counts = defaultdict(int)
    for name in full_market_names:
        band_counts[reporting_band(per_market_days[name])] += 1

    band_order = ["0 days", "1-2 days", "3-4 days", "5-6 days", "7 days"]
    bands = [{"band": b, "market_count": band_counts.get(b, 0)} for b in band_order]
    top_market = max(per_market_days.items(), key=lambda kv: (kv[1], kv[0]), default=(None, 0))

    return {
        "markets_in_roster": len(full_market_names),
        "markets_reporting_at_least_once": sum(1 for d in per_market_days.values() if d > 0),
        "compliance_bands": bands,
        "markets_reporting_5_to_6_days": band_counts.get("5-6 days", 0),
        "markets_reporting_all_7_days": band_counts.get("7 days", 0),
        "markets_not_reporting": band_counts.get("0 days", 0),
        "top_reporting_market": top_market[0],
        "top_reporting_market_days": top_market[1],
        "roster_caveat": (
            "Roster = Agmarknet's own registered Madhya Pradesh market list "
            "(from /daily-price-arrival/filters), not derived from which markets "
            "happened to report — every registered market is counted whether or "
            "not it reported this week."
        ),
    }


def compute_top_commodities(current_rows: list, prior_rows: list, top_n: int):
    def group_sum_arrivals(rows):
        totals = defaultdict(float)
        for r in rows:
            if r["arrival_qty"] is not None:
                totals[r["commodity"]] += r["arrival_qty"]
        return totals

    cur_totals = group_sum_arrivals(current_rows)
    prior_totals = group_sum_arrivals(prior_rows)
    total_state_arrivals = sum(cur_totals.values())

    weighted_price_num = defaultdict(float)
    weighted_price_den = defaultdict(float)
    markets_trading = defaultdict(set)
    for r in current_rows:
        if r["modal_price"] is not None and r["arrival_qty"] is not None:
            weighted_price_num[r["commodity"]] += r["modal_price"] * r["arrival_qty"]
            weighted_price_den[r["commodity"]] += r["arrival_qty"]
        if r["market"]:
            markets_trading[r["commodity"]].add(r["market"])

    ranked = sorted(cur_totals.items(), key=lambda kv: -kv[1])[:top_n]
    rows_out = []
    for commodity, value in ranked:
        wow = None
        if prior_totals.get(commodity):
            wow = round((value - prior_totals[commodity]) / prior_totals[commodity] * 100, 1)
        weighted_price = (
            round(weighted_price_num[commodity] / weighted_price_den[commodity], 2)
            if weighted_price_den.get(commodity) else None
        )
        rows_out.append({
            "commodity": commodity,  # raw casing — see run() for why this must not be title-cased here
            "arrival_value": round(value, 2),
            "share_pct_of_state_arrivals": round(value / total_state_arrivals * 100, 1) if total_state_arrivals else None,
            "markets_trading": len(markets_trading.get(commodity, ())),
            "modal_price_weighted": weighted_price,
            "wow_arrival_pct_change": wow,
        })

    # HHI is computed over ALL commodities' shares (not just the top_n slice
    # returned above), matching the standard definition — a truncated HHI
    # would understate concentration.
    hhi = (
        round(sum((v / total_state_arrivals) ** 2 for v in cur_totals.values()), 3)
        if total_state_arrivals else None
    )

    donut_top_n = 8
    donut_ranked = sorted(cur_totals.items(), key=lambda kv: -kv[1])[:donut_top_n]
    donut_slices = [
        {
            "commodity": commodity,
            "arrival_value": round(value, 2),
            "share_pct_of_state_arrivals": round(value / total_state_arrivals * 100, 1) if total_state_arrivals else None,
        }
        for commodity, value in donut_ranked
    ]
    donut_top_total = sum(v for _, v in donut_ranked)
    remaining_value = total_state_arrivals - donut_top_total
    remaining_count = len(cur_totals) - len(donut_ranked)
    if remaining_count > 0 and total_state_arrivals:
        donut_slices.append({
            "commodity": f"Remaining {remaining_count} commodities",
            "arrival_value": round(remaining_value, 2),
            "share_pct_of_state_arrivals": round(remaining_value / total_state_arrivals * 100, 1),
        })

    return {
        "ranking_basis": "arrival_qty",
        "top_commodities": rows_out,
        "total_commodities_traded": len({r["commodity"] for r in current_rows if r["commodity"]}),
        "concentration_hhi": hhi,
        "donut_slices": donut_slices,
    }


def compute_overall_arrivals(current_rows: list, prior_rows: list):
    current_total = sum(r["arrival_qty"] for r in current_rows if r["arrival_qty"] is not None)
    prior_total = sum(r["arrival_qty"] for r in prior_rows if r["arrival_qty"] is not None)
    wow_pct = round((current_total - prior_total) / prior_total * 100, 1) if prior_total else None
    return {
        "total_arrivals": round(current_total, 2),
        "total_arrivals_basis": "arrival_qty",
        "prior_week_total_arrivals": round(prior_total, 2) if prior_rows else None,
        "wow_pct_change": wow_pct,
    }


MIN_TRADING_DAYS_FOR_RANKING = 3  # matches the reference dashboard's thin-trade exclusion rule


def _weighted_avg_price(rows: list, commodity: str):
    """Arrival-weighted mean modal price for one commodity within `rows` —
    same weighting rule as compute_top_commodities, so a period average isn't
    skewed by a low-volume market's price. Falls back to a simple mean if no
    row in the period has both a price and an arrival quantity."""
    num = den = 0.0
    for r in rows:
        if r["commodity"] == commodity and r["modal_price"] is not None and r["arrival_qty"] is not None:
            num += r["modal_price"] * r["arrival_qty"]
            den += r["arrival_qty"]
    if den:
        return round(num / den, 2)
    prices = [r["modal_price"] for r in rows if r["commodity"] == commodity and r["modal_price"] is not None]
    return round(sum(prices) / len(prices), 2) if prices else None


def compute_price_trend(this_week_rows: list, last_week_rows: list, last_month_rows: list,
                         last_year_rows: list, commodities: list):
    """Per commodity: this week's average price vs three comparison periods —
    last week, the same week one month ago, and the same week one year ago.
    Each comparison period is only reported if the source actually returned
    rows for it; a period with zero matching rows stays None rather than
    being silently treated as 0% change."""
    out = []
    for commodity in commodities:
        this_week_avg = _weighted_avg_price(this_week_rows, commodity)

        def period(rows):
            avg = _weighted_avg_price(rows, commodity)
            pct = None
            if avg is not None and this_week_avg is not None and avg != 0:
                pct = round((this_week_avg - avg) / avg * 100, 2)
            return {"avg_price": avg, "pct_change_vs_this_week": pct}

        out.append({
            "commodity": display_commodity_name(commodity),
            "this_week_avg_price": this_week_avg,
            "last_week": period(last_week_rows),
            "last_month_same_week": period(last_month_rows),
            "last_year_same_week": period(last_year_rows),
        })
    return out


def compute_price_bands(current_rows: list, commodity_names: list):
    """Weekly min/max/arrival-weighted-modal price band per commodity — the
    band chart wants the full spread traded during the week (min_price/
    max_price extremes across all rows), not just the single modal figure
    already carried by top_commodities."""
    bands = []
    for name in commodity_names:
        prices = [r["modal_price"] for r in current_rows if r["commodity"] == name and r["modal_price"] is not None]
        mins = [r["min_price"] for r in current_rows if r["commodity"] == name and r["min_price"] is not None]
        maxs = [r["max_price"] for r in current_rows if r["commodity"] == name and r["max_price"] is not None]
        if not prices:
            continue
        bands.append({
            "commodity": display_commodity_name(name),
            "min_price": min(mins) if mins else min(prices),
            "max_price": max(maxs) if maxs else max(prices),
            "modal_price": _weighted_avg_price(current_rows, name),
        })
    return bands


# Onion/potato/tomato plus three more high-volume, price-sensitive
# vegetables confirmed present in the real Agmarknet MP dataset (green
# chilli, cauliflower, cabbage) — raw lowercase casing, matches source rows.
PERISHABLES_WATCHLIST = ["tomato", "onion", "potato", "green chilli", "cauliflower", "cabbage"]
DISTRESS_ARRIVAL_SURGE_PCT = 15.0  # arrival WoW at/above this...
DISTRESS_PRICE_FALL_PCT = -15.0    # ...together with a price WoW at/below this = a glut signal
WATCH_PRICE_FALL_PCT = -8.0        # price falling on its own (no arrival surge) still merits a Watch chip


def compute_perishables(current_rows: list, prior_rows: list):
    """Tomato/onion/potato are tracked separately from the top-10 arrival
    ranking because they drive consumer price sensitivity regardless of
    their arrival-volume rank. The distress composite rule (arrival surge +
    price fall in the same commodity/week) mirrors the classic perishables
    'glut' signal; the two thresholds are simple fixed cutoffs chosen to
    flag a clearly abnormal week, not a tuned/validated model.

    Matching is case-insensitive: Agmarknet's raw commodity casing is
    inconsistent (see display_commodity_name's docstring) — a real pull
    returned 'Onion' for one row shape and would silently produce an empty
    perishables list against a strict lowercase-only match, not because
    onion wasn't traded but because '=='-comparing against a hardcoded
    lowercase name doesn't match a differently-cased raw string."""
    out = []
    for name in PERISHABLES_WATCHLIST:
        cur_val = sum(r["arrival_qty"] for r in current_rows if r["commodity"] and r["commodity"].strip().lower() == name and r["arrival_qty"] is not None)
        prior_val = sum(r["arrival_qty"] for r in prior_rows if r["commodity"] and r["commodity"].strip().lower() == name and r["arrival_qty"] is not None)
        if not cur_val and not prior_val:
            continue  # not traded this cycle — omit rather than fabricate a zero row
        arrival_wow = round((cur_val - prior_val) / prior_val * 100, 1) if prior_val else None
        cur_price = _weighted_avg_price_ci(current_rows, name)
        prior_price = _weighted_avg_price_ci(prior_rows, name)
        price_wow = round((cur_price - prior_price) / prior_price * 100, 1) if (cur_price is not None and prior_price) else None
        distress = arrival_wow is not None and price_wow is not None and arrival_wow >= DISTRESS_ARRIVAL_SURGE_PCT and price_wow <= DISTRESS_PRICE_FALL_PCT
        watch = not distress and price_wow is not None and price_wow <= WATCH_PRICE_FALL_PCT
        out.append({
            "commodity": display_commodity_name(name),
            "arrival_value": round(cur_val, 2),
            "arrival_wow_pct_change": arrival_wow,
            "modal_price": cur_price,
            "prior_modal_price": prior_price,
            "price_wow_pct_change": price_wow,
            "distress_composite": distress,
            "status": "action" if distress else ("watch" if watch else "normal"),
        })
    return out


def compute_reporting_exceptions(market_compliance: dict, current_rows: list):
    """The reference design's 'nil transaction' count is a market yard that
    filed a return explicitly declaring zero arrival for a commodity. The
    live API mixes these into the same row stream as real transactions
    rather than a separate return type, so they're identified here as rows
    with an explicit arrival_qty of 0 (as opposed to a missing/None
    quantity, which just means the field wasn't reported for that row).
    If none show up in a given week's pull, that's a real, computed zero —
    not an unknown — so it's reported as 0, not N/A."""
    band_counts = {b["band"]: b["market_count"] for b in market_compliance["compliance_bands"]}
    partial = band_counts.get("1-2 days", 0) + band_counts.get("3-4 days", 0) + band_counts.get("5-6 days", 0)
    nil_markets = {r["market"] for r in current_rows if r["arrival_qty"] == 0 and r["market"]}
    return {
        "partial_reporting_market_yards": partial,
        "non_reporting_market_yards": band_counts.get("0 days", 0),
        "full_reporting_market_yards": band_counts.get("7 days", 0),
        "nil_transactions_reported": len(nil_markets),
        "nil_transactions_note": (
            "Nil transactions = market yards with at least one row this week explicitly declaring "
            "zero arrival quantity, as distinct from a market that filed no return at all."
        ),
        "note": (
            "Reporting split is by reporting-day coverage: partial = reported on 1-6 of 7 days, "
            "non-reporting = reported on 0 of 7 days. Nil transactions reported is a separate, "
            "narrower count of markets whose return explicitly declared zero arrival."
        ),
    }


ALERT_PRICE_CRITICAL_PCT = 20.0   # WoW modal-price move at/above this = Critical price-volatility alert
ALERT_PRICE_HIGH_PCT = 10.0       # ...at/above this (below Critical) = High
ALERT_NONREPORTING_HIGH_SHARE = 10.0  # % of roster non-reporting at/above this = High rather than Watch


def compute_alerts(fs: dict):
    """Simple deterministic rules engine over numbers already computed
    elsewhere in the fact sheet (never MSP-based — MSP isn't fetched). Fixed
    thresholds, documented at point of use above; this intentionally trades
    sophistication for auditability — every alert traces to one already-
    published number."""
    alerts = []
    pc = fs["price_change"]
    if pc.get("available"):
        for g in pc["top_gainers"] + pc["top_decliners"]:
            mag = abs(g["pct_change"])
            if mag >= ALERT_PRICE_CRITICAL_PCT:
                sev = "Critical"
            elif mag >= ALERT_PRICE_HIGH_PCT:
                sev = "High"
            else:
                continue
            direction = "increase" if g["pct_change"] >= 0 else "decline"
            alerts.append({
                "severity": sev,
                "type": "Price volatility",
                "entity": g["commodity"],
                "trigger": f"Modal price {direction} of {abs(g['pct_change'])}% week-on-week to Rs {g['current_modal_price']:,}",
                "owner": "State Marketing Cell",
            })
    for p in fs.get("perishables", []):
        if p["distress_composite"]:
            alerts.append({
                "severity": "Critical",
                "type": "Distress composite",
                "entity": p["commodity"],
                "trigger": f"Arrival {fmt_pct(p['arrival_wow_pct_change'])} with modal price {fmt_pct(p['price_wow_pct_change'])} in the same week",
                "owner": "Divisional Joint Directors",
            })
    mc = fs["market_compliance"]
    non_reporting_share = (mc["markets_not_reporting"] / mc["markets_in_roster"] * 100) if mc["markets_in_roster"] else 0
    if mc["markets_not_reporting"] > 0:
        sev = "High" if non_reporting_share >= ALERT_NONREPORTING_HIGH_SHARE else "Watch"
        alerts.append({
            "severity": sev,
            "type": "Reporting default",
            "entity": f"{mc['markets_not_reporting']} of {mc['markets_in_roster']} market yards, state-wide",
            "trigger": f"{round(non_reporting_share, 1)}% of registered market yards filed no return this week",
            "owner": "State Marketing Cell",
        })

    severity_rank = {"Critical": 0, "High": 1, "Watch": 2}
    alerts.sort(key=lambda a: severity_rank.get(a["severity"], 3))
    counts = {"Critical": 0, "High": 0, "Watch": 0}
    for a in alerts:
        counts[a["severity"]] = counts.get(a["severity"], 0) + 1
    return {"alerts": alerts, "counts": counts}


ACTION_TARGET_DAYS = {"Critical": 3, "High": 7}  # Critical closes within a working week, High within two


def compute_action_points(alerts_obj: dict, generated_at_iso: str):
    """Action points are derived 1:1 from Critical/High alerts — never a
    separate judgment call. target_date = generated_at + N days, N fixed per
    severity (see ACTION_TARGET_DAYS)."""
    gen = datetime.fromisoformat(generated_at_iso)
    rows = []
    for a in alerts_obj["alerts"]:
        days = ACTION_TARGET_DAYS.get(a["severity"])
        if days is None:
            continue
        target = (gen + timedelta(days=days)).date().isoformat()
        rows.append({
            "priority": a["severity"],
            "action": f"Review {a['type'].lower()} — {a['entity']}: {a['trigger']}.",
            "owner": a["owner"],
            "target_date": target,
        })
    return rows


def compute_coverage(current_rows: list, full_market_names: list):
    """completeness_pct is the same ratio market_compliance already reports
    (markets_reporting_at_least_once / markets_in_roster), surfaced here for
    the coverage bar. records_missing_price counts rows the API returned
    without a modal price — the pipeline has no separate row-validation/
    rejection step, so this is a completeness signal, not a 'rejected in
    validation' count (that concept doesn't exist in this pipeline)."""
    reporting = len({r["market"] for r in current_rows if r["market"]})
    records_missing_price = sum(1 for r in current_rows if r["modal_price"] is None)
    completeness_pct = round(reporting / len(full_market_names) * 100, 1) if full_market_names else None
    return {
        "completeness_pct": completeness_pct,
        "records_processed": len(current_rows),
        "records_missing_price": records_missing_price,
        "note": (
            "completeness_pct = share of registered market yards that reported at least once. "
            "records_missing_price = rows returned by the source API without a modal price value "
            "(not a validation-rejection count — this pipeline performs no separate row-rejection step)."
        ),
    }


def _weighted_avg_price_ci(rows: list, commodity_lower: str):
    """Case-insensitive counterpart to _weighted_avg_price, for the fixed
    perishables watchlist (see compute_perishables) where the raw casing of
    a hardcoded name like 'onion' isn't guaranteed to match the source
    row's casing."""
    num = den = 0.0
    for r in rows:
        if r["commodity"] and r["commodity"].strip().lower() == commodity_lower and r["modal_price"] is not None and r["arrival_qty"] is not None:
            num += r["modal_price"] * r["arrival_qty"]
            den += r["arrival_qty"]
    if den:
        return round(num / den, 2)
    prices = [r["modal_price"] for r in rows if r["commodity"] and r["commodity"].strip().lower() == commodity_lower and r["modal_price"] is not None]
    return round(sum(prices) / len(prices), 2) if prices else None


def compute_price_change(current_rows: list, prior_rows: list):
    def mean_modal(rows):
        sums, counts = defaultdict(float), defaultdict(int)
        for r in rows:
            if r["modal_price"] is not None:
                sums[r["commodity"]] += r["modal_price"]
                counts[r["commodity"]] += 1
        return {k: sums[k] / counts[k] for k in sums}

    def trading_days(rows):
        days = defaultdict(set)
        for r in rows:
            if r["modal_price"] is not None:
                days[r["commodity"]].add(r["arrival_date"])
        return days

    cur = mean_modal(current_rows)
    prior = mean_modal(prior_rows)
    cur_days = trading_days(current_rows)
    prior_days = trading_days(prior_rows)

    common = {
        c for c in (set(cur) & set(prior))
        if len(cur_days.get(c, ())) >= MIN_TRADING_DAYS_FOR_RANKING
        and len(prior_days.get(c, ())) >= MIN_TRADING_DAYS_FOR_RANKING
    }
    excluded_thin_trade = (set(cur) & set(prior)) - common
    if not common:
        return {"available": False, "reason": "no commodity traded on at least 3 days in both weeks", "top_gainers": [], "top_decliners": []}

    changes = {c: round((cur[c] - prior[c]) / prior[c] * 100, 2) for c in common}
    gainers = sorted([c for c in changes if changes[c] > 0], key=lambda c: -changes[c])[:3]
    decliners = sorted([c for c in changes if changes[c] < 0], key=lambda c: changes[c])[:3]

    def to_rows(names):
        return [
            {"commodity": display_commodity_name(c), "pct_change": changes[c], "current_modal_price": round(cur[c], 2), "prior_modal_price": round(prior[c], 2)}
            for c in names
        ]

    return {
        "available": True,
        "top_gainers": to_rows(gainers),
        "top_decliners": to_rows(decliners),
        "min_trading_days_for_ranking": MIN_TRADING_DAYS_FOR_RANKING,
        "commodities_excluded_thin_trade": len(excluded_thin_trade),
    }


# ---------------------------------------------------------------------------
# Narrative — fixed templates with numeric slots (see pipeline.ipynb section
# 11-12 for the full rationale: no free-generation model, so the text can
# never state a number that disagrees with the fact sheet).
# ---------------------------------------------------------------------------

COMMODITY_NAME_HI = {
    "absinthe": "आबसिंथ", "adulsa": "अडूसा", "ajwan": "अजवाइन",
    "akarkara": "अकरकरा", "amaltas": "अमलतास", "amaranthus": "चौलाई",
    "amarbel": "अमरबेल", "ambady/mesta/patson": "अंबाडी", "ambrette seed/muskmallow": "मुश्कदाना",
    "amla(nelli kai)": "आंवला", "amranthas red": "लाल चौलाई", "apple": "सेब",
    "aretha": "रीठा", "asalia": "हलीम", "asgand": "असगंध",
    "ashoka": "अशोक", "ashwagandha": "अश्वगंधा", "asparagus": "शतावरी",
    "baboolphali": "बबूल फली", "bael": "बेल", "bajra(pearl millet/cumbu)": "बाजरा",
    "banana": "केला", "barley(jau)": "जौ", "beans": "सेम",
    "beetroot": "चुकंदर", "behada": "बहेड़ा", "bengal gram(gram)(whole)": "चना",
    "ber(zizyphus/borehannu)": "बेर", "bhindi(ladies finger)": "भिंडी", "bhringraj": "भृंगराज",
    "bhui amlaya": "भूई आंवला", "bitter gourd": "करेला", "black gram(urd beans)(whole)": "उड़द",
    "bottle gourd": "लौकी", "brahmi": "ब्राह्मी", "brinjal": "बैंगन",
    "cabbage": "पत्तागोभी", "calendula": "गेंदा", "capsicum": "शिमला मिर्च",
    "carrot": "गाजर", "castor seed": "अरंडी", "cauliflower": "फूलगोभी",
    "chandrashoor": "चंद्रशूर", "chena": "छेना", "chiaseeds": "चिया बीज",
    "chikoos(sapota)": "चीकू", "chili red": "लाल मिर्च", "chilly capsicum": "मिर्च शिमला",
    "cluster beans": "ग्वार फली", "colacasia": "अरबी", "coriander(leaves)": "हरा धनिया",
    "corriander seed": "धनिया बीज", "cotton": "कपास", "cowpea(lobia/karamani)": "लोबिया",
    "cowpea(veg)": "लोबिया सब्जी", "cucumbar(kheera)": "खीरा", "cummin seed(jeera)": "जीरा",
    "drumstick": "सहजन", "duster beans": "ग्वार फली", "flax seeds": "अलसी",
    "french beans(frasbean)": "फ्रेंच बीन्स", "garlic": "लहसुन", "gataran": "गटारन",
    "giloy": "गिलोय", "ginger(dry)": "सोंठ", "ginger(green)": "अदरक",
    "gokhru": "गोखरू", "gond": "गोंद", "gram raw(chholia)": "छोलिया",
    "grapes": "अंगूर", "green chilli": "हरी मिर्च", "green gram(moong)(whole)": "मूंग",
    "green peas": "हरी मटर", "groundnut": "मूंगफली", "groundnut pods(raw)": "कच्ची मूंगफली फली",
    "guar": "ग्वार", "guava": "अमरूद", "gudmar": "गुड़मार",
    "gur(jaggery)": "गुड़", "harrah": "हरड़", "heena": "मेहंदी",
    "hingot": "हिंगोट", "indian beans(seam)": "सेम", "isabgul(psyllium)": "ईसबगोल",
    "jack fruit(ripe)": "पका कटहल", "jackfruit seed": "कटहल बीज", "jackfruit(green/raw/unripe)": "कच्चा कटहल",
    "jaee": "जई", "jamun": "जामुन", "jamun(narale hannu)": "जामुन",
    "jowar(sorghum)": "ज्वार", "kabuli chana(chickpeas-white)": "काबुली चना", "kalmegh": "कालमेघ",
    "kantakari": "कंटकारी", "karbuja(musk melon)": "खरबूजा", "kaunch": "कौंच",
    "kinnow": "किन्नू", "kodo millet(varagu)": "कोदो", "kulthi(horse gram)": "कुलथी",
    "kutki": "कुटकी", "ladies finger": "भिंडी", "laha": "लाहा",
    "lak(teora)": "लाख", "leafy vegetable": "पत्तेदार सब्जी", "lemon": "नींबू",
    "lentil(masur)(whole)": "मसूर", "lime": "नींबू", "linseed": "अलसी",
    "litchi": "लीची", "little gourd(kundru)": "कुंदरू", "long melon(kakri)": "ककड़ी",
    "mahua": "महुआ", "maize": "मक्का", "mango": "आम",
    "mango(raw-ripe)": "आम (कच्चा-पका)", "marigold(calcutta)": "गेंदा फूल", "methi seeds": "मेथी दाना",
    "methi(leaves)": "मेथी पत्ती", "mousambi(sweet lime)": "मौसमी", "muesli": "मूसली",
    "muleti": "मुलेठी", "muskmelon seeds": "खरबूजा बीज", "mustard": "सरसों",
    "nagarmotha": "नागरमोथा", "neem seed": "नीम बीज", "niger seed(ramtil)": "रामतिल",
    "onion": "प्याज", "onion green": "हरा प्याज", "orange": "संतरा",
    "other green and fresh vegetables": "अन्य हरी सब्जियां", "paddy(common)": "धान", "palash flowers": "पलाश फूल",
    "papaya": "पपीता", "papaya(raw)": "कच्चा पपीता", "pea pod/pea cod/हरी मटर": "हरी मटर फली",
    "pear(marasebu)": "नाशपाती", "peas wet": "हरी मटर", "peas(dry)": "सूखी मटर",
    "pineapple": "अनानास", "plum": "आलूबुखारा", "pointed gourd(parval)": "परवल",
    "pomegranate": "अनार", "potato": "आलू", "pumpkin": "कद्दू",
    "pupadia": "पुपाड़िया", "quinoa": "क्विनोआ", "raddish": "मूली",
    "ragi(finger millet)": "रागी", "rajgir": "राजगिरा", "ramphal": "रामफल",
    "ratanjot": "रतनजोत", "rayee": "राई", "red gram/arhar/tur(whole)": "अरहर",
    "ridgeguard(tori)": "तोरई", "rose(loose))": "गुलाब", "round gourd": "टिंडा",
    "safflower": "कुसुम", "saffron": "केसर", "sahjan leaf": "सहजन पत्ती",
    "same/savi": "सामा", "sanai/sunhemp": "सनई", "seetapal": "सीताफल",
    "sem": "सेम", "sesamum(sesame,gingelly,til)": "तिल", "shankhpushpi": "शंखपुष्पी",
    "snakeguard": "चिचिंडा", "soanf": "सौंफ", "soapnut(antawala/retha)": "रीठा",
    "soha": "सोहा", "soyabean": "सोयाबीन", "spinach": "पालक",
    "sponge gourd": "तोरई", "sunflower/sunflower seed": "सूरजमुखी", "sweet potato": "शकरकंद",
    "tamarind fruit": "इमली", "taramira": "तारामीरा", "taro (arvi) stem": "अरबी डंठल",
    "tender coconut": "नारियल पानी", "tesu flower": "टेसू फूल", "tinda": "टिंडा",
    "tobacco": "तंबाकू", "tomato": "टमाटर", "turmeric": "हल्दी",
    "water melon": "तरबूज", "water chestnut": "सिंघाड़ा", "wheat": "गेहूँ",
    "white muesli": "सफेद मूसली", "wild melon": "जंगली खरबूजा", "basil": "तुलसी",
    "buttery": "बटरी", "dhawai flowers": "धवई फूल", "dried mango": "सूखा आम",
    "gulli": "गुल्ली", "karanja seeds": "करंज बीज", "liquor turmeric": "लीकर हल्दी",
    "mango powder": "आम पाउडर", "nigella": "कलौंजी", "nigella seeds": "कलौंजी बीज",
    "pippali": "पिप्पली", "poppy seeds": "खसखस", "sanay": "सनाय",
    "spikenard": "जटामांसी", "stevia": "स्टीविया", "vadang": "वायविडंग",
    "soybean": "सोयाबीन", "rice": "चावल", "paddy": "धान",
    "gram": "चना", "tur": "अरहर", "lentil": "मसूर",
    "coriander": "धनिया",
}


def commodity_hi(name):
    if not name:
        return name
    return COMMODITY_NAME_HI.get(str(name).strip().lower(), name)


def fmt_pct(value):
    if value is None:
        return "not available (no prior-week data)"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def fmt_pct_hi(value):
    if value is None:
        return "उपलब्ध नहीं (पिछले सप्ताह का डेटा नहीं)"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value}%"


def _fmt_trend_period(label: str, period: dict) -> str:
    if period["avg_price"] is None:
        return f"{label} not available"
    pct = fmt_pct(period["pct_change_vs_this_week"]) if period["pct_change_vs_this_week"] is not None else "n/a"
    return f"{label} Rs {period['avg_price']:,} ({pct})"


def _fmt_trend_period_hi(label: str, period: dict) -> str:
    if period["avg_price"] is None:
        return f"{label} उपलब्ध नहीं"
    pct = fmt_pct_hi(period["pct_change_vs_this_week"]) if period["pct_change_vs_this_week"] is not None else "n/a"
    return f"{label} रु {period['avg_price']:,} ({pct})"


def narrate_english(fs: dict) -> str:
    """Deterministic fallback, written as flowing prose paragraphs (not
    bullets) — this is also the shape the fine-tuned model is trained to
    imitate (self-distillation, see train_lora.py), so the template's own
    output must already look like the target register, not a bulleted
    outline of it."""
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    title = f"Madhya Pradesh Weekly Mandi Summary — {format_date_readable(fs['week_start'])} to {format_date_readable(fs['week_end'])}"

    p1 = (
        f"Total arrivals across Madhya Pradesh markets for the week were {oa['total_arrivals']:,} tonnes, "
        f"{fmt_pct(oa['wow_pct_change'])} against the previous week."
    )
    if tc["top_commodities"]:
        top = tc["top_commodities"][0]
        share = f", {top['share_pct_of_state_arrivals']}% of state arrivals" if top["share_pct_of_state_arrivals"] is not None else ""
        p1 += (
            f" {top['commodity']} was the most-traded commodity by arrival volume at {top['arrival_value']:,} "
            f"tonnes{share}, traded across {top['markets_trading']} markets."
        )
        others = ", ".join(f"{r['commodity']} ({r['arrival_value']:,})" for r in tc["top_commodities"][1:5])
        if others:
            p1 += f" Other leading commodities by arrival volume were {others}."

    if pc.get("available"):
        gainers = "; ".join(f"{g['commodity']} {fmt_pct(g['pct_change'])} to Rs {g['current_modal_price']:,} (from Rs {g['prior_modal_price']:,})" for g in pc["top_gainers"])
        decliners = "; ".join(f"{d['commodity']} {fmt_pct(d['pct_change'])} to Rs {d['current_modal_price']:,} (from Rs {d['prior_modal_price']:,})" for d in pc["top_decliners"])
        p2 = f"The largest week-on-week price increases were {gainers if gainers else 'none'}, while the largest declines were {decliners if decliners else 'none'}."
    else:
        p2 = f"Week-on-week price comparison is not available this week ({pc.get('reason')})."
    pt = fs.get("price_trend", {}).get("commodities", [])
    if pt:
        top_trend = pt[0]
        p2 += (
            f" {top_trend['commodity']}'s average price this week was Rs {top_trend['this_week_avg_price']:,}, "
            f"compared with {_fmt_trend_period('last week', top_trend['last_week'])}, "
            f"{_fmt_trend_period('the same week last month', top_trend['last_month_same_week'])}, and "
            f"{_fmt_trend_period('the same week last year', top_trend['last_year_same_week'])}."
        )

    p3 = (
        f"Of {mc['markets_in_roster']} registered market yards, {mc['markets_reporting_at_least_once']} reported "
        f"at least once this week: {mc['markets_reporting_all_7_days']} markets reported on all 7 days, "
        f"{mc['markets_reporting_5_to_6_days']} reported on 5-6 days, and {mc['markets_not_reporting']} filed no return."
    )
    if mc["top_reporting_market"]:
        p3 += f" {mc['top_reporting_market']} reported the most days, {mc['top_reporting_market_days']} of 7."

    return "\n\n".join([title, p1, p2, p3])


def narrate_hindi(fs: dict) -> str:
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    title = f"मध्य प्रदेश साप्ताहिक मंडी सारांश — {format_date_readable(fs['week_start'])} से {format_date_readable(fs['week_end'])}"

    p1 = (
        f"मध्य प्रदेश की मंडियों में इस सप्ताह कुल आवक {oa['total_arrivals']:,} टन रही, "
        f"जो पिछले सप्ताह की तुलना में {fmt_pct_hi(oa['wow_pct_change'])} है।"
    )
    if tc["top_commodities"]:
        top = tc["top_commodities"][0]
        share = f", राज्य की आवक का {top['share_pct_of_state_arrivals']}%" if top["share_pct_of_state_arrivals"] is not None else ""
        p1 += (
            f" आवक मात्रा के आधार पर {commodity_hi(top['commodity'])} सबसे अधिक कारोबार वाली वस्तु रही "
            f"({top['arrival_value']:,} टन{share}), जिसका कारोबार {top['markets_trading']} मंडियों में हुआ।"
        )
        others = ", ".join(f"{commodity_hi(r['commodity'])} ({r['arrival_value']:,})" for r in tc["top_commodities"][1:5])
        if others:
            p1 += f" अन्य प्रमुख वस्तुएँ रहीं: {others}।"

    if pc.get("available"):
        gainers = "; ".join(f"{commodity_hi(g['commodity'])} {fmt_pct_hi(g['pct_change'])} (रु {g['current_modal_price']:,}, पूर्व रु {g['prior_modal_price']:,})" for g in pc["top_gainers"])
        decliners = "; ".join(f"{commodity_hi(d['commodity'])} {fmt_pct_hi(d['pct_change'])} (रु {d['current_modal_price']:,}, पूर्व रु {d['prior_modal_price']:,})" for d in pc["top_decliners"])
        p2 = f"साप्ताहिक आधार पर सबसे अधिक मूल्य वृद्धि रही {gainers if gainers else 'कोई नहीं'}, जबकि सबसे अधिक गिरावट रही {decliners if decliners else 'कोई नहीं'}।"
    else:
        p2 = "इस सप्ताह मूल्य तुलना उपलब्ध नहीं है (पिछले सप्ताह का डेटा नहीं)।"
    pt = fs.get("price_trend", {}).get("commodities", [])
    if pt:
        top_trend = pt[0]
        p2 += (
            f" {commodity_hi(top_trend['commodity'])} का इस सप्ताह औसत मूल्य रु {top_trend['this_week_avg_price']:,} रहा — तुलना में "
            f"{_fmt_trend_period_hi('पिछला सप्ताह', top_trend['last_week'])}, "
            f"{_fmt_trend_period_hi('पिछले महीने का यही सप्ताह', top_trend['last_month_same_week'])}, और "
            f"{_fmt_trend_period_hi('पिछले वर्ष का यही सप्ताह', top_trend['last_year_same_week'])}।"
        )

    p3 = (
        f"{mc['markets_in_roster']} पंजीकृत मंडियों में से {mc['markets_reporting_at_least_once']} मंडियों ने इस सप्ताह "
        f"कम से कम एक बार रिपोर्ट की: {mc['markets_reporting_all_7_days']} मंडियों ने सातों दिन रिपोर्ट की, "
        f"{mc['markets_reporting_5_to_6_days']} मंडियों ने 5-6 दिन रिपोर्ट की, और {mc['markets_not_reporting']} मंडियों ने कोई रिपोर्ट दर्ज नहीं की।"
    )
    if mc["top_reporting_market"]:
        p3 += f" {mc['top_reporting_market']} मंडी ने सबसे अधिक दिन रिपोर्ट की, सप्ताह के {mc['top_reporting_market_days']} दिन।"

    return "\n\n".join([title, p1, p2, p3])


def _strip_bullet(line: str) -> str:
    return re.sub(r"^[-•*]\s*", "", line.strip())


def _clean_model_paragraphs(text: str) -> str:
    """Normalizes a model draft into blank-line-separated paragraphs: joins
    wrapped lines within a paragraph, strips any stray bullet marker left
    over from the model's pre-paragraph-reformat training data (see
    train_lora.py), and drops empty paragraphs. Works whether the model
    already emits '\\n\\n'-separated paragraphs or one block per line."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    cleaned = []
    for p in paragraphs:
        joined = " ".join(_strip_bullet(l) for l in p.splitlines() if l.strip())
        if joined:
            cleaned.append(joined)
    return "\n\n".join(cleaned)


def _body_only(text: str) -> str:
    """Strips the fixed title line before scoring. The title (state name +
    date range) is never a model/template claim about the fact sheet — it's
    header text appended separately — so it must not be scored against the
    fact sheet's numbers. This mattered in practice: an ISO-format date like
    "2026-07-14" gets misparsed by the number regex as 2026, -7, -14 (the
    hyphens read as minus signs), which showed even a fully correct template
    as only ~94% "verified" until the title was excluded from scoring."""
    parts = text.split("\n\n", 1)
    return parts[1] if len(parts) > 1 else text


# Real timed test on this hardware: a single paraphrase attempt (CPU model
# load + generation) averages ~65-115s; 3 attempts took 232-342s end to end.
# Capped to 1 attempt here — retries were rarely fixing the issue anyway
# (the same near-miss recurred across attempts more often than not) and
# every extra attempt costs another ~1-2 minutes for no reliable gain. On
# any failure this falls straight to the deterministic template, which is
# effectively instant, so this cap trades "maybe succeeds on retry 2 or 3"
# for a much more predictable total refresh time — not a guarantee the
# model succeeds on that one attempt, just a bound on how long it's given
# to try before the guaranteed-accurate template takes over.
NARRATION_MAX_ATTEMPTS = 1


def compose_briefs(fs: dict):
    """Tries a real grounded model draft for each language; falls back to the
    fixed template on any failure (no token, API error, or a draft that
    never passes the gate after retries). This is the only place that
    decides which source produced the final text, and it always records
    which one it was in the returned meta dict — the output files never let
    a reader mistake one for the other silently.

    The model path is narrate_by_paraphrase (see narration.py), not
    narrate_with_model: the deterministic template is generated FIRST
    (guaranteed-correct, every number already attached to its right claim),
    and the model's only job is to reword it, gated on not a single number
    being added/dropped/altered. Testing narrate_with_model's alternative —
    generating prose directly from the raw JSON fact sheet — repeatedly
    produced real, dangerous failures beyond wrong numbers: correctly-
    grounded values attached to the wrong claim (a genuine +47.88% price
    gain narrated as a "decrease"), and different commodities' figures
    mixed into one sentence. Paraphrasing an already-correct passage removes
    the extraction/attribution step that caused those, at the cost of the
    model no longer choosing its own structure — an accepted tradeoff given
    the accuracy-first requirement this whole pipeline is built around."""
    en_title = f"Madhya Pradesh Weekly Mandi Summary — {format_date_readable(fs['week_start'])} to {format_date_readable(fs['week_end'])}"
    hi_title = f"मध्य प्रदेश साप्ताहिक मंडी सारांश — {format_date_readable(fs['week_start'])} से {format_date_readable(fs['week_end'])}"

    def confidence_label(meta):
        if not meta["used_model"]:
            return "High — verified template (formulaic, no model claim risk)"
        if meta["attempts"] <= 1:
            return "High — model draft verified on first attempt"
        return f"Medium — model draft needed {meta['attempts']} attempts before verification passed"

    def spelling_meta(body, language):
        # Checked once more here even for a model draft that already passed
        # this gate inside narrate_with_model — and always checked for the
        # template, which has never been checked before. A template check
        # that ever comes back non-empty means a real bug in the fixed
        # template strings, not a model failure, and is worth surfacing
        # rather than assuming the template is infallible just because it's
        # numerically grounded by construction.
        ok, issues = check_spelling_grammar(body, _slim_fact_sheet(fs), language)
        return {"spelling_grammar_ok": ok, "spelling_grammar_issues": issues}

    # English and Hindi narration run sequentially, one model process at a
    # time. Parallel execution (two concurrent local model processes) was
    # tried and reverted: a real timed test on this machine pushed system
    # memory to 95% load / 0.73GB free — the same danger zone as an earlier
    # near-OOM incident this session — even though a single sequential call
    # runs comfortably. Stability wins over the ~1x-call-duration speedup
    # parallel execution would have bought.
    template_en_body = _body_only(narrate_english(fs))
    template_hi_body = _body_only(narrate_hindi(fs))
    print("Requesting grounded English narration from the model ...", file=sys.stderr)
    model_en, meta_en = narrate_by_paraphrase(template_en_body, "en", max_attempts=NARRATION_MAX_ATTEMPTS)
    print("Requesting grounded Hindi narration from the model ...", file=sys.stderr)
    model_hi, meta_hi = narrate_by_paraphrase(template_hi_body, "hi", max_attempts=NARRATION_MAX_ATTEMPTS)

    if model_en:
        body = _clean_model_paragraphs(model_en)
        english_brief = f"{en_title}\n\n{body}"
    else:
        english_brief = narrate_english(fs)
        body = template_en_body
    meta_en.update(score_grounding(_body_only(english_brief), fs))
    meta_en.update(spelling_meta(body, "en"))
    if not meta_en["spelling_grammar_ok"]:
        print(f"  WARNING: published English text has spelling/grammar issues: "
              f"{meta_en['spelling_grammar_issues']}", file=sys.stderr)
    meta_en["confidence"] = confidence_label(meta_en)

    if model_hi:
        body = _clean_model_paragraphs(model_hi)
        hindi_brief = f"{hi_title}\n\n{body}"
    else:
        hindi_brief = narrate_hindi(fs)
        body = template_hi_body
    meta_hi.update(score_grounding(_body_only(hindi_brief), fs))
    meta_hi.update(spelling_meta(body, "hi"))
    if not meta_hi["spelling_grammar_ok"]:
        print(f"  WARNING: published Hindi text has spelling/grammar issues: "
              f"{meta_hi['spelling_grammar_issues']}", file=sys.stderr)
    meta_hi["confidence"] = confidence_label(meta_hi)

    return english_brief, hindi_brief, {"en": meta_en, "hi": meta_hi}


RAW_ROW_FIELDS = [
    "state", "district", "market", "commodity", "variety", "grade",
    "arrival_date", "min_price", "max_price", "modal_price",
    "arrival_qty", "price_unit", "arrival_unit",
]


def write_raw_dataset(rows: list, dataset_dir: str, week_start: date_cls, week_end: date_cls) -> str:
    """Persists the current week's raw, row-level pull (exactly what came back
    from the live API, flattened — nothing aggregated) as a CSV, independent
    of the computed fact sheet. This is the audit trail: if a number in the
    fact sheet is ever questioned, this file is what it was computed from."""
    import os
    os.makedirs(dataset_dir, exist_ok=True)
    filename = f"madhya_pradesh_{week_start}_to_{week_end}.csv"
    path = os.path.join(dataset_dir, filename)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_ROW_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k) for k in RAW_ROW_FIELDS})
    return path


def _next_snapshot_id(week_end: date_cls, out_dir: str) -> str:
    """Persists a per-ISO-week counter in a small manifest file next to
    --out-dir (survives across separate `python pipeline.py` runs, unlike
    anything held in memory) so regenerating the same week's report
    advances the snapshot suffix: AGM-MP-2026W30-01, then -02 on the next
    regeneration for that same week, etc. Each ISO week gets its own
    independent counter, starting at 01."""
    import os

    iso_year, iso_week, _ = week_end.isocalendar()
    week_key = f"{iso_year}W{iso_week:02d}"
    manifest_dir = os.path.dirname(os.path.normpath(out_dir)) or "."
    manifest_path = os.path.join(manifest_dir, "snapshot_counters.json")

    counters = {}
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            counters = json.load(f)
    counters[week_key] = counters.get(week_key, 0) + 1

    os.makedirs(manifest_dir, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(counters, f, indent=2)

    return f"AGM-MP-{week_key}-{counters[week_key]:02d}"


def archive_snapshot(fact_sheet: dict, english_brief: str, hindi_brief: str, archive_dir: str) -> str:
    """Persists a durable, dated copy of this snapshot's fact sheet + briefs
    — separate from --out-dir, which is the "current" output the live app
    serves and gets OVERWRITTEN on every run. archive_dir instead
    accumulates one folder per (week, snapshot_id), so re-running the
    pipeline never destroys a previously-generated week's record. Keyed by
    snapshot_id (already unique per week+regeneration via
    _next_snapshot_id) rather than just the week range, so multiple
    regenerations of the same week each get their own folder instead of
    colliding."""
    import os

    week_key = f"{fact_sheet['week_start']}_to_{fact_sheet['week_end']}"
    snapshot_dir = os.path.join(archive_dir, week_key, fact_sheet["snapshot_id"])
    os.makedirs(snapshot_dir, exist_ok=True)

    with open(os.path.join(snapshot_dir, "fact_sheet.json"), "w", encoding="utf-8") as f:
        json.dump(fact_sheet, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(snapshot_dir, "brief_en.txt"), "w", encoding="utf-8") as f:
        f.write(english_brief)
    with open(os.path.join(snapshot_dir, "brief_hi.txt"), "w", encoding="utf-8") as f:
        f.write(hindi_brief)

    return snapshot_dir


def run(week_end: date_cls, out_dir: str, dataset_dir: str = None, archive_dir: str = None):
    print(f"Fetching Agmarknet filters (market/district roster) ...", file=sys.stderr)
    filters = fetch_filters()
    market_ids, market_id_to_district, market_id_to_name = mp_roster(filters)
    full_market_names = sorted(market_id_to_name.values())
    print(f"Madhya Pradesh registered markets: {len(market_ids)}", file=sys.stderr)

    week_start = week_end - timedelta(days=6)
    prior_week_end = week_start - timedelta(days=1)
    prior_week_start = prior_week_end - timedelta(days=6)

    # "Same week" comparisons are shifted by whole weeks (28 / 364 days, not a
    # calendar month/year) so the day-of-week alignment is preserved — 364
    # instead of 365 specifically avoids a 1-2 day drift across a leap year.
    last_month_week_end = week_end - timedelta(days=28)
    last_month_week_start = last_month_week_end - timedelta(days=6)
    last_year_week_end = week_end - timedelta(days=364)
    last_year_week_start = last_year_week_end - timedelta(days=6)

    current_days = [week_end - timedelta(days=6 - i) for i in range(7)]
    prior_days = [prior_week_end - timedelta(days=6 - i) for i in range(7)]
    last_month_days = [last_month_week_end - timedelta(days=6 - i) for i in range(7)]
    last_year_days = [last_year_week_end - timedelta(days=6 - i) for i in range(7)]

    all_days = current_days + prior_days + last_month_days + last_year_days
    print(f"Fetching {len(all_days)} days concurrently "
          f"(max {MAX_CONCURRENT_REQUESTS} in flight) ...", file=sys.stderr)
    t0 = time.time()
    all_results = fetch_days(all_days, market_ids, market_id_to_district)
    print(f"Fetched all days in {time.time() - t0:.1f}s", file=sys.stderr)

    def split(days):
        rows, errors = [], []
        for day in days:
            day_rows, err = all_results[day]
            rows.extend(day_rows)
            if err is not None:
                errors.append((str(day), err))
        return rows, errors

    current_rows, current_errors = split(current_days)
    prior_rows, prior_errors = split(prior_days)
    last_month_rows, last_month_errors = split(last_month_days)
    last_year_rows, last_year_errors = split(last_year_days)

    top_commodities = compute_top_commodities(current_rows, prior_rows, TOP_N_COMMODITIES)
    # Raw casing, straight from the source — must match the raw rows'
    # "commodity" field exactly for compute_price_trend's filtering below.
    # Title-casing for display happens after, in top_commodities_display,
    # once nothing downstream needs to match against it anymore.
    top_commodity_names = [c["commodity"] for c in top_commodities["top_commodities"]]

    # Wider ranked-by-arrival-volume list feeding ONLY the price-trend table
    # (up to 30 commodities) — independent of TOP_N_COMMODITIES=10, which
    # still governs the main top-commodities table/donut elsewhere in this
    # fact sheet. Ranked the same way (current week arrival_qty, descending).
    PRICE_TREND_TOP_N = 30
    _price_trend_arrival_totals = defaultdict(float)
    for r in current_rows:
        if r["arrival_qty"] is not None:
            _price_trend_arrival_totals[r["commodity"]] += r["arrival_qty"]
    price_trend_commodity_names = [
        c for c, _ in sorted(_price_trend_arrival_totals.items(), key=lambda kv: -kv[1])[:PRICE_TREND_TOP_N]
    ]
    top_commodities_display = {
        **top_commodities,
        "top_commodities": [
            {**c, "commodity": display_commodity_name(c["commodity"])}
            for c in top_commodities["top_commodities"]
        ],
        "donut_slices": [
            # "Remaining N commodities" is generated label text, not a raw
            # commodity name — must not be run through display_commodity_name.
            {**s, "commodity": s["commodity"] if s["commodity"].startswith("Remaining ") else display_commodity_name(s["commodity"])}
            for s in top_commodities["donut_slices"]
        ],
    }

    fact_sheet = {
        "state": STATE_NAME,
        "week_start": str(week_start),
        "week_end": str(week_end),
        # AGM-MP-<ISO year><ISO week>-<NN> — NN increments each time this
        # same week is regenerated (see _next_snapshot_id), so re-running
        # the pipeline for a week that's already been published is visibly
        # a new snapshot, not silently indistinguishable from the first.
        "snapshot_id": _next_snapshot_id(week_end, out_dir),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "agmarknet.gov.in live API (api.agmarknet.gov.in/v1/prices-and-arrivals/market-report/daily)",
        "fetch_errors": {
            "current_week": current_errors,
            "prior_week": prior_errors,
            "last_month_same_week": last_month_errors,
            "last_year_same_week": last_year_errors,
        },
        "overall_arrivals": compute_overall_arrivals(current_rows, prior_rows),
        "market_compliance": compute_market_compliance(current_rows, full_market_names),
        "top_commodities": top_commodities_display,
        "price_change": compute_price_change(current_rows, prior_rows),
        "price_trend": {
            "definition": (
                "last_week = the preceding 7-day window. last_month_same_week = 28 days before "
                "the current week (same weekday alignment). last_year_same_week = 364 days before "
                "(52 whole weeks, avoids leap-year weekday drift). Each average is arrival-weighted "
                "across all Madhya Pradesh markets."
            ),
            "last_week_range": {"start": str(prior_week_start), "end": str(prior_week_end)},
            "last_month_same_week_range": {"start": str(last_month_week_start), "end": str(last_month_week_end)},
            "last_year_same_week_range": {"start": str(last_year_week_start), "end": str(last_year_week_end)},
            "commodities": compute_price_trend(
                current_rows, prior_rows, last_month_rows, last_year_rows, price_trend_commodity_names
            ),
        },
    }

    if dataset_dir:
        dataset_path = write_raw_dataset(current_rows, dataset_dir, week_start, week_end)
        fact_sheet["raw_dataset_file"] = dataset_path
        print(f"Wrote {len(current_rows)} raw rows to {dataset_path}", file=sys.stderr)

    fact_sheet["coverage"] = compute_coverage(current_rows, full_market_names)
    fact_sheet["price_bands"] = compute_price_bands(current_rows, top_commodity_names)
    fact_sheet["perishables"] = compute_perishables(current_rows, prior_rows)
    fact_sheet["reporting_exceptions"] = compute_reporting_exceptions(fact_sheet["market_compliance"], current_rows)
    fact_sheet["alerts"] = compute_alerts(fact_sheet)
    fact_sheet["action_points"] = compute_action_points(fact_sheet["alerts"], fact_sheet["generated_at"])

    english_brief, hindi_brief, narration_meta = compose_briefs(fact_sheet)
    fact_sheet["narration_meta"] = narration_meta

    import os
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "madhya_pradesh_state_fact_sheet.json"), "w", encoding="utf-8") as f:
        json.dump(fact_sheet, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(out_dir, "madhya_pradesh_weekly_brief_en.txt"), "w", encoding="utf-8") as f:
        f.write(english_brief)
    with open(os.path.join(out_dir, "madhya_pradesh_weekly_brief_hi.txt"), "w", encoding="utf-8") as f:
        f.write(hindi_brief)

    if archive_dir:
        archive_path = archive_snapshot(fact_sheet, english_brief, hindi_brief, archive_dir)
        print(f"Archived snapshot to {archive_path}", file=sys.stderr)

    print(f"Done. Wrote fact sheet + briefs to {out_dir}", file=sys.stderr)
    return fact_sheet


def most_recent_completed_week_end(today: date_cls) -> date_cls:
    """The reporting week is always a fixed Sunday-Saturday calendar week
    (changed from Monday-Sunday per explicit request — the automated job
    runs Sunday night, the night after the week's own Saturday close), not
    a rolling 7-day window ending N days ago — so clicking Refresh on
    different days within the same week yields the SAME week, not a
    shifting date range. Always the most recently completed Saturday before
    today (no extra reporting-lag buffer beyond requiring the week to have
    actually ended): a Sunday-night run therefore covers the Saturday that
    just passed, matching the scheduled job's own timing exactly."""
    days_since_saturday = (today.weekday() - 5) % 7  # Mon=0..Sat=5..Sun=6 -> Sat=0..Fri=6
    if days_since_saturday == 0:
        days_since_saturday = 7  # today IS Saturday — that week isn't over yet, use the one before it
    return today - timedelta(days=days_since_saturday)


def main():
    parser = argparse.ArgumentParser(description="Live Madhya Pradesh weekly mandi summary pipeline")
    parser.add_argument("--week-end", default=None,
                         help="YYYY-MM-DD, defaults to the most recently completed Sunday-Saturday "
                              "calendar week (see most_recent_completed_week_end) — a fixed week, "
                              "not a rolling window, so the same week is returned no matter which "
                              "day of the week you refresh on.")
    parser.add_argument("--out-dir", default="../data/output")
    parser.add_argument("--dataset-dir", default="../dataset",
                         help="Where the current week's raw row-level pull is archived as CSV. "
                              "Pass '' to skip writing it.")
    parser.add_argument("--archive-dir", default="../data/archive",
                         help="Where a durable, dated copy of each snapshot (fact sheet + briefs) is "
                              "kept — unlike --out-dir, never overwritten by a later run. Pass '' to "
                              "skip archiving.")
    args = parser.parse_args()

    week_end = (
        datetime.strptime(args.week_end, "%Y-%m-%d").date()
        if args.week_end else most_recent_completed_week_end(datetime.now(timezone.utc).date())
    )
    run(week_end, args.out_dir, dataset_dir=args.dataset_dir or None, archive_dir=args.archive_dir or None)


if __name__ == "__main__":
    main()
