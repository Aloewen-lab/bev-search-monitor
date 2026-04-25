"""Static config for the BEV Search Monitor.

Markets, language pairings, and file paths only — no secrets here.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR     = PROJECT_ROOT / "data"
KEYWORDS_YAML = PROJECT_ROOT / "keywords.yaml"

# Google Ads geo and language constants.
# Geo:  https://developers.google.com/google-ads/api/data/geotargets
# Lang: https://developers.google.com/google-ads/api/data/codes-formats#languages
MARKETS = {
    "DE": {"name": "Germany",     "geo_id": 2276, "language_ids": [1001]},          # de
    "UK": {"name": "United Kingdom", "geo_id": 2826, "language_ids": [1000]},        # en
    "FR": {"name": "France",      "geo_id": 2250, "language_ids": [1002]},           # fr
    "IT": {"name": "Italy",       "geo_id": 2380, "language_ids": [1004]},           # it
    "ES": {"name": "Spain",       "geo_id": 2724, "language_ids": [1003]},           # es
    "BE": {"name": "Belgium",     "geo_id": 2056, "language_ids": [1010, 1002]},     # nl, fr
    "CH": {"name": "Switzerland", "geo_id": 2756, "language_ids": [1001, 1002, 1004]},  # de, fr, it
    "AT": {"name": "Austria",     "geo_id": 2040, "language_ids": [1001]},           # de
    "SE": {"name": "Sweden",      "geo_id": 2752, "language_ids": [1015]},           # sv
    "NL": {"name": "Netherlands", "geo_id": 2528, "language_ids": [1010]},           # nl
    "PT": {"name": "Portugal",    "geo_id": 2620, "language_ids": [1014]},           # pt
}

FOCAL_BRAND = "smart"
START_YEAR  = 2023
