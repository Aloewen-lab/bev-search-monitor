"""Spike v2 — pytrends mit 30s-Pausen und Retry-Logic auf 429.

Validates:
1. Hält pytrends stabil bei 30s Spacing zwischen Batches?
2. Erholt sich der Backoff von einzelnen 429ern?

Run:
    python scripts/spike_pytrends.py

Erwartet bei Erfolg: 3 Tabellen, jeweils mit Mean-Scores.
Erwartet bei Misserfolg: Klare Diagnose welcher Batch wo gescheitert ist.
"""

import time
from pytrends.exceptions import TooManyRequestsError
from pytrends.request import TrendReq

ANCHOR = "Tesla Model Y"
TEST_BATCHES = [
    ("DE", ["smart #1", "BMW iX3", "Polestar 2", "Zeekr 001"]),
    ("DE", ["VW ID.3", "Audi Q4 e-tron", "Mercedes EQA", "Cupra Born"]),
    ("CH", ["smart #1", "Polestar 2", "Volvo EX30", "BMW iX3"]),
]

BASE_PAUSE = 30          # Sekunden zwischen Batches
RETRY_DELAYS = [60, 120, 240]  # bei 429: nochmal warten + retry


def query_one_batch(pytrends, full_batch, geo):
    for attempt, delay_if_fail in enumerate([0] + RETRY_DELAYS):
        if delay_if_fail:
            print(f"  ⏸  Retry-Pause {delay_if_fail}s (Versuch {attempt + 1})…")
            time.sleep(delay_if_fail)
        try:
            pytrends.build_payload(full_batch, timeframe="today 3-m", geo=geo)
            df = pytrends.interest_over_time()
            if df.empty:
                print(f"  ⚠ Empty response (Versuch {attempt + 1})")
                continue
            return df
        except TooManyRequestsError:
            print(f"  ⚠ 429 (Versuch {attempt + 1})")
            continue
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            return None
    return None


pytrends = TrendReq(hl="en-US", tz=120)

for i, (geo, keywords) in enumerate(TEST_BATCHES):
    if i > 0:
        print(f"\n⏸  Spacing {BASE_PAUSE}s vor nächstem Batch…")
        time.sleep(BASE_PAUSE)
    full_batch = [ANCHOR] + keywords
    print(f"\n=== Batch {i + 1}: geo={geo}, keywords={full_batch} ===")
    df = query_one_batch(pytrends, full_batch, geo)
    if df is None:
        print("❌ Final fail nach allen Retries.")
        continue
    last30 = df.iloc[-30:].drop(columns="isPartial", errors="ignore")
    print(f"✅ Got {len(df)} daily rows.")
    print("Mean interest score per keyword (last 30 days):")
    print(last30.mean().round(1).to_string())
