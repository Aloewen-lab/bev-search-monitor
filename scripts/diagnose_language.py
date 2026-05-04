"""Diagnose whether Google Ads' `language` filter actually matters for brand
keywords — or whether it's effectively ignored, leading to multi-language
double-counting in our fetcher.

Method: query CH (geo_id=2756) for two test keywords, once per official
Swiss language. If the three runs return ~identical volumes, the language
filter is non-disjoint for brand keywords → multi-language summing inflates.

Run:
    python scripts/diagnose_language.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fetcher import _load_client, _read_credentials  # noqa: E402

CH_GEO_ID = 2756
LANGUAGES = [(1001, "DE"), (1002, "FR"), (1004, "IT")]
TEST_KEYWORDS = ["Tesla Model Y", "BMW iX3"]


def main():
    client = _load_client()
    customer_id = _read_credentials()["customer_id"]

    googleads_service = client.get_service("GoogleAdsService")
    keyword_plan_idea_service = client.get_service("KeywordPlanIdeaService")

    geo = googleads_service.geo_target_constant_path(CH_GEO_ID)

    print(f"Diagnostic: CH × {TEST_KEYWORDS} × {[n for _, n in LANGUAGES]}\n")
    print(f"{'Keyword':<20} {'Lang':<5} "
          f"{'Last Month Vol':>15} {'12-mo Sum':>15}")
    print("-" * 60)

    for lang_id, lang_name in LANGUAGES:
        lang = googleads_service.language_constant_path(lang_id)
        request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
        request.customer_id = customer_id
        request.keywords.extend(TEST_KEYWORDS)
        request.geo_target_constants.append(geo)
        request.language = lang
        request.keyword_plan_network = (
            client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
        )

        response = keyword_plan_idea_service.generate_keyword_historical_metrics(
            request=request
        )

        for result in response.results:
            kw = result.text
            volumes = list(result.keyword_metrics.monthly_search_volumes)
            last_month_vol = int(volumes[-1].monthly_searches or 0) if volumes else 0
            twelve_mo_sum = sum(int(m.monthly_searches or 0) for m in volumes[-12:])
            print(f"{kw:<20} {lang_name:<5} "
                  f"{last_month_vol:>15,} {twelve_mo_sum:>15,}")
        time.sleep(3)

    print()
    print("Wenn die Werte pro Keyword über alle Sprachen ~identisch sind →")
    print("Google ignoriert den language-Filter für Brand-Keywords →")
    print("Multi-Language-Summen blähen die Daten auf, Revert nötig.")


if __name__ == "__main__":
    main()
