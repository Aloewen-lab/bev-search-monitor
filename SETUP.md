# BEV Search Monitor — Setup

European Google search volumes for BEV brands & models, by market, since 2023.

## 1. Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 2. Secrets

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Fill in the `.streamlit/secrets.toml` you just created:

| Field                       | Where to get it |
|-----------------------------|-----------------|
| `app_password`              | Choose any string — gates dashboard access |
| `developer_token`           | Already provided — Google Ads API Center |
| `client_id`, `client_secret`| Google Cloud → APIs & Services → Credentials → OAuth 2.0 Client (Desktop) |
| `refresh_token`             | Run the OAuth flow once, see step 3 |
| `login_customer_id`         | Your Google Ads MCC (manager) account ID, no dashes |
| `customer_id`               | The operating account ID under the MCC, no dashes |

## 3. Generate refresh token (one-time)

Use Google's official helper:

```bash
python -m google_ads.examples.authentication.generate_user_credentials \
  --client_secrets_path=path/to/client_secret.json
```

Or follow the manual flow in [Google's docs](https://developers.google.com/google-ads/api/docs/oauth/cloud-project).
Paste the resulting `refresh_token` into `secrets.toml`.

## 4. Validate

```bash
python update.py --dry-run
```

Should print "✅ All credentials present."

## 5. First fetch

```bash
python update.py --markets DE   # start small to verify
python update.py                # full refresh: 11 markets
```

Expect ~5–15 min for a full refresh. Output: `data/search_volumes.parquet`.

## 6. Dashboard

```bash
streamlit run dashboard.py
```

Open http://localhost:8501, enter the password from `secrets.toml`.

## 7. Deploy (Streamlit Cloud)

1. Push repo to GitHub (private).
2. https://share.streamlit.io → New app → select repo, `dashboard.py`.
3. App Settings → Secrets → paste the contents of `secrets.toml`.
4. Deploy.

## 8. Monthly auto-update (later)

GitHub Actions workflow at `.github/workflows/monthly_update.yml` (not yet
created — milestone 2). Will run `python update.py` on the 5th of each month
and commit the updated parquet back to the repo.

## Data model

`data/search_volumes.parquet`:

| Column | Type | Notes |
|---|---|---|
| `country_code` | str | DE, UK, FR, IT, ES, BE, CH, AT, SE, NL, PT |
| `brand` | str | Slug from `keywords.yaml` (e.g. `volkswagen`) |
| `keyword` | str | Exact keyword string queried |
| `pure_bev` | bool | Whether the brand is pure-BEV (relevant for share calc) |
| `year`, `month` | int | 2023+ |
| `search_volume` | int | Monthly Google searches (Keyword Planner) |
| `competition` | str | LOW / MEDIUM / HIGH / UNSPECIFIED |
| `low_top_of_page_bid_micros` | int | EUR cents × 1e4 |
| `high_top_of_page_bid_micros` | int | EUR cents × 1e4 |
