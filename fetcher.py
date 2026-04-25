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
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

import config

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


def fetch_market(client, customer_id: str, market_code: str,
                 keywords: list[KeywordEntry]) -> pd.DataFrame:
    """Fetch historical metrics for one market across all keywords."""
    market = config.MARKETS[market_code]
    keyword_plan_idea_service = client.get_service("KeywordPlanIdeaService")
    googleads_service = client.get_service("GoogleAdsService")

    geo_resource = googleads_service.geo_target_constant_path(market["geo_id"])
    # historical metrics endpoint takes ONE language; pick the primary
    language_resource = googleads_service.language_constant_path(market["language_ids"][0])

    rows: list[dict] = []

    # API caps at ~10k keywords/request; we batch to be safe.
    keyword_strings = [k.keyword for k in keywords]
    keyword_to_brand_pure = {k.keyword: (k.brand, k.pure_bev) for k in keywords}

    for batch in _chunked(keyword_strings, 5000):
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(batch)
        request.geo_target_constants.append(geo_resource)
        request.language = language_resource
        request.include_adult_keywords = False
        request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH

        response = keyword_plan_idea_service.generate_keyword_historical_metrics(
            request=request
        )

        for result in response.results:
            text = result.text
            metrics = result.keyword_metrics
            brand, pure_bev = keyword_to_brand_pure.get(text, (None, None))
            if brand is None:
                # Google sometimes normalizes — try case-insensitive match
                norm = text.lower()
                for k, v in keyword_to_brand_pure.items():
                    if k.lower() == norm:
                        brand, pure_bev = v
                        break
            for monthly in metrics.monthly_search_volumes:
                rows.append({
                    "country_code": market_code,
                    "brand":        brand,
                    "keyword":      text,
                    "pure_bev":     pure_bev,
                    "year":         int(monthly.year),
                    "month":        int(monthly.month),  # 1=JAN .. 12=DEC (enum)
                    "search_volume": int(monthly.monthly_searches or 0),
                    "competition":  metrics.competition.name if metrics.competition else None,
                    "low_top_of_page_bid_micros":  int(metrics.low_top_of_page_bid_micros or 0),
                    "high_top_of_page_bid_micros": int(metrics.high_top_of_page_bid_micros or 0),
                })

    df = pd.DataFrame(rows)
    if not df.empty:
        # Google Ads returns enum month names — coerce if needed
        if df["month"].dtype == object:
            month_map = {
                "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
                "MAY": 5, "JUNE": 6, "JULY": 7, "AUGUST": 8,
                "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12,
            }
            df["month"] = df["month"].map(month_map).astype(int)
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
    for mkt in markets:
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
