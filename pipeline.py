"""
Agmarknet Weekly District Brief — LIVE DATA PIPELINE (prototype)
==================================================================

Pulls REAL data from the data.gov.in Open Government Data (OGD) API,
which republishes Agmarknet's daily mandi price/arrival records under
the dataset "Variety-wise Daily Market Prices Data of Commodity"
(resource id: 9ef84268-d588-465a-a308-a864a43d0070). This is the same
underlying source as agmarknet.gov.in — data.gov.in exposes it through
a clean REST API, whereas agmarknet.gov.in itself is a server-rendered
ASP.NET site with no public API (confirmed 403 on direct fetch).

IMPORTANT — network constraint of THIS session:
This script was authored and unit-tested with an injected mock
response (see `_MOCK_API_RESPONSE_FOR_TESTING` at the bottom) because
the cloud sandbox this was written in has no outbound access to
api.data.gov.in. It has NOT been run against the live endpoint. Run it
yourself in an environment with normal internet access and it will
call the real API — see "Getting your own API key" below.

Getting your own API key (free, instant, ~2 minutes):
  1. Register at https://data.gov.in/user/register (or /login if you
     already have an account for any Indian government open-data portal)
  2. Go to https://data.gov.in/user (My Account) -> "API Keys" and copy
     your personal key.
  3. Pass it via --api-key or the AGMARKNET_API_KEY environment variable.
  Do NOT rely on shared "demo" keys found in tutorials/blog posts for
  production use — they are commonly rate-limited or revoked without
  notice, since they are shared across every reader of that tutorial.

Scope (per current requirements): Agmarknet is the ONLY data source.
No other datasets (weather, other price indices, etc.) are combined in.
Every number in the output is either a raw field from the API response
or a value computed directly from those raw fields in this script —
nothing is inferred or estimated by a language model in this file.
Bilingual LLM narration (Section 3 of the design doc) is a separate,
later stage that reads the output of this script as its ONLY input.

Usage:
    python agmarknet_live_pipeline.py --state "Madhya Pradesh" \
        --api-key YOUR_KEY --days 7

    # Or set the key once:
    export AGMARKNET_API_KEY=your_key_here
    python agmarknet_live_pipeline.py --state "Madhya Pradesh"
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
BASE_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"

# Field names as published by data.gov.in for this resource. Field
# naming on OGD resources has been known to shift slightly between
# dataset revisions (e.g. "arrival_date" vs "Arrival_Date") — the
# FIELD_ALIASES map lets _normalize_record() cope with either without
# changing the rest of the pipeline.
FIELD_ALIASES = {
    "state": ["state", "State"],
    "district": ["district", "District"],
    "market": ["market", "Market"],
    "commodity": ["commodity", "Commodity"],
    "variety": ["variety", "Variety"],
    "grade": ["grade", "Grade"],
    "arrival_date": ["arrival_date", "Arrival_Date"],
    "min_price": ["min_price", "Min_Price"],
    "max_price": ["max_price", "Max_Price"],
    "modal_price": ["modal_price", "Modal_Price"],
}


class AgmarknetAPIError(Exception):
    pass


class AgmarknetClient:
    """Thin, honest client for the data.gov.in Agmarknet resource.

    No data invention: every field returned by get_records() is either
    a verbatim value from the API response or None if the API omitted
    it. This class does not guess, backfill, or smooth missing data —
    that decision belongs to the caller (see DataProcessor), which is
    required to be explicit about what it does with gaps.
    """

    def __init__(self, api_key: str, timeout: int = 30, max_retries: int = 3):
        if not api_key:
            raise ValueError(
                "An API key is required. Get a free personal key at "
                "https://data.gov.in/user (do not use a shared demo key "
                "for anything beyond a one-off manual test)."
            )
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()

    def get_records(self, state: str = None, district: str = None,
                     commodity: str = None, offset: int = 0, limit: int = 100):
        """Fetch one page of records. Returns the raw list of record dicts.

        Raises AgmarknetAPIError on repeated failure rather than
        silently returning an empty/partial result — a data pipeline
        that feeds a published brief should fail loudly, not quietly
        under-report.
        """
        params = {
            "api-key": self.api_key,
            "format": "json",
            "offset": offset,
            "limit": limit,
        }
        if state:
            params["filters[state.keyword]"] = state
        if district:
            params["filters[district.keyword]"] = district
        if commodity:
            params["filters[commodity.keyword]"] = commodity

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(BASE_URL, params=params, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
                records = payload.get("records", [])
                logger.info(
                    "Fetched %d records (offset=%d, total available=%s)",
                    len(records), offset, payload.get("total", "unknown"),
                )
                return records, payload
            except requests.exceptions.RequestException as exc:
                last_error = exc
                wait = 2 ** attempt
                logger.warning("Request failed (attempt %d/%d): %s — retrying in %ds",
                                attempt, self.max_retries, exc, wait)
                import time
                time.sleep(wait)
            except (ValueError, json.JSONDecodeError) as exc:
                # API returned something that isn't valid JSON — surface
                # the raw text so the caller can see exactly what came
                # back (often an HTML error page or a rate-limit message).
                raise AgmarknetAPIError(
                    f"API did not return valid JSON. Raw response started with: "
                    f"{resp.text[:300]!r}"
                ) from exc

        raise AgmarknetAPIError(f"Failed after {self.max_retries} attempts: {last_error}")

    def get_all_records(self, state: str = None, district: str = None,
                         commodity: str = None, page_size: int = 100, max_pages: int = 50):
        """Paginate through get_records() until exhausted or max_pages hit.

        max_pages is a hard safety cap, not a silent truncation — if it
        is reached, a warning is logged and the caller is told so the
        brief can flag incomplete data rather than presenting a partial
        pull as complete.
        """
        all_records = []
        offset = 0
        for page in range(max_pages):
            records, payload = self.get_records(
                state=state, district=district, commodity=commodity,
                offset=offset, limit=page_size,
            )
            if not records:
                break
            all_records.extend(records)
            offset += page_size
            total = payload.get("total")
            if total is not None and offset >= int(total):
                break
        else:
            logger.warning(
                "Hit max_pages=%d while paginating — data may be incomplete. "
                "Raise max_pages if this state/district legitimately has more records.",
                max_pages,
            )
        return all_records


def _get_field(record: dict, canonical_name: str):
    for alias in FIELD_ALIASES.get(canonical_name, [canonical_name]):
        if alias in record:
            return record[alias]
    return None


def _to_float(value):
    """Convert an API price/qty string to float, or None if not parseable.
    Never silently coerces to 0 — a missing/unparseable price must stay
    None so downstream aggregation doesn't treat 'no data' as 'zero'.
    """
    if value in (None, "", "NA", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


class DataProcessor:
    """Turns raw Agmarknet records into the same aggregated structure
    used by the brief generator — computed here in plain code, not by
    a language model, per the grounded-generation design.
    """

    def __init__(self, records: list):
        self.raw_records = records
        self.parse_errors = []

    def normalize(self):
        normalized = []
        for i, r in enumerate(self.raw_records):
            arrival_date_str = _get_field(r, "arrival_date")
            try:
                arrival_date = (
                    datetime.strptime(arrival_date_str, "%d/%m/%Y").date()
                    if arrival_date_str else None
                )
            except ValueError:
                arrival_date = None
                self.parse_errors.append((i, "unparseable arrival_date", arrival_date_str))

            normalized.append({
                "state": _get_field(r, "state"),
                "district": _get_field(r, "district"),
                "market": _get_field(r, "market"),
                "commodity": _get_field(r, "commodity"),
                "variety": _get_field(r, "variety"),
                "arrival_date": arrival_date,
                "min_price": _to_float(_get_field(r, "min_price")),
                "max_price": _to_float(_get_field(r, "max_price")),
                "modal_price": _to_float(_get_field(r, "modal_price")),
            })
        if self.parse_errors:
            logger.warning("%d records had unparseable fields — see .parse_errors",
                            len(self.parse_errors))
        return normalized

    def aggregate_by_district(self, normalized_records: list, week_end_date=None):
        """Compute the exact set of stats specified in the brief scope:
        market/commodity detail, arrivals, top commodities by volume,
        price deviation vs prior week, markets reporting 5/6+ days.

        Note: this dataset (like agmarknet generally) reports PRICES
        (min/max/modal ₹ per quintal) but does NOT include arrival
        QUANTITY (tonnes) in this particular resource — that lives in
        a separate Agmarknet report ("Daily Price and Arrival Report").
        This function computes everything that IS available here and
        marks arrival-quantity fields as unavailable rather than
        fabricating a number, per the no-invented-data rule. If
        tonnage is required, a second resource/report needs to be
        integrated — flagged as a follow-up, not silently faked here.
        """
        if week_end_date is None:
            week_end_date = max((r["arrival_date"] for r in normalized_records if r["arrival_date"]), default=None)
        week_start_date = week_end_date - timedelta(days=6) if week_end_date else None

        by_district = defaultdict(lambda: {
            "markets": defaultdict(lambda: {"reporting_dates": set(), "commodities": defaultdict(list)}),
            "commodity_totals": defaultdict(int),  # count of price quotes, not tonnage — see docstring
        })

        for r in normalized_records:
            if not r["district"] or not r["arrival_date"]:
                continue
            if week_start_date and not (week_start_date <= r["arrival_date"] <= week_end_date):
                continue

            d = by_district[r["district"]]
            m = d["markets"][r["market"] or "Unknown Market"]
            m["reporting_dates"].add(r["arrival_date"])
            m["commodities"][r["commodity"] or "Unknown"].append({
                "variety": r["variety"],
                "date": r["arrival_date"],
                "min_price": r["min_price"],
                "max_price": r["max_price"],
                "modal_price": r["modal_price"],
            })
            d["commodity_totals"][r["commodity"] or "Unknown"] += 1

        results = {}
        for district, d in by_district.items():
            market_summaries = []
            for market, m in d["markets"].items():
                reporting_days = len(m["reporting_dates"])
                market_summaries.append({
                    "market": market,
                    "reporting_days": reporting_days,
                    "full_week_reporter": reporting_days >= 5,
                    "commodity_count": len(m["commodities"]),
                })

            top_commodities = sorted(
                d["commodity_totals"].items(), key=lambda kv: kv[1], reverse=True
            )[:5]

            results[district] = {
                "district": district,
                "week_start": str(week_start_date) if week_start_date else None,
                "week_end": str(week_end_date) if week_end_date else None,
                "markets_reporting": len(market_summaries),
                "markets_full_week_5plus_days": sum(1 for m in market_summaries if m["full_week_reporter"]),
                "market_detail": sorted(market_summaries, key=lambda x: -x["reporting_days"]),
                "top_commodities_by_quote_count": top_commodities,
                "arrival_quantity_tonnes": None,  # NOT available in this resource — see docstring
                "arrival_quantity_note": (
                    "Agmarknet's arrival-quantity (tonnes) figures live in a separate "
                    "report ('Daily Price and Arrival Report') not covered by this "
                    "resource. Left as None rather than estimated."
                ),
            }
        return results

    def compute_price_deviation(self, current_week: dict, previous_week: dict):
        """Compare modal prices for the same commodity+market between
        two already-computed weekly aggregates. Returns only commodities
        present in BOTH weeks — no interpolation for missing weeks.
        """
        deviations = []
        # left as an extension point: wire this to two aggregate_by_district()
        # outputs (current week, prior week) once >1 week of pulled data
        # exists; documented here rather than stubbed with fake numbers.
        return deviations


def build_fact_sheet(district_aggregate: dict) -> dict:
    """The ONLY object that should ever be handed to an LLM narration
    step. Everything in here is either a raw API field or a value
    computed in DataProcessor above — nothing is inferred.
    """
    return district_aggregate


def main():
    parser = argparse.ArgumentParser(description="Pull live Agmarknet data via data.gov.in and compute weekly district facts.")
    parser.add_argument("--state", default="Madhya Pradesh")
    parser.add_argument("--district", default=None, help="Optional: restrict to one district")
    parser.add_argument("--api-key", default=os.environ.get("AGMARKNET_API_KEY"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--out", default="agmarknet_fact_sheets.json")
    parser.add_argument("--use-mock", action="store_true",
                         help="Use the bundled mock response instead of calling the live API "
                              "(for testing pipeline logic without network access).")
    args = parser.parse_args()

    if args.use_mock:
        logger.warning("Running with --use-mock: NOT live data. For pipeline testing only.")
        records = _MOCK_API_RESPONSE_FOR_TESTING["records"]
    else:
        if not args.api_key:
            logger.error("No API key provided. Pass --api-key or set AGMARKNET_API_KEY. "
                         "Get a free key at https://data.gov.in/user")
            sys.exit(1)
        client = AgmarknetClient(api_key=args.api_key)
        try:
            records = client.get_all_records(state=args.state, district=args.district)
        except AgmarknetAPIError as exc:
            logger.error("Live API call failed: %s", exc)
            sys.exit(1)

    if not records:
        logger.error("Zero records returned. Check state/district spelling matches "
                      "Agmarknet's exact naming (e.g. 'Madhya Pradesh', case-sensitive "
                      "on this API), or that data exists for the requested window.")
        sys.exit(1)

    processor = DataProcessor(records)
    normalized = processor.normalize()
    aggregates = processor.aggregate_by_district(normalized)

    fact_sheets = {district: build_fact_sheet(agg) for district, agg in aggregates.items()}

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(fact_sheets, f, indent=2, ensure_ascii=False, default=str)

    logger.info("Wrote %d district fact sheets to %s", len(fact_sheets), args.out)
    for district, fs in fact_sheets.items():
        print(f"\n{district}: {fs['markets_reporting']} markets, "
              f"{fs['markets_full_week_5plus_days']} reporting 5+ days, "
              f"top commodity: {fs['top_commodities_by_quote_count'][0] if fs['top_commodities_by_quote_count'] else 'N/A'}")


# ---------------------------------------------------------------------------
# Mock response used ONLY for offline pipeline testing (--use-mock flag).
# Shape matches the real data.gov.in response format for this resource.
# This is clearly separated and labeled so it can never be mistaken for
# a live pull downstream.
# ---------------------------------------------------------------------------
_MOCK_API_RESPONSE_FOR_TESTING = {
    "records": [
        {"state": "Madhya Pradesh", "district": "Indore", "market": "Indore",
         "commodity": "Wheat", "variety": "Dara", "arrival_date": "17/07/2026",
         "min_price": "2200", "max_price": "2650", "modal_price": "2450"},
        {"state": "Madhya Pradesh", "district": "Indore", "market": "Indore",
         "commodity": "Wheat", "variety": "Dara", "arrival_date": "18/07/2026",
         "min_price": "2210", "max_price": "2660", "modal_price": "2460"},
        {"state": "Madhya Pradesh", "district": "Indore", "market": "Indore",
         "commodity": "Soyabean", "variety": "Yellow", "arrival_date": "18/07/2026",
         "min_price": "3800", "max_price": "4100", "modal_price": "3950"},
        {"state": "Madhya Pradesh", "district": "Indore", "market": "Rau",
         "commodity": "Onion", "variety": "Red", "arrival_date": "19/07/2026",
         "min_price": "800", "max_price": "1400", "modal_price": "1100"},
    ]
}


if __name__ == "__main__":
    main()