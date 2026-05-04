"""Google Ads → Parquet fetcher for the BEV Search Monitor.

Fetches monthly historical search volumes for each (market × keyword) pair via
KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics.

Run:
    python update.py            # full refresh
    python update.py --markets DE,UK
    python update.py --dry-run  # validate config + auth, no API calls

Output: data/search_volumes.parquet
        columns = [country_code, brand, keyword, year, month, search_volume,
                   competition, low_top_of_page_bid_micros, high_top_of_page_bid_micros]
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, TypeVar

import pandas as pd
import yaml

import config

T = TypeVar("T")


def _retry_on_rate_limit(call: Callable[[], T], max_attempts: int = 6,
                         base_delay: float = 8.0) -> T:
    """Retry a Google Ads API call on RESOURCE_EXHAUSTED with exponential backoff.

    Basic Access tier rate-limits GenerateKeywordHistoricalMetrics to roughly
    one call every few seconds; bursts trip 429s. We sleep 8, 16, 32, 64, 128s.
    """
    from google.api_core.exceptions import ResourceExhausted

    for attempt in range(max_attempts):
        try:
            return call()
        except ResourceExhausted:
            if attempt == max_attempts - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[fetcher]   ⚠ rate-limited, sleeping {delay:.0f}s "
                  f"(attempt {attempt + 1}/{max_attempts})…")
            time.sleep(delay)
    raise RuntimeError("unreachable")


MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]
MONTH_NAME_TO_INT = {name: i + 1 for i, name in enumerate(MONTH_NAMES)}


def normalize_keyword(s: str) -> str:
    """Match Google Ads' own normalization: lowercase, strip punctuation,
    collapse whitespace. Without this, e.g. 'smart #1' (sent) vs 'smart 1'
    (returned by Google) won't match."""
    s = s.lower()
    s = re.sub(r"[#!?.\-,'\":°]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _month_to_int(m) -> int:
    """Google Ads' MonthOfYearEnum starts at UNSPECIFIED=0, UNKNOWN=1, JAN=2 …
    Map back to calendar 1..12. Accepts the proto enum value or its .name."""
    name = getattr(m, "name", None)
    if name in MONTH_NAME_TO_INT:
        return MONTH_NAME_TO_INT[name]
    # fallback: enum int with the +1 offset
    return int(m) - 1

# google-ads imports are deferred so --dry-run works without credentials
def _load_client():
    from google.ads.googleads.client import GoogleAdsClient
    creds = _read_credentials()
    return GoogleAdsClient.load_from_dict({
        "developer_token":   creds["developer_token"],
        "client_id":         creds["client_id"],
        "client_secret":     creds["client_secret"],
        "refresh_token":     creds["refresh_token"],
        "login_customer_id": creds["login_customer_id"],
        "use_proto_plus":    creds.get("use_proto_plus", True),
    })


def _read_credentials() -> dict:
    """Load Google Ads credentials from Streamlit secrets or env-style TOML."""
    secrets_path = Path(__file__).parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        raise FileNotFoundError(
            f"{secrets_path} not found. Copy secrets.toml.example and fill in values."
        )
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with secrets_path.open("rb") as f:
        data = tomllib.load(f)
    if "google_ads" not in data:
        raise KeyError("Missing [google_ads] section in secrets.toml")
    return data["google_ads"]


# ---------------------------------------------------------------------------
# Keyword loader
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KeywordEntry:
    brand: str
    keyword: str
    pure_bev: bool


def load_keywords(yaml_path: Path = config.KEYWORDS_YAML) -> list[KeywordEntry]:
    with yaml_path.open() as f:
        spec = yaml.safe_load(f)
    out: list[KeywordEntry] = []
    for brand, body in spec["brands"].items():
        for kw in body["keywords"]:
            out.append(KeywordEntry(
                brand=brand,
                keyword=kw,
                pure_bev=bool(body.get("pure_bev", False)),
            ))
    return out


# ---------------------------------------------------------------------------
# Google Ads call
# ---------------------------------------------------------------------------

def _chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _fetch_market_one_language(client, customer_id, market_code,
                               geo_resource, language_resource,
                               keywords) -> list[dict]:
    """Run one historical-metrics query for a single (market, language) pair."""
    keyword_plan_idea_service = client.get_service("KeywordPlanIdeaService")

    rows: list[dict] = []
    keyword_strings = [k.keyword for k in keywords]
    keyword_to_brand_pure = {k.keyword: (k.brand, k.pure_bev) for k in keywords}
    normalized_lookup = {
        normalize_keyword(k.keyword): (k.brand, k.pure_bev) for k in keywords
    }

    today = pd.Timestamp.today()
    end_year, end_month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    month_enum = client.enums.MonthOfYearEnum
    end_month_enum = getattr(month_enum, MONTH_NAMES[end_month - 1])

    for batch in _chunked(keyword_strings, 5000):
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(batch)
        request.geo_target_constants.append(geo_resource)
        request.language = language_resource
        request.include_adult_keywords = False
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        request.historical_metrics_options.year_month_range.start.year = config.START_YEAR
        request.historical_metrics_options.year_month_range.start.month = month_enum.JANUARY
        request.historical_metrics_options.year_month_range.end.year = end_year
        request.historical_metrics_options.year_month_range.end.month = end_month_enum

        response = _retry_on_rate_limit(
            lambda: keyword_plan_idea_service.generate_keyword_historical_metrics(
                request=request
            )
        )

        for result in response.results:
            text = result.text
            metrics = result.keyword_metrics
            brand, pure_bev = keyword_to_brand_pure.get(text, (None, None))
            if brand is None:
                brand, pure_bev = normalized_lookup.get(
                    normalize_keyword(text), (None, None)
                )
            for monthly in metrics.monthly_search_volumes:
                rows.append({
                    "country_code": market_code,
                    "brand":        brand,
                    "keyword":      text,
                    "pure_bev":     pure_bev,
                    "year":         int(monthly.year),
                    "month":        _month_to_int(monthly.month),
                    "search_volume": int(monthly.monthly_searches or 0),
                    "competition":  metrics.competition.name if metrics.competition else None,
                    "low_top_of_page_bid_micros":  int(metrics.low_top_of_page_bid_micros or 0),
                    "high_top_of_page_bid_micros": int(metrics.high_top_of_page_bid_micros or 0),
                })
    return rows


def fetch_market(client, customer_id: str, market_code: str,
                 keywords: list[KeywordEntry]) -> pd.DataFrame:
    """Fetch historical metrics for one market.

    NOTE on language: We query with the primary language only (language_ids[0]).
    Empirical test (scripts/diagnose_language.py, 2026-04) showed that Google
    Ads ignores the `language` filter for brand/model keywords — querying
    'Tesla Model Y' in CH with DE / FR / IT all return identical volumes.
    Looping over all official languages and summing therefore inflated CH (3×)
    and BE (2×). The single-language query already returns total geo-level
    volumes for language-agnostic terms, which is what we want."""
    market = config.MARKETS[market_code]
    googleads_service = client.get_service("GoogleAdsService")
    geo_resource = googleads_service.geo_target_constant_path(market["geo_id"])
    language_resource = googleads_service.language_constant_path(
        market["language_ids"][0]
    )

    rows = _fetch_market_one_language(
        client, customer_id, market_code,
        geo_resource, language_resource, keywords,
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df[df["year"] >= config.START_YEAR].reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(markets: list[str] | None = None, dry_run: bool = False) -> None:
    keywords = load_keywords()
    markets = markets or list(config.MARKETS.keys())
    print(f"[fetcher] Loaded {len(keywords)} keywords across "
          f"{len(set(k.brand for k in keywords))} brands.")
    print(f"[fetcher] Markets: {markets}")

    if dry_run:
        print("[fetcher] --dry-run: skipping API call. Credentials check…")
        creds = _read_credentials()
        required = ["developer_token", "client_id", "client_secret",
                    "refresh_token", "login_customer_id", "customer_id"]
        missing = [k for k in required if not creds.get(k)]
        if missing:
            print(f"[fetcher] ❌ Missing credentials: {missing}")
            sys.exit(1)
        print("[fetcher] ✅ All credentials present.")
        return

    client = _load_client()
    customer_id = _read_credentials()["customer_id"]

    all_frames: list[pd.DataFrame] = []
    for i, mkt in enumerate(markets):
        if i > 0:
            time.sleep(5)  # proactive spacing to stay under Basic-tier rate limit
        print(f"[fetcher] {mkt} — fetching {len(keywords)} keywords…")
        df = fetch_market(client, customer_id, mkt, keywords)
        print(f"[fetcher] {mkt} — got {len(df)} monthly rows")
        all_frames.append(df)

    combined = pd.concat(all_frames, ignore_index=True) if all_frames else pd.DataFrame()
    config.DATA_DIR.mkdir(exist_ok=True)
    out = config.DATA_DIR / "search_volumes.parquet"
    combined.to_parquet(out, index=False)
    print(f"[fetcher] ✅ Wrote {len(combined)} rows → {out}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--markets", help="Comma-separated market codes (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate config + credentials, no API calls")
    args = parser.parse_args()

    market_list = args.markets.split(",") if args.markets else None
    run(markets=market_list, dry_run=args.dry_run)
