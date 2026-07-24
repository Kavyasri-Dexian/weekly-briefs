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

from narration import narrate_with_model, score_grounding


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
            "commodity": commodity,
            "this_week_avg_price": this_week_avg,
            "last_week": period(last_week_rows),
            "last_month_same_week": period(last_month_rows),
            "last_year_same_week": period(last_year_rows),
        })
    return out


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
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    lines = [f"Madhya Pradesh Weekly Mandi Summary — {format_date_readable(fs['week_start'])} to {format_date_readable(fs['week_end'])}", ""]
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
    pt = fs.get("price_trend", {}).get("commodities", [])
    if pt:
        top_trend = pt[0]
        lines.append(
            f"{top_trend['commodity']}'s average price this week was "
            f"Rs {top_trend['this_week_avg_price']:,} — vs "
            f"{_fmt_trend_period('last week', top_trend['last_week'])}, "
            f"{_fmt_trend_period('same week last month', top_trend['last_month_same_week'])}, "
            f"{_fmt_trend_period('same week last year', top_trend['last_year_same_week'])}."
        )
    lines.append(
        f"Of {mc['markets_in_roster']} registered market yards, {mc['markets_reporting_at_least_once']} "
        f"reported at least once this week. {mc['markets_reporting_all_7_days']} markets reported on all 7 days, "
        f"{mc['markets_reporting_5_to_6_days']} reported on 5-6 days, and {mc['markets_not_reporting']} filed no return."
    )
    if mc["top_reporting_market"]:
        lines.append(f"{mc['top_reporting_market']} reported the most days ({mc['top_reporting_market_days']} of 7 days).")
    return "\n".join(lines)


def narrate_hindi(fs: dict) -> str:
    oa, mc, tc, pc = fs["overall_arrivals"], fs["market_compliance"], fs["top_commodities"], fs["price_change"]
    lines = [f"मध्य प्रदेश साप्ताहिक मंडी सारांश — {format_date_readable(fs['week_start'])} से {format_date_readable(fs['week_end'])}", ""]
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
    pt = fs.get("price_trend", {}).get("commodities", [])
    if pt:
        top_trend = pt[0]
        lines.append(
            f"{commodity_hi(top_trend['commodity'])} का इस सप्ताह औसत मूल्य "
            f"रु {top_trend['this_week_avg_price']:,} रहा — तुलना में "
            f"{_fmt_trend_period_hi('पिछला सप्ताह', top_trend['last_week'])}, "
            f"{_fmt_trend_period_hi('पिछले महीने का यही सप्ताह', top_trend['last_month_same_week'])}, "
            f"{_fmt_trend_period_hi('पिछले वर्ष का यही सप्ताह', top_trend['last_year_same_week'])}।"
        )
    lines.append(
        f"{mc['markets_in_roster']} पंजीकृत मंडियों में से {mc['markets_reporting_at_least_once']} मंडियों ने इस सप्ताह "
        f"कम से कम एक बार रिपोर्ट की। {mc['markets_reporting_all_7_days']} मंडियों ने सातों दिन रिपोर्ट की, "
        f"{mc['markets_reporting_5_to_6_days']} मंडियों ने 5-6 दिन रिपोर्ट की, और {mc['markets_not_reporting']} मंडियों ने कोई रिपोर्ट दर्ज नहीं की।"
    )
    if mc["top_reporting_market"]:
        lines.append(f"{mc['top_reporting_market']} मंडी ने सबसे अधिक दिन रिपोर्ट की (सप्ताह के {mc['top_reporting_market_days']} दिन)।")
    return "\n".join(lines)


def _strip_bullet(line: str) -> str:
    return re.sub(r"^[-•*]\s*", "", line.strip())


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


def compose_briefs(fs: dict):
    """Tries a real grounded model draft for each language (see narration.py —
    every draft is checked against the fact sheet's own numbers before it's
    accepted); falls back to the fixed template on any failure (no token, API
    error, or a draft that never passes the numeric gate after retries). This
    is the only place that decides which source produced the final text, and
    it always records which one it was in the returned meta dict — the output
    files never let a reader mistake one for the other silently."""
    en_title = f"Madhya Pradesh Weekly Mandi Summary — {format_date_readable(fs['week_start'])} to {format_date_readable(fs['week_end'])}"
    hi_title = f"मध्य प्रदेश साप्ताहिक मंडी सारांश — {format_date_readable(fs['week_start'])} से {format_date_readable(fs['week_end'])}"

    def confidence_label(meta):
        if not meta["used_model"]:
            return "High — verified template (formulaic, no model claim risk)"
        if meta["attempts"] <= 1:
            return "High — model draft verified on first attempt"
        return f"Medium — model draft needed {meta['attempts']} attempts before verification passed"

    print("Requesting grounded English narration from the model ...", file=sys.stderr)
    model_en, meta_en = narrate_with_model(fs, "en")
    if model_en:
        body = "\n".join(_strip_bullet(l) for l in model_en.splitlines() if l.strip())
        english_brief = f"{en_title}\n\n{body}"
    else:
        print(f"  falling back to template ({meta_en['reason']})", file=sys.stderr)
        english_brief = narrate_english(fs)
    meta_en.update(score_grounding(_body_only(english_brief), fs))
    meta_en["confidence"] = confidence_label(meta_en)

    print("Requesting grounded Hindi narration from the model ...", file=sys.stderr)
    model_hi, meta_hi = narrate_with_model(fs, "hi")
    if model_hi:
        body = "\n".join(_strip_bullet(l) for l in model_hi.splitlines() if l.strip())
        hindi_brief = f"{hi_title}\n\n{body}"
    else:
        print(f"  falling back to template ({meta_hi['reason']})", file=sys.stderr)
        hindi_brief = narrate_hindi(fs)
    meta_hi.update(score_grounding(_body_only(hindi_brief), fs))
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


def run(week_end: date_cls, out_dir: str, dataset_dir: str = None):
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
    top_commodity_names = [c["commodity"] for c in top_commodities["top_commodities"]]

    fact_sheet = {
        "state": STATE_NAME,
        "week_start": str(week_start),
        "week_end": str(week_end),
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
        "top_commodities": top_commodities,
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
                current_rows, prior_rows, last_month_rows, last_year_rows, top_commodity_names[:5]
            ),
        },
    }

    if dataset_dir:
        dataset_path = write_raw_dataset(current_rows, dataset_dir, week_start, week_end)
        fact_sheet["raw_dataset_file"] = dataset_path
        print(f"Wrote {len(current_rows)} raw rows to {dataset_path}", file=sys.stderr)

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

    print(f"Done. Wrote fact sheet + briefs to {out_dir}", file=sys.stderr)
    return fact_sheet


def main():
    parser = argparse.ArgumentParser(description="Live Madhya Pradesh weekly mandi summary pipeline")
    parser.add_argument("--week-end", default=None, help="YYYY-MM-DD, defaults to yesterday (today's data is usually incomplete)")
    parser.add_argument("--out-dir", default="../data/output")
    parser.add_argument("--dataset-dir", default="../dataset",
                         help="Where the current week's raw row-level pull is archived as CSV. "
                              "Pass '' to skip writing it.")
    args = parser.parse_args()

    week_end = (
        datetime.strptime(args.week_end, "%Y-%m-%d").date()
        if args.week_end else (datetime.now(timezone.utc).date() - timedelta(days=1))
    )
    run(week_end, args.out_dir, dataset_dir=args.dataset_dir or None)


if __name__ == "__main__":
    main()
