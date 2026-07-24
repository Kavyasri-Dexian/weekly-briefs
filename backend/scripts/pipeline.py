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
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, date as date_cls, timezone

import requests

API_BASE = "https://api.agmarknet.gov.in/v1"
STATE_ID = 19  # Madhya Pradesh, per /daily-price-arrival/filters
STATE_NAME = "Madhya Pradesh"
TOP_N_COMMODITIES = 10
REQUEST_TIMEOUT = 30
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def fetch_filters():
    r = requests.get(f"{API_BASE}/daily-price-arrival/filters", headers=HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()["data"]


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
            wait = 2 ** attempt
            print(f"  [warn] {day} attempt {attempt}/{retries} failed: {exc} — retrying in {wait}s", file=sys.stderr)
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
            "commodity": commodity,
            "arrival_value": round(value, 2),
            "share_pct_of_state_arrivals": round(value / total_state_arrivals * 100, 1) if total_state_arrivals else None,
            "markets_trading": len(markets_trading.get(commodity, ())),
            "modal_price_weighted": weighted_price,
            "wow_arrival_pct_change": wow,
        })

    return {
        "ranking_basis": "arrival_qty",
        "top_commodities": rows_out,
        "total_commodities_traded": len({r["commodity"] for r in current_rows if r["commodity"]}),
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
            {"commodity": c, "pct_change": changes[c], "current_modal_price": round(cur[c], 2), "prior_modal_price": round(prior[c], 2)}
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
    "wheat": "गेहूँ", "soyabean": "सोयाबीन", "soybean": "सोयाबीन", "onion": "प्याज",
    "garlic": "लहसुन", "tomato": "टमाटर", "gram": "चना", "maize": "मक्का",
    "mustard": "सरसों", "potato": "आलू", "tur": "तुअर", "paddy": "धान",
    "lentil": "मसूर", "coriander": "धनिया", "rice": "चावल",
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


def narrate_english(fs: dict) -> str:
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    lines = [f"Madhya Pradesh Weekly Mandi Summary — {fs['week_start']} to {fs['week_end']}", ""]
    lines.append(
        f"Total arrivals across Madhya Pradesh markets for the week were "
        f"{oa['total_arrivals']:,} tonnes, a change of {fmt_pct(oa['wow_pct_change'])} over the previous week."
    )
    if tc["top_commodities"]:
        top = tc["top_commodities"][0]
        share = f", {top['share_pct_of_state_arrivals']}% of state arrivals" if top["share_pct_of_state_arrivals"] is not None else ""
        lines.append(
            f"{top['commodity']} was the most-traded commodity by arrival volume "
            f"({top['arrival_value']:,} tonnes{share}), traded across {top['markets_trading']} markets."
        )
        others = ", ".join(f"{r['commodity']} ({r['arrival_value']:,})" for r in tc["top_commodities"][1:5])
        if others:
            lines.append(f"Other leading commodities by arrival volume: {others}.")
    if pc.get("available"):
        gainers = "; ".join(f"{g['commodity']} {fmt_pct(g['pct_change'])} (Rs {g['current_modal_price']:,} from Rs {g['prior_modal_price']:,})" for g in pc["top_gainers"])
        decliners = "; ".join(f"{d['commodity']} {fmt_pct(d['pct_change'])} (Rs {d['current_modal_price']:,} from Rs {d['prior_modal_price']:,})" for d in pc["top_decliners"])
        lines.append(f"Largest week-on-week price increases: {gainers if gainers else 'none'}.")
        lines.append(f"Largest week-on-week price decreases: {decliners if decliners else 'none'}.")
    else:
        lines.append(f"Week-on-week price comparison is not available this week ({pc.get('reason')}).")
    lines.append(
        f"Of {mc['markets_in_roster']} registered market yards, {mc['markets_reporting_at_least_once']} "
        f"reported at least once this week. {mc['markets_reporting_all_7_days']} markets reported on all 7 days, "
        f"{mc['markets_reporting_5_to_6_days']} reported on 5-6 days, and {mc['markets_not_reporting']} filed no return."
    )
    if mc["top_reporting_market"]:
        lines.append(f"{mc['top_reporting_market']} reported the most days ({mc['top_reporting_market_days']} of the week).")
    return "\n".join(lines)


def narrate_hindi(fs: dict) -> str:
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    lines = [f"मध्य प्रदेश साप्ताहिक मंडी सारांश — {fs['week_start']} से {fs['week_end']}", ""]
    lines.append(
        f"मध्य प्रदेश की मंडियों में इस सप्ताह कुल आवक {oa['total_arrivals']:,} टन रही, "
        f"जो पिछले सप्ताह की तुलना में {fmt_pct_hi(oa['wow_pct_change'])} है।"
    )
    if tc["top_commodities"]:
        top = tc["top_commodities"][0]
        share = f", राज्य की आवक का {top['share_pct_of_state_arrivals']}%" if top["share_pct_of_state_arrivals"] is not None else ""
        lines.append(
            f"आवक मात्रा के आधार पर {commodity_hi(top['commodity'])} सबसे अधिक कारोबार वाली वस्तु रही "
            f"({top['arrival_value']:,} टन{share}), जिसका कारोबार {top['markets_trading']} मंडियों में हुआ।"
        )
        others = ", ".join(f"{commodity_hi(r['commodity'])} ({r['arrival_value']:,})" for r in tc["top_commodities"][1:5])
        if others:
            lines.append(f"आवक मात्रा के आधार पर अन्य प्रमुख वस्तुएँ: {others}.")
    if pc.get("available"):
        gainers = "; ".join(f"{commodity_hi(g['commodity'])} {fmt_pct_hi(g['pct_change'])} (रु {g['current_modal_price']:,}, पूर्व रु {g['prior_modal_price']:,})" for g in pc["top_gainers"])
        decliners = "; ".join(f"{commodity_hi(d['commodity'])} {fmt_pct_hi(d['pct_change'])} (रु {d['current_modal_price']:,}, पूर्व रु {d['prior_modal_price']:,})" for d in pc["top_decliners"])
        lines.append(f"साप्ताहिक आधार पर सबसे अधिक मूल्य वृद्धि: {gainers if gainers else 'कोई नहीं'}.")
        lines.append(f"साप्ताहिक आधार पर सबसे अधिक मूल्य गिरावट: {decliners if decliners else 'कोई नहीं'}.")
    else:
        lines.append("इस सप्ताह मूल्य तुलना उपलब्ध नहीं है (पिछले सप्ताह का डेटा नहीं)।")
    lines.append(
        f"{mc['markets_in_roster']} पंजीकृत मंडियों में से {mc['markets_reporting_at_least_once']} मंडियों ने इस सप्ताह "
        f"कम से कम एक बार रिपोर्ट की। {mc['markets_reporting_all_7_days']} मंडियों ने सातों दिन रिपोर्ट की, "
        f"{mc['markets_reporting_5_to_6_days']} मंडियों ने 5-6 दिन रिपोर्ट की, और {mc['markets_not_reporting']} मंडियों ने कोई रिपोर्ट दर्ज नहीं की।"
    )
    if mc["top_reporting_market"]:
        lines.append(f"{mc['top_reporting_market']} मंडी ने सबसे अधिक दिन रिपोर्ट की (सप्ताह के {mc['top_reporting_market_days']} दिन)।")
    return "\n".join(lines)


def run(week_end: date_cls, out_dir: str):
    print(f"Fetching Agmarknet filters (market/district roster) ...", file=sys.stderr)
    filters = fetch_filters()
    market_ids, market_id_to_district, market_id_to_name = mp_roster(filters)
    full_market_names = sorted(market_id_to_name.values())
    print(f"Madhya Pradesh registered markets: {len(market_ids)}", file=sys.stderr)

    week_start = week_end - timedelta(days=6)
    prior_week_end = week_start - timedelta(days=1)
    prior_week_start = prior_week_end - timedelta(days=6)

    current_days = [week_end - timedelta(days=6 - i) for i in range(7)]
    prior_days = [prior_week_end - timedelta(days=6 - i) for i in range(7)]

    print(f"Fetching {len(current_days) + len(prior_days)} days concurrently "
          f"(max {MAX_CONCURRENT_REQUESTS} in flight) ...", file=sys.stderr)
    t0 = time.time()
    all_results = fetch_days(current_days + prior_days, market_ids, market_id_to_district)
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

    fact_sheet = {
        "state": STATE_NAME,
        "week_start": str(week_start),
        "week_end": str(week_end),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "agmarknet.gov.in live API (api.agmarknet.gov.in/v1/prices-and-arrivals/market-report/daily)",
        "fetch_errors": {"current_week": current_errors, "prior_week": prior_errors},
        "overall_arrivals": compute_overall_arrivals(current_rows, prior_rows),
        "market_compliance": compute_market_compliance(current_rows, full_market_names),
        "top_commodities": compute_top_commodities(current_rows, prior_rows, TOP_N_COMMODITIES),
        "price_change": compute_price_change(current_rows, prior_rows),
    }

    english_brief = narrate_english(fact_sheet)
    hindi_brief = narrate_hindi(fact_sheet)

    import os
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "madhya_pradesh_state_fact_sheet.json"), "w", encoding="utf-8") as f:
        json.dump(fact_sheet, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(out_dir, "madhya_pradesh_weekly_brief_en.txt"), "w", encoding="utf-8") as f:
        f.write(english_brief)
    with open(os.path.join(out_dir, "madhya_pradesh_weekly_brief_hi.txt"), "w", encoding="utf-8") as f:
        f.write(hindi_brief)

    print(f"Done. Wrote fact sheet + briefs to {out_dir}", file=sys.stderr)
    return fact_sheet


def main():
    parser = argparse.ArgumentParser(description="Live Madhya Pradesh weekly mandi summary pipeline")
    parser.add_argument("--week-end", default=None, help="YYYY-MM-DD, defaults to yesterday (today's data is usually incomplete)")
    parser.add_argument("--out-dir", default="../data/output")
    args = parser.parse_args()

    week_end = (
        datetime.strptime(args.week_end, "%Y-%m-%d").date()
        if args.week_end else (datetime.now(timezone.utc).date() - timedelta(days=1))
    )
    run(week_end, args.out_dir)


if __name__ == "__main__":
    main()
