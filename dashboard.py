"""BEV Search Monitor — Streamlit Dashboard.

Run locally:
    streamlit run dashboard.py

Deploy:
    Push to GitHub → connect repo on share.streamlit.io → add secrets.
"""

import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import config

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="BEV Search Monitor",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

def _password_ok() -> bool:
    expected = st.secrets.get("app_password")
    if not expected:
        return True
    if st.session_state.get("authed"):
        return True
    pw = st.text_input("Password", type="password")
    if pw and pw == expected:
        st.session_state["authed"] = True
        st.rerun()
    elif pw:
        st.error("Wrong password")
    return False


if not _password_ok():
    st.stop()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_int_de(n) -> str:
    """German thousands separator: 1234567 → '1.234.567'."""
    if pd.isna(n):
        return ""
    return f"{int(n):,}".replace(",", ".")


def fmt_pct(n) -> str:
    if pd.isna(n):
        return ""
    return f"{n:.2f} %"


def consolidate_smart_keyword(kw: str) -> str:
    """Display-side merge: 'smart 1' / 'smart hashtag 1' → 'smart #1'."""
    m = re.match(r"^smart (?:hashtag )?([135])$", kw or "", re.I)
    return f"smart #{m.group(1)}" if m else kw


def strip_facet_prefix(fig):
    """Plotly facet labels show 'country_code=DE' — replace with just 'DE'."""
    fig.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
    return fig


# ---------------------------------------------------------------------------
# Data load
# ---------------------------------------------------------------------------

DATA_FILE = config.DATA_DIR / "search_volumes.parquet"


@st.cache_data(ttl=3600, show_spinner="Loading search volumes…")
def load_data(file_mtime: float) -> pd.DataFrame:
    """Load parquet. Cache key includes file_mtime so any data refresh
    automatically busts the cache — no manual 'Clear cache' needed."""
    if not DATA_FILE.exists():
        return pd.DataFrame()
    df = pd.read_parquet(DATA_FILE)
    df = df.dropna(subset=["brand"])
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01"
    )
    # Display-side keyword consolidation (smart 1 + smart hashtag 1 → smart #1)
    df["display_keyword"] = df["keyword"].map(consolidate_smart_keyword)
    return df


mtime = DATA_FILE.stat().st_mtime if DATA_FILE.exists() else 0.0
df = load_data(mtime)

if df.empty:
    st.warning(
        f"No data file found at `{DATA_FILE.relative_to(config.PROJECT_ROOT)}`. "
        f"Run `python update.py` first."
    )
    st.stop()

MARKET_NAMES = {k: v["name"] for k, v in config.MARKETS.items()}

# ---------------------------------------------------------------------------
# Sidebar filters
# ---------------------------------------------------------------------------

st.sidebar.title("BEV Search Monitor")
st.sidebar.caption("European search volumes for BEV brands & models")

available_markets = sorted(df["country_code"].unique())
sel_markets = st.sidebar.multiselect(
    "Markets",
    options=available_markets,
    default=available_markets,
    format_func=lambda k: f"{k} – {MARKET_NAMES.get(k, k)}",
)

available_brands = sorted(df["brand"].unique())
sel_brands = st.sidebar.multiselect(
    "Brands",
    options=available_brands,
    default=available_brands,
)

date_min, date_max = df["date"].min(), df["date"].max()
date_range = st.sidebar.slider(
    "Date range",
    min_value=date_min.to_pydatetime(),
    max_value=date_max.to_pydatetime(),
    value=(date_min.to_pydatetime(), date_max.to_pydatetime()),
    format="YYYY-MM",
)

dff = df[
    df["country_code"].isin(sel_markets)
    & df["brand"].isin(sel_brands)
    & df["date"].between(*date_range)
].copy()

st.sidebar.divider()
st.sidebar.caption(
    f"{fmt_int_de(len(dff))} rows · last update: {df['date'].max():%Y-%m}"
)


def _empty_filter_guard():
    """Return True if filters yield no data; render warning + stop tab body."""
    if dff.empty:
        st.warning(
            "Keine Daten für die aktuelle Filterauswahl. "
            "Mindestens einen Markt und eine Marke in der Sidebar wählen."
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_info, tab1, tab2, tab3, tab4 = st.tabs([
    "Info",
    "Brand Trend",
    "Model Trend",
    f"Share of {config.FOCAL_BRAND} Brand Interest",
    "Raw Data",
])


# ── Tab Info ────────────────────────────────────────────────────────────────
with tab_info:
    st.title("BEV Search Monitor")
    st.caption(
        "Monthly Google search volumes for over 200 BEV brand and model keywords "
        "across 11 European markets — data since January 2023, updated monthly."
    )

    st.markdown(
        """
### What does this dashboard show?

Monthly Google search volumes for **over 200 BEV brand and model keywords**
covering **56 brands** in **11 European markets** (DE, UK, FR, IT, ES, BE, CH,
AT, SE, NL, PT). The data supports trend analysis, market comparisons, and
competitive benchmarks from the perspective of **smart** as the focal brand.

### Data source & method

- **Source:** Google Ads API · `KeywordPlanIdeaService.GenerateKeywordHistoricalMetrics`
- **Granularity:** monthly, per keyword × market
- **Time range:** since 2023-01, ongoing
- **Keyword logic:**
  - **Pure-BEV brands** (Tesla, BYD, Polestar, …): standalone brand name **+** model names
  - **Mixed brands** (BMW, VW, Audi, …): **model names only** — the standalone
    brand keyword would pull in ICE intent and distort the share calculation
  - **smart**: model names only (`#1`, `#3`, `#5`) — the word "smart" alone is
    too generic (smart watch, smart home, smart phone …)

### Headline KPI: Share of smart Brand Interest

Per market and month:

`Searches(smart) / Searches(all tracked BEV brands) × 100`

Dimensionless share indicator — comparable across markets regardless of country
size. A rising value = growing attention to smart relative to the BEV
competitive set.

### How to use the dashboard

1. **Sidebar filters** (left) apply **globally** to all tabs:
   - Markets (default: all 11)
   - Brands (default: all 56)
   - Date range
2. **Tabs:**
   - **Brand Trend** — aggregated search volumes per brand, with market comparison + yearly table
   - **Model Trend** — drill-down to keyword level within one brand
   - **Share of smart Brand Interest** — the headline KPI; one line per market + table for the latest month
   - **Raw Data** — raw table with CSV export
3. **Charts:**
   - Hover for exact values
   - Click legend = toggle a line on/off
   - Double-click legend = isolate that line
   - Range slider below the chart = zoom

### System architecture

```
   [Google Ads API]                         (data source)
   KeywordPlanIdeaService
            │
            │ OAuth 2.0 + Developer Token
            ▼
   [fetcher.py]                             (Python ingestion)
   - Reads keywords.yaml (200 kws, 56 brands)
   - Queries 11 markets sequentially
   - Normalises keywords, handles rate limits
            │
            │ writes
            ▼
   [data/search_volumes.parquet]            (storage, columnar binary)
            │
            │ committed to
            ▼
   [GitHub: Aloewen-lab/bev-search-monitor] (version control)
            │
            │ auto-deploy on push to main
            ▼
   [Streamlit Cloud]                        (hosting + container runtime)
   - Builds Python env from requirements.txt
   - Reads secrets.toml from Cloud Secrets store
            │
            │ runs
            ▼
   [dashboard.py]                           (visualization layer)
   - Password gate
   - Plotly charts + pandas tables
   - Auto-busts data cache on parquet mtime change
            │
            ▼
   [User browser]                           (bev-search-monitor.streamlit.app)
```

**Component summary**

| Component | Role |
|---|---|
| Google Ads API | Authoritative source of monthly keyword search volumes |
| `fetcher.py` + `keywords.yaml` | Local Python pipeline that pulls + cleans the data |
| `data/search_volumes.parquet` | Compact columnar storage (~115 KB for ~86 k rows) |
| GitHub repository | Version control + single source of truth for code and data |
| Streamlit Cloud | Free managed hosting that auto-redeploys on every `git push` |
| `dashboard.py` | Streamlit + Plotly app; password-gated, hot-reloads on data changes |
| `.streamlit/secrets.toml` | OAuth credentials + app password (local, never committed) |
| Cloud Secrets (Streamlit) | Same secrets, separately managed in the Streamlit Cloud UI |

**Update flow**

1. Locally: activate venv → `python update.py` → fresh parquet with the newest completed month
2. `git add data/search_volumes.parquet` → `git commit` → `git push`
3. Streamlit Cloud detects the push and rebuilds the app in 1–3 minutes
4. The cache key includes the parquet file's modification time, so users see the new data on next refresh — no manual cache clearing needed

**Why this stack**

The whole stack is **portable and open** — no vendor lock-in. The repo can be cloned to any Linux/macOS/Windows machine, the parquet can be opened in any tool that reads it (Python, R, DuckDB, Excel via plugin), and the dashboard can be redeployed to any container host (Render, Fly.io, AWS App Runner, self-hosted Docker) without code changes.

### Caveats

- **Granularity:** Google Keyword Planner snaps volumes to a fixed grid
  (`14800, 18100, 22200, 27100, …`) — this is normal, not a range estimate.
- **Keyword normalisation:** Google strips special characters (`#`, `°`, `:` …);
  we mirror this on our side. Spelling variants are consolidated
  (e.g. `smart 1` + `smart hashtag 1` → `smart #1`).
- **Late-launch models:** Models released in 2024+ have no search history in
  2023 — this is not a data error.
"""
    )


# ── Tab 1: Brand-level trend ────────────────────────────────────────────────
with tab1:
    st.header("Search Volume by Brand")
    st.caption("Tip: click a brand in the legend to toggle its line on/off.")

    if not _empty_filter_guard():
        agg_mode = st.radio(
            "Aggregation",
            options=["Sum across selected markets", "Per market (small multiples)"],
            horizontal=True,
        )

        by_brand_month = (
            dff.groupby(["date", "brand", "country_code"])["search_volume"]
            .sum()
            .reset_index()
        )

        if not by_brand_month.empty:
            if agg_mode == "Sum across selected markets":
                agg = (
                    by_brand_month.groupby(["date", "brand"])["search_volume"]
                    .sum().reset_index()
                )
                fig = px.line(
                    agg.sort_values("date"),
                    x="date", y="search_volume", color="brand", markers=True,
                    labels={"date": "Month", "search_volume": "Monthly searches",
                            "brand": "Brand (selectable)"},
                    title="Monthly Search Volume — Brand Total",
                )
                fig.update_layout(hovermode="x unified")
            else:
                fig = px.line(
                    by_brand_month.sort_values("date"),
                    x="date", y="search_volume", color="brand",
                    facet_col="country_code", facet_col_wrap=2,
                    labels={"date": "", "search_volume": "Searches",
                            "country_code": "Market",
                            "brand": "Brand (selectable)"},
                    title="Monthly Search Volume — Per Market",
                )
                strip_facet_prefix(fig)
            st.plotly_chart(fig, width="stretch")

        st.subheader("Brand × Year — total searches")
        yearly = (
            dff.groupby(["brand", "year"])["search_volume"]
            .sum().reset_index()
            .pivot(index="brand", columns="year", values="search_volume")
            .fillna(0).astype(int)
        )
        # Cast year columns to strings so Arrow doesn't warn on mixed dtypes
        # (integer years + "Total" string would otherwise mix)
        yearly.columns = [str(c) for c in yearly.columns]
        yearly["Total"] = yearly.sum(axis=1)
        yearly = yearly.sort_values("Total", ascending=False)
        st.dataframe(
            yearly.style.format(fmt_int_de),
            width="stretch",
        )


# ── Tab 2: Model-level trend ────────────────────────────────────────────────
with tab2:
    st.header("Search Volume by Model (Keyword)")
    st.caption("Tip: click a keyword in the legend to toggle its line on/off.")

    if not _empty_filter_guard():
        # Reserve graph slot at top, render selectors + table below
        graph_slot = st.empty()
        sel_brand_for_models = st.selectbox(
            "Brand", options=sorted(dff["brand"].unique())
        )
        bdf = dff[dff["brand"] == sel_brand_for_models]

        available_models = sorted(bdf["display_keyword"].unique())
        sel_models = st.multiselect(
            "Models",
            options=available_models,
            default=available_models,
            help="Filters which keywords appear in the chart and table.",
        )
        table_slot = st.empty()

        bdf_filtered = bdf[bdf["display_keyword"].isin(sel_models)]
        by_kw_month = (
            bdf_filtered.groupby(["date", "display_keyword"])["search_volume"]
            .sum().reset_index()
            .rename(columns={"display_keyword": "keyword"})
        )
        if not by_kw_month.empty:
            fig = px.line(
                by_kw_month.sort_values("date"),
                x="date", y="search_volume", color="keyword", markers=True,
                labels={"date": "Month", "search_volume": "Monthly searches",
                        "keyword": "Keyword (selectable)"},
                title=f"Monthly Search Volume — {sel_brand_for_models} (per keyword)",
            )
            graph_slot.plotly_chart(fig, width="stretch")

            by_kw = (
                bdf_filtered.groupby("display_keyword")["search_volume"].sum()
                .sort_values(ascending=False).reset_index()
                .rename(columns={"display_keyword": "keyword"})
            )
            table_slot.dataframe(
                by_kw.style.format({"search_volume": fmt_int_de}),
                width="stretch",
                hide_index=True,
            )
        else:
            graph_slot.info(
                f"No data for {sel_brand_for_models} with current filters."
            )


# ── Tab 3: Share of smart Brand Interest ────────────────────────────────────
with tab3:
    st.header(f"Share of {config.FOCAL_BRAND} Brand Interest")
    st.caption(
        f"Per market: searches for **{config.FOCAL_BRAND}** keywords ÷ "
        f"total searches across all tracked BEV brands."
    )

    if not _empty_filter_guard():
        focal_mask = dff["brand"] == config.FOCAL_BRAND
        focal = (
            dff[focal_mask].groupby(["country_code", "date"])["search_volume"]
            .sum().rename("focal")
        )
        total = (
            dff.groupby(["country_code", "date"])["search_volume"]
            .sum().rename("total")
        )
        by_market = pd.concat([focal, total], axis=1).fillna(0).reset_index()
        by_market["others"] = by_market["total"] - by_market["focal"]
        by_market["share_pct"] = (
            100 * by_market["focal"] / by_market["total"].replace(0, pd.NA)
        )

        if by_market.empty or by_market["date"].dropna().empty:
            st.info("Keine smart-Daten für die aktuelle Filterauswahl.")
        else:
            fig = px.line(
                by_market.sort_values("date"),
                x="date", y="share_pct", color="country_code", markers=True,
                labels={"date": "Month",
                        "share_pct": f"{config.FOCAL_BRAND} share %",
                        "country_code": "Market"},
                title=f"Share of {config.FOCAL_BRAND} Brand Interest "
                      f"— Monthly, by Market",
            )
            fig.update_layout(hovermode="x unified")
            st.plotly_chart(fig, width="stretch")

            latest_date = by_market["date"].max()
            latest = (
                by_market[by_market["date"] == latest_date]
                [["country_code", "focal", "others", "total", "share_pct"]]
                .sort_values("share_pct", ascending=False)
                .rename(columns={
                    "country_code": "Market",
                    "focal": f"{config.FOCAL_BRAND} (focal)",
                    "others": "Others",
                    "total": "Total",
                    "share_pct": "Share",
                })
            )
            st.subheader(f"Latest month — {latest_date:%Y-%m}")
            st.dataframe(
                latest.style.format({
                    f"{config.FOCAL_BRAND} (focal)": fmt_int_de,
                    "Others": fmt_int_de,
                    "Total": fmt_int_de,
                    "Share": fmt_pct,
                }),
                width="stretch",
                hide_index=True,
            )


# ── Tab 4: Raw data export ──────────────────────────────────────────────────
with tab4:
    st.header("Raw Data")
    st.caption(
        f"{fmt_int_de(len(dff))} rows. Numbers shown unformatted — use the CSV "
        "download for analysis. Sortable by clicking column headers."
    )
    st.dataframe(dff, width="stretch", hide_index=True)
    csv = dff.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="bev_search_volumes.csv",
        mime="text/csv",
    )
