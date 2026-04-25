"""BEV Search Monitor — Streamlit Dashboard.

Run locally:
    streamlit run dashboard.py

Deploy:
    Push to GitHub → connect repo on share.streamlit.io → add secrets.
"""

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
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------

def _password_ok() -> bool:
    expected = st.secrets.get("app_password")
    if not expected:
        return True  # no gate configured → open access (dev mode)
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
# Data load
# ---------------------------------------------------------------------------

DATA_FILE = config.DATA_DIR / "search_volumes.parquet"


@st.cache_data(ttl=3600, show_spinner="Loading search volumes…")
def load_data() -> pd.DataFrame:
    if not DATA_FILE.exists():
        return pd.DataFrame()
    df = pd.read_parquet(DATA_FILE)
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01"
    )
    return df


df = load_data()

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

st.sidebar.title("🔍 BEV Search Monitor")
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
st.sidebar.caption(f"{len(dff):,} rows · last update: {df['date'].max():%Y-%m}")

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab1, tab2, tab3, tab4 = st.tabs([
    "📈 Brand Trend",
    "🚗 Model Trend",
    f"⚡ Share of {config.FOCAL_BRAND.title()} Brand Interest",
    "📥 Raw Data",
])

# ── Tab 1: Brand-level trend ────────────────────────────────────────────────
with tab1:
    st.header("Search Volume by Brand")

    by_brand_month = (
        dff.groupby(["date", "brand", "country_code"])["search_volume"]
        .sum()
        .reset_index()
    )

    agg_mode = st.radio(
        "Aggregation",
        options=["Sum across selected markets", "Per market (small multiples)"],
        horizontal=True,
    )

    if agg_mode == "Sum across selected markets":
        agg = by_brand_month.groupby(["date", "brand"])["search_volume"].sum().reset_index()
        fig = px.line(
            agg.sort_values("date"),
            x="date", y="search_volume", color="brand", markers=True,
            labels={"date": "Month", "search_volume": "Monthly searches", "brand": "Brand"},
            title="Monthly Search Volume — Brand Total",
        )
        fig.update_layout(hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)
    else:
        fig = px.line(
            by_brand_month.sort_values("date"),
            x="date", y="search_volume", color="brand",
            facet_col="country_code", facet_col_wrap=3,
            labels={"date": "", "search_volume": "Searches"},
            title="Monthly Search Volume — Per Market",
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Brand × Year — total searches")
    yearly = (
        dff.groupby(["brand", "year"])["search_volume"]
        .sum()
        .reset_index()
        .pivot(index="brand", columns="year", values="search_volume")
        .fillna(0).astype(int)
    )
    yearly["Total"] = yearly.sum(axis=1)
    yearly = yearly.sort_values("Total", ascending=False)
    st.dataframe(yearly, use_container_width=True)


# ── Tab 2: Model-level trend ────────────────────────────────────────────────
with tab2:
    st.header("Search Volume by Model (Keyword)")

    sel_brand_for_models = st.selectbox(
        "Brand", options=sorted(dff["brand"].unique())
    )
    bdf = dff[dff["brand"] == sel_brand_for_models]

    by_kw_month = (
        bdf.groupby(["date", "keyword"])["search_volume"].sum().reset_index()
    )
    fig = px.line(
        by_kw_month.sort_values("date"),
        x="date", y="search_volume", color="keyword", markers=True,
        labels={"date": "Month", "search_volume": "Monthly searches", "keyword": "Keyword"},
        title=f"Monthly Search Volume — {sel_brand_for_models} (per keyword)",
    )
    st.plotly_chart(fig, use_container_width=True)

    by_kw = (
        bdf.groupby("keyword")["search_volume"].sum().sort_values(ascending=False)
        .reset_index()
    )
    st.dataframe(by_kw, use_container_width=True)


# ── Tab 3: Share of smart Brand Interest ────────────────────────────────────
with tab3:
    st.header(f"Share of {config.FOCAL_BRAND.title()} Brand Interest")
    st.caption(
        f"Per market: searches for **{config.FOCAL_BRAND}** keywords ÷ "
        f"total searches across all tracked BEV brands."
    )

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

    fig = px.line(
        by_market.sort_values("date"),
        x="date", y="share_pct", color="country_code", markers=True,
        labels={"date": "Month", "share_pct": f"{config.FOCAL_BRAND} share %",
                "country_code": "Market"},
        title=f"Share of {config.FOCAL_BRAND.title()} Brand Interest — Monthly, by Market",
    )
    fig.update_layout(hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    latest = by_market[by_market["date"] == by_market["date"].max()].copy()
    latest = latest[["country_code", "focal", "others", "total", "share_pct"]]
    latest = latest.sort_values("share_pct", ascending=False)
    st.subheader(f"Latest month — {by_market['date'].max():%Y-%m}")
    st.dataframe(
        latest.style.format({
            "focal": "{:,.0f}", "others": "{:,.0f}", "total": "{:,.0f}",
            "share_pct": "{:.2f}%",
        }),
        use_container_width=True,
    )


# ── Tab 4: Raw data export ──────────────────────────────────────────────────
with tab4:
    st.header("Raw Data")
    st.dataframe(dff, use_container_width=True)
    csv = dff.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download CSV",
        data=csv,
        file_name="bev_search_volumes.csv",
        mime="text/csv",
    )
