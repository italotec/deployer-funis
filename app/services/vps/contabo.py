import time
import uuid

import requests

from .base import VpsProvider, VpsInstance

AUTH_URL = "https://auth.contabo.com/auth/realms/contabo/protocol/openid-connect/token"
API_BASE = "https://api.contabo.com/v1"

# Contabo's default standard Ubuntu 22.04 image id (per Contabo API docs).
# Verify against the current image catalog (GET /v1/compute/images) before relying on it long-term —
# see docs/providers/vps/contabo.md.
DEFAULT_UBUNTU_IMAGE_ID = "afecbb85-e2fc-46f0-9684-b46b1faf00bb"

PLANS = [
    {"id": "V91", "label": "Cloud VPS 10 (4 vCPU / 8GB / 75GB)", "price": "verificar no painel Contabo"},
    {"id": "V92", "label": "Cloud VPS 20 (6 vCPU / 16GB / 150GB)", "price": "verificar no painel Contabo"},
    {"id": "V93", "label": "Cloud VPS 30 (8 vCPU / 24GB / 250GB)", "price": "verificar no painel Contabo"},
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
        data = {
            "client_id": self.secret.get("client_id", ""),
            "client_secret": self.secret.get("client_secret", ""),
            "username": self.secret.get("api_user", ""),
            "password": self.secret.get("api_password", ""),
            "grant_type": "password",
        }
        r = requests.post(AUTH_URL, data=data, timeout=30)
        r.raise_for_status()
        return r.json()["access_token"]

    def _headers(self):
        return {
            "Authorization": f"Bearer {self._token()}",
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    def list_plans(self):
        return PLANS

    def list_regions(self):
        return REGIONS

    @staticmethod
    def _extract_ipv4(data: dict) -> str:
        return ((data.get("ipConfig") or {}).get("v4") or {}).get("ip", "")

    def _upload_ssh_key(self, public_key: str, label: str) -> int:
        body = {"name": f"deployer-funis-{label}", "type": "ssh", "value": public_key}
        r = requests.post(f"{API_BASE}/secrets", headers=self._headers(), json=body, timeout=30)
        r.raise_for_status()
        return r.json()["data"][0]["secretId"]

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

        secret_id = self._upload_ssh_key(public_openssh, label)

        body = {
            "imageId": DEFAULT_UBUNTU_IMAGE_ID,
            "productId": plan_id,
            "region": region_id,
            "period": 1,
            "displayName": label[:255],
            "sshKeys": [secret_id],
            "defaultUser": "root",
        }
        r = requests.post(f"{API_BASE}/compute/instances", headers=self._headers(), json=body, timeout=60)
        r.raise_for_status()
        data = r.json()["data"][0]

        return VpsInstance(
            instance_id=str(data["instanceId"]),
            ip_address=self._extract_ipv4(data),
            status="provisioning",
            ssh_user="root",
            ssh_private_key=private_pem,
            region=region_id,
            plan=plan_id,
        )

    def get_instance(self, instance_id: str) -> VpsInstance:
        r = requests.get(f"{API_BASE}/compute/instances/{instance_id}", headers=self._headers(), timeout=30)
        r.raise_for_status()
        data = r.json()["data"][0]
        status = "ready" if data.get("status") == "running" else "provisioning"
        return VpsInstance(
            instance_id=str(data["instanceId"]),
            ip_address=self._extract_ipv4(data),
            status=status,
            region=data.get("region", ""),
            plan=data.get("productId", ""),
        )

    def destroy(self, instance_id: str) -> None:
        body = {"cancelDate": time.strftime("%Y-%m-%d")}
        r = requests.post(
            f"{API_BASE}/compute/instances/{instance_id}/cancel",
            headers=self._headers(),
            json=body,
            timeout=30,
        )
        r.raise_for_status()
