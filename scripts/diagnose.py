"""Quick data quality checks on data/search_volumes.parquet.

Run:
    python scripts/diagnose.py
"""

from pathlib import Path
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / "data" / "search_volumes.parquet"

if not DATA.exists():
    raise SystemExit(f"❌ {DATA} not found — run 'python update.py' first.")

df = pd.read_parquet(DATA)

print(f"Total rows:      {len(df):,}")
print(f"Markets:         {sorted(df['country_code'].unique())}")
print(f"Date range:      "
      f"{df['year'].min()}-{df[df['year']==df['year'].min()]['month'].min():02d}"
      f" → {df['year'].max()}-{df[df['year']==df['year'].max()]['month'].max():02d}")
print()

n_unmatched = df["brand"].isna().sum()
print(f"Rows ohne brand: {n_unmatched:,} ({100*n_unmatched/len(df):.1f} %)")
if n_unmatched:
    print()
    print("Unmatched keywords — top 15 by avg monthly volume:")
    unm = (
        df[df["brand"].isna()]
        .groupby("keyword")["search_volume"]
        .mean()
        .sort_values(ascending=False)
        .head(15)
        .round(0)
    )
    print(unm.to_string())
