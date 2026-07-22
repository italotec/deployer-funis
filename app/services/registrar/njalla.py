import requests

from .base import RegistrarProvider

BASE_URL = "https://njal.la/api/1/"


class NjallaProvider(RegistrarProvider):
    """secret must contain: api_token."""

    FIELDS = [
        {"name": "api_token", "label": "API Token", "type": "password", "required": True, "help": ""},
    ]
    BILLING = "Debita do saldo pré-pago (wallet) da conta Njalla — é preciso adicionar créditos antes de registrar domínios."

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._call("list-domains")
        except RuntimeError as exc:
            return False, f"Njalla rejeitou as credenciais: {exc}"
        except requests.RequestException as exc:
            return False, f"Falha de conexão com a Njalla: {exc}"
        return True, "Conexão OK."

    def _headers(self):
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Njalla " + self.secret.get("api_token", ""),
            "Referer": "https://njal.la/",
        }

    def _call(self, method: str, params: dict | None = None) -> dict:
        body = {"method": method, "params": params or {}}
        r = requests.post(BASE_URL, json=body, headers=self._headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Erro desconhecido na API Njalla"))
        return data.get("result", {})

    def check_availability(self, domain: str) -> bool:
        result = self._call("find-domains", {"query": domain})
        for d in result.get("domains", []):
            if d.get("name") == domain:
                return str(d.get("status", "")).lower() == "available"
        return False

    def register(self, domain: str, years: int = 1) -> str:
        result = self._call("register-domain", {"domain": domain, "years": years})
        # register-domain is async on Njalla's side and returns a task id;
        # completion is confirmed by polling get_status() (get-domain) from the caller.
        return str(result.get("task", ""))

    def _upsert_a_record(self, domain: str, name: str, ip_address: str, ttl: int = 10800) -> None:
        existing = self._call("list-records", {"domain": domain}).get("records", [])
        match = next((r for r in existing if r.get("type") == "A" and r.get("name") == name), None)
        if match is None:
            self._call("add-record", {"domain": domain, "type": "A", "name": name, "content": ip_address, "ttl": ttl})
        elif match.get("content") != ip_address:
            self._call("edit-record", {"domain": domain, "id": match["id"], "type": "A", "name": name, "content": ip_address, "ttl": ttl})

    def set_dns_a(self, domain: str, ip_address: str) -> None:
        # add-record is not idempotent — redeploying a domain that already has A records
        # (e.g. a deploy that failed after DNS was set) would otherwise create duplicates.
        self._upsert_a_record(domain, "@", ip_address)
        self._upsert_a_record(domain, "www", ip_address)

    def get_status(self, domain: str) -> str:
        result = self._call("get-domain", {"domain": domain})
        return str(result.get("status", ""))
