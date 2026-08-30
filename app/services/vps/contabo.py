import re
import time
import uuid

import requests

from .base import VpsProvider, VpsInstance

AUTH_URL = "https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"
API_BASE = "https://api.contabo.com/v1"

# Fallback Ubuntu 22.04 image id, used only if the live catalog lookup in
# _resolve_ubuntu_image_id() fails — Contabo periodically retires image ids, which is
# exactly the kind of drift that used to surface as an opaque 400 on instance creation.
DEFAULT_UBUNTU_IMAGE_ID = "afecbb85-e2fc-46f0-9684-b46b1faf00bb"

# Matches the plain "ubuntu-22.04" image only — Contabo's catalog also lists control-panel
# variants like "ubuntu-22.04-plesk" / "ubuntu-22.04-cpanel", which would conflict with
# this app's own nginx/certbot/php-fpm provisioning and must not be picked.
UBUNTU_2204_RE = re.compile(r"^ubuntu[ _-]?22\.?04$", re.IGNORECASE)

# Contabo retired the old "V91"/"V92"/"V93" Cloud VPS line — POST /compute/instances now
# rejects them with "No offer was found for product ID '...' and period '...'" even though
# a grandfathered account can still see old instances running on them. Current catalog
# (confirmed against the live API docs) is the "V153"-"V158" Cloud VPS SSD series.
PLANS = [
    {"id": "V153", "label": "Cloud VPS 4 (4 vCPU / 4GB / 100GB SSD)", "price": "verificar no painel Contabo"},
    {"id": "V154", "label": "Cloud VPS 6 (6 vCPU / 6GB / 200GB SSD)", "price": "verificar no painel Contabo"},
    {"id": "V155", "label": "Cloud VPS 8 (8 vCPU / 8GB / 300GB SSD)", "price": "verificar no painel Contabo"},
    {"id": "V156", "label": "Cloud VPS 12 (12 vCPU / 12GB / 400GB SSD)", "price": "verificar no painel Contabo"},
    {"id": "V157", "label": "Cloud VPS 16 (16 vCPU / 16GB / 500GB SSD)", "price": "verificar no painel Contabo"},
    {"id": "V158", "label": "Cloud VPS 18 (18 vCPU / 18GB / 600GB SSD)", "price": "verificar no painel Contabo"},
]

REGIONS = [
    {"id": "EU", "label": "Europa"},
    {"id": "US-central", "label": "EUA (Central)"},
    {"id": "US-east", "label": "EUA (Leste)"},
    {"id": "US-west", "label": "EUA (Oeste)"},
    {"id": "SIN", "label": "Singapura"},
    {"id": "UK", "label": "Reino Unido"},
    {"id": "AUS", "label": "Austrália"},
    {"id": "JPN", "label": "Japão"},
    {"id": "IND", "label": "Índia"},
]


class ContaboProvider(VpsProvider):
    """secret must contain: client_id, client_secret, api_user, api_password."""

    FIELDS = [
        {"name": "client_id", "label": "Client ID", "type": "text", "required": True, "help": ""},
        {"name": "client_secret", "label": "Client Secret", "type": "password", "required": True, "help": ""},
        {"name": "api_user", "label": "API User", "type": "text", "required": True, "help": "e-mail/usuário de API cadastrado no painel Contabo"},
        {"name": "api_password", "label": "API Password", "type": "password", "required": True, "help": "senha de API gerada no painel Contabo — não é a senha de login da conta"},
    ]
    BILLING = "Cobra diretamente no cartão/PayPal cadastrado na conta Contabo — não usa saldo pré-pago."

    def __init__(self, secret: dict):
        super().__init__(secret)
        self._cached_token = ""
        self._token_expires_at = 0.0

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._token()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status == 401:
                return False, "Contabo rejeitou as credenciais (401). Confira client_id/client_secret e a API password gerada no painel (não é a senha da conta)."
            return False, f"Erro Contabo: {exc}"
        except requests.RequestException as exc:
            return False, f"Falha de conexão com a Contabo: {exc}"
        return True, "Autenticação OK."

    def _token(self) -> str:
        if self._cached_token and time.time() < self._token_expires_at:
            return self._cached_token
        data = {
            "client_id": self.secret.get("client_id", ""),
            "client_secret": self.secret.get("client_secret", ""),
            "username": self.secret.get("api_user", ""),
            "password": self.secret.get("api_password", ""),
            "grant_type": "password",
        }
        r = requests.post(AUTH_URL, data=data, timeout=30)
        r.raise_for_status()
        body = r.json()
        self._cached_token = body["access_token"]
        # Refresh a bit early so a token doesn't expire mid-request.
        self._token_expires_at = time.time() + max(int(body.get("expires_in", 60)) - 30, 0)
        return self._cached_token

    def _headers(self, request_id: str):
        return {
            "Authorization": f"Bearer {self._token()}",
            "x-request-id": request_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _error_text(r: requests.Response) -> str:
        try:
            body = r.json()
        except ValueError:
            return (r.text or "").strip()[:500]
        message = body.get("message") or body.get("error_description") or body.get("error")
        errors = body.get("errors")
        if errors:
            detail = "; ".join(
                f"{e.get('field', '')}: {e.get('message', e)}".strip(": ") if isinstance(e, dict) else str(e)
                for e in errors
            )
            message = f"{message} ({detail})" if message else detail
        if not message:
            message = (r.text or "").strip()[:500] or "sem detalhes"
        request_id = body.get("requestId")
        return f"{message} [requestId: {request_id}]" if request_id else message

    def _request(self, method: str, path: str, **kw):
        timeout = kw.pop("timeout", 30)
        request_id = str(uuid.uuid4())
        r = requests.request(method, f"{API_BASE}{path}", headers=self._headers(request_id), timeout=timeout, **kw)
        if not r.ok:
            # Contabo's own error body doesn't always echo a requestId (e.g. on a bare 500),
            # so fall back to the x-request-id we sent — that's what Contabo support needs
            # to look up a failed request when their error says "contact support".
            detail = self._error_text(r)
            if "requestId" not in detail:
                detail = f"{detail} [x-request-id enviado: {request_id}]"
            raise RuntimeError(f"Contabo {r.status_code} em {path}: {detail}")
        return r.json() if r.content else {}

    def list_plans(self):
        return PLANS

    def list_regions(self):
        return REGIONS

    @staticmethod
    def _extract_ipv4(data: dict) -> str:
        return ((data.get("ipConfig") or {}).get("v4") or {}).get("ip", "")

    def _resolve_ubuntu_image_id(self) -> str:
        """Looks up the current Ubuntu 22.04 standard image id instead of trusting a
        hardcoded constant, which Contabo periodically retires — that drift used to
        surface as an opaque 400 on instance creation with no indication of the cause."""
        try:
            body = self._request("GET", "/compute/images", params={"standardImage": "true", "size": 100})
        except Exception:
            return DEFAULT_UBUNTU_IMAGE_ID
        candidates = [
            img for img in body.get("data", [])
            if UBUNTU_2204_RE.match((img.get("name") or "").strip())
        ]
        if not candidates:
            return DEFAULT_UBUNTU_IMAGE_ID
        candidates.sort(key=lambda img: img.get("creationDate", ""), reverse=True)
        return candidates[0].get("imageId") or DEFAULT_UBUNTU_IMAGE_ID

    @staticmethod
    def _sanitize_display_name(label: str, fallback: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9 ._-]", "", label or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return (cleaned or fallback)[:255]

    def _upload_ssh_key(self, public_key: str, name: str) -> int:
        body = {"name": name, "type": "ssh", "value": public_key}
        data = self._request("POST", "/secrets", json=body)
        return data["data"][0]["secretId"]

    def _delete_secret(self, secret_id: int) -> None:
        try:
            self._request("DELETE", f"/secrets/{secret_id}")
        except Exception:
            pass  # best-effort cleanup; never mask the original error

    def create_instance(self, plan_id: str, region_id: str, label: str) -> VpsInstance:
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        public_openssh = key.public_key().public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        ).decode()

        display_name = self._sanitize_display_name(label, "deployer-funis")
        secret_name = f"deployer-funis-{display_name}-{uuid.uuid4().hex[:8]}"[:255]
        secret_id = self._upload_ssh_key(public_openssh, secret_name)

        try:
            body = {
                "imageId": self._resolve_ubuntu_image_id(),
                "productId": plan_id,
                "region": region_id,
                "period": 1,
                "displayName": display_name,
                "sshKeys": [secret_id],
                "defaultUser": "root",
            }
            data = self._request("POST", "/compute/instances", json=body, timeout=60)
        except Exception:
            self._delete_secret(secret_id)
            raise
        instance = data["data"][0]

        return VpsInstance(
            instance_id=str(instance["instanceId"]),
            ip_address=self._extract_ipv4(instance),
            status="provisioning",
            ssh_user="root",
            ssh_private_key=private_pem,
            region=region_id,
            plan=plan_id,
        )

    def get_instance(self, instance_id: str) -> VpsInstance:
        data = self._request("GET", f"/compute/instances/{instance_id}")
        instance = data["data"][0]
        status = "ready" if instance.get("status") == "running" else "provisioning"
        return VpsInstance(
            instance_id=str(instance["instanceId"]),
            ip_address=self._extract_ipv4(instance),
            status=status,
            region=instance.get("region", ""),
            plan=instance.get("productId", ""),
        )

    def destroy(self, instance_id: str) -> None:
        body = {"cancelDate": time.strftime("%Y-%m-%d")}
        self._request("POST", f"/compute/instances/{instance_id}/cancel", json=body)
