"""Per-user Google account connection (OAuth) for Search Console.

A user who connects their Google account has the app verify and own their domains as
themself, so the domains show up in their own Search Console. Users who haven't connected
fall back to the shared service account."""
import secrets
from urllib.parse import urlencode

import requests

from ... import db
from ...models import ProviderCredential
from .search_console import SearchConsoleClient, SearchConsoleError

KIND = "google"
PROVIDER = "google_oauth"

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
_SCOPES = (
    "openid email "
    "https://www.googleapis.com/auth/siteverification "
    "https://www.googleapis.com/auth/webmasters"
)


def oauth_configured(config) -> bool:
    return bool(config["GOOGLE_OAUTH_CLIENT_ID"] and config["GOOGLE_OAUTH_CLIENT_SECRET"])


def get_connection(user_id: int):
    return ProviderCredential.query.filter_by(user_id=user_id, kind=KIND, provider=PROVIDER).first()


def build_auth_url(config, redirect_uri: str, state: str) -> str:
    return _AUTH_URL + "?" + urlencode({
        "client_id": config["GOOGLE_OAUTH_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",   # ask for a refresh token
        "prompt": "consent",        # ...and force it even if consent was given before
        "state": state,
    })


def new_state() -> str:
    return secrets.token_urlsafe(24)


def complete_connection(config, user_id: int, code: str, redirect_uri: str) -> str:
    """Exchange the authorization code, store the refresh token (encrypted) and return the
    connected account's e-mail. Raises SearchConsoleError on failure."""
    r = requests.post(_TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config["GOOGLE_OAUTH_CLIENT_ID"],
        "client_secret": config["GOOGLE_OAUTH_CLIENT_SECRET"],
        "redirect_uri": redirect_uri,
    }, timeout=30)
    data = r.json()
    if "access_token" not in data:
        raise SearchConsoleError(f"Google recusou o login: {data.get('error_description') or data.get('error')}")
    if not data.get("refresh_token"):
        raise SearchConsoleError(
            "O Google não devolveu um refresh token. Remova o acesso do app em "
            "myaccount.google.com/permissions e conecte de novo."
        )

    info = requests.get(_USERINFO_URL, headers={"Authorization": f"Bearer {data['access_token']}"}, timeout=30).json()
    email = info.get("email", "")

    cred = get_connection(user_id)
    if not cred:
        cred = ProviderCredential(user_id=user_id, kind=KIND, provider=PROVIDER, label=email)
        db.session.add(cred)
    cred.label = email
    cred.set_secret({"refresh_token": data["refresh_token"], "email": email})
    db.session.commit()
    return email


def client_for_user(config, user_id: int) -> tuple[SearchConsoleClient, str]:
    """(client, account) — the user's own Google account if connected, else the service
    account. `account` is the e-mail of the connected account, or '' for the service account."""
    cred = get_connection(user_id)
    if cred and oauth_configured(config):
        secret = cred.get_secret()
        client = SearchConsoleClient(oauth={
            "client_id": config["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": config["GOOGLE_OAUTH_CLIENT_SECRET"],
            "refresh_token": secret.get("refresh_token", ""),
        })
        return client, secret.get("email", "")
    return SearchConsoleClient(config["GOOGLE_SERVICE_ACCOUNT_FILE"], config["GSC_OWNER_EMAIL"]), ""
