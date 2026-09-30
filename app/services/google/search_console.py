import base64
import json
import os
import threading
import time
from urllib.parse import quote

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_SCOPES = (
    "https://www.googleapis.com/auth/siteverification "
    "https://www.googleapis.com/auth/webmasters"
)
_VERIFICATION_URL = "https://www.googleapis.com/siteVerification/v1"
_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"


class SearchConsoleError(RuntimeError):
    pass


def _b64url(data) -> str:
    if not isinstance(data, bytes):
        data = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class SearchConsoleClient:
    """Adds a domain to Google Search Console as a Domain property (sc-domain:<domain>),
    proving ownership with a DNS TXT record. Authenticates as a service account, signing
    the OAuth JWT itself so no Google client library is needed."""

    def __init__(self, key_file: str, owner_email: str = ""):
        if not key_file or not os.path.isfile(key_file):
            raise SearchConsoleError(
                "Chave da conta de serviço do Google não encontrada. "
                "Defina GOOGLE_SERVICE_ACCOUNT_FILE no .env com o caminho do arquivo JSON."
            )
        with open(key_file, "r", encoding="utf-8") as f:
            self._key = json.load(f)
        self.owner_email = owner_email
        self._token = ""
        self._token_exp = 0.0
        self._lock = threading.Lock()

    def _access_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            now = int(time.time())
            unsigned = _b64url({"alg": "RS256", "typ": "JWT"}) + "." + _b64url({
                "iss": self._key["client_email"],
                "scope": _SCOPES,
                "aud": self._key["token_uri"],
                "iat": now,
                "exp": now + 3600,
            })
            private_key = serialization.load_pem_private_key(self._key["private_key"].encode(), password=None)
            signature = private_key.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
            r = requests.post(
                self._key["token_uri"],
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": unsigned + "." + _b64url(signature),
                },
                timeout=30,
            )
            data = r.json()
            if "access_token" not in data:
                raise SearchConsoleError(f"Google recusou a autenticação: {data.get('error_description') or data}")
            self._token = data["access_token"]
            self._token_exp = time.time() + int(data.get("expires_in", 3600))
            return self._token

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        return requests.request(method, url, headers=headers, timeout=30, **kwargs)

    @staticmethod
    def _error_message(r: requests.Response) -> str:
        try:
            return r.json()["error"]["message"]
        except Exception:
            return f"HTTP {r.status_code}"

    @staticmethod
    def _site(domain: str) -> dict:
        return {"type": "INET_DOMAIN", "identifier": domain}

    def get_dns_token(self, domain: str) -> str:
        """TXT value Google expects on the domain root. Deterministic per domain + account."""
        r = self._request("POST", f"{_VERIFICATION_URL}/token", json={
            "site": self._site(domain),
            "verificationMethod": "DNS_TXT",
        })
        if r.status_code != 200:
            raise SearchConsoleError(f"Não foi possível obter o token de verificação: {self._error_message(r)}")
        return r.json()["token"]

    def verify(self, domain: str) -> bool:
        """Ask Google to check the TXT record. False means it isn't visible (yet)."""
        body = {"site": self._site(domain)}
        if self.owner_email:
            body["owners"] = [self.owner_email]
        r = self._request(
            "POST", f"{_VERIFICATION_URL}/webResource",
            params={"verificationMethod": "DNS_TXT"}, json=body,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 400:
            return False
        raise SearchConsoleError(f"Erro ao verificar o domínio: {self._error_message(r)}")

    def list_sites(self) -> list[dict]:
        """Every property the service account can see: [{'siteUrl', 'permissionLevel'}]."""
        r = self._request("GET", _SITES_URL)
        if r.status_code != 200:
            raise SearchConsoleError(f"Erro ao listar propriedades: {self._error_message(r)}")
        return r.json().get("siteEntry", [])

    def add_site(self, domain: str) -> None:
        r = self._request("PUT", f"{_SITES_URL}/{quote(f'sc-domain:{domain}', safe='')}")
        if r.status_code not in (200, 204):
            raise SearchConsoleError(f"Erro ao adicionar a propriedade: {self._error_message(r)}")
