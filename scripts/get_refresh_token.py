"""One-time OAuth flow to obtain a refresh_token for the Google Ads API.

Reads client_secret.json (Desktop OAuth client downloaded from Cloud Console),
opens a browser for login + consent, then prints the refresh_token so you can
paste it into .streamlit/secrets.toml.

Run:
    python scripts/get_refresh_token.py

Notes:
    * Log in with aloewen@al-mediaconsulting.com (the same account that owns
      the Google Ads MCC).
    * The browser may show a Google security warning — click "Advanced" →
      "Go to BEV Search Monitor (unsafe)". This is expected for an Internal
      OAuth app on first use.
    * If you've authorized this app before, prompt='consent' forces Google to
      re-issue a refresh_token. Without it, Google returns only an access
      token on subsequent runs.
"""

from pathlib import Path
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/adwords"]
CLIENT_SECRET = Path(__file__).resolve().parent.parent / "client_secret.json"


def main():
    if not CLIENT_SECRET.exists():
        sys.exit(
            f"❌ {CLIENT_SECRET} not found.\n"
            "   Download it from Cloud Console → Auth Platform → Clients → "
            "your Desktop client → Download JSON, and save as "
            "'client_secret.json' in the project root."
        )
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CLIENT_SECRET), scopes=SCOPES
    )
    creds = flow.run_local_server(port=0, prompt="consent")

    print()
    print("=" * 64)
    print("✅ Refresh token obtained.")
    print()
    print("Paste this into .streamlit/secrets.toml under [google_ads]:")
    print()
    print(f'    refresh_token = "{creds.refresh_token}"')
    print()
    print("=" * 64)


if __name__ == "__main__":
    main()
