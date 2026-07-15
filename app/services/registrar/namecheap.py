import xml.etree.ElementTree as ET

import requests

from .base import RegistrarProvider

NS = "{http://api.namecheap.com/xml.response}"


class NamecheapProvider(RegistrarProvider):
    """secret must contain: api_user, api_key, client_ip (IP whitelisted in Namecheap's
    API access settings), and optionally: username (defaults to api_user),
    contact (dict with first_name, last_name, address1, city, state, postal_code, country,
    phone, email — required by Namecheap for domain registration)."""

    FIELDS = [
        {"name": "api_user", "label": "API User", "type": "text", "required": True, "help": ""},
        {"name": "api_key", "label": "API Key", "type": "password", "required": True, "help": ""},
        {"name": "client_ip", "label": "Client IP", "type": "text", "required": True, "help": "IP liberado no whitelist da API Namecheap (painel Namecheap → Profile → Tools → API Access)"},
        {"name": "username", "label": "Username (opcional)", "type": "text", "required": False, "help": "padrão: mesmo valor de API User"},
    ]
    REQUIRES_CONTACT = True
    BILLING = "Debita do saldo pré-pago da conta Namecheap — é preciso adicionar créditos antes de registrar domínios."

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._call("namecheap.users.getBalances")
        except RuntimeError as exc:
            return False, f"Namecheap rejeitou as credenciais: {exc}"
        except requests.RequestException as exc:
            return False, f"Falha de conexão com a Namecheap: {exc}"
        return True, "Conexão OK."

    def _base_url(self):
        return "https://api.namecheap.com/xml.response"

    def _params(self, command, extra=None):
        p = {
            "ApiUser": self.secret.get("api_user", ""),
            "ApiKey": self.secret.get("api_key", ""),
            "UserName": self.secret.get("username") or self.secret.get("api_user", ""),
            "ClientIp": self.secret.get("client_ip", ""),
            "Command": command,
        }
        if extra:
            p.update(extra)
        return p

    def _call(self, command, extra=None):
        r = requests.get(self._base_url(), params=self._params(command, extra), timeout=30)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        if root.attrib.get("Status") != "OK":
            errors = root.find(f"{NS}Errors")
            msg = "; ".join((e.text or "") for e in errors) if errors is not None else "Erro desconhecido na API Namecheap"
            raise RuntimeError(msg)
        return root

    def check_availability(self, domain: str) -> bool:
        root = self._call("namecheap.domains.check", {"DomainList": domain})
        result = root.find(f".//{NS}DomainCheckResult")
        return result is not None and result.attrib.get("Available") == "true"

    def register(self, domain: str, years: int = 1) -> str:
        extra = {"DomainName": domain, "Years": years}
        extra.update(self._contact_params())
        root = self._call("namecheap.domains.create", extra)
        result = root.find(f".//{NS}DomainCreateResult")
        if result is None or result.attrib.get("Registered") != "true":
            raise RuntimeError(f"Falha ao registrar {domain} via Namecheap")
        return result.attrib.get("DomainID", "")

    def set_dns_a(self, domain: str, ip_address: str) -> None:
        sld, _, tld = domain.partition(".")
        extra = {
            "SLD": sld,
            "TLD": tld,
            "HostName1": "@",
            "RecordType1": "A",
            "Address1": ip_address,
            "TTL1": "1800",
            "HostName2": "www",
            "RecordType2": "A",
            "Address2": ip_address,
            "TTL2": "1800",
        }
        self._call("namecheap.domains.dns.setHosts", extra)

    def _contact_params(self):
        c = self.secret.get("contact", {}) or {}
        fields = {}
        for role in ("Registrant", "Tech", "Admin", "AuxBilling"):
            fields[f"{role}FirstName"] = c.get("first_name", "")
            fields[f"{role}LastName"] = c.get("last_name", "")
            fields[f"{role}Address1"] = c.get("address1", "")
            fields[f"{role}City"] = c.get("city", "")
            fields[f"{role}StateProvince"] = c.get("state", "")
            fields[f"{role}PostalCode"] = c.get("postal_code", "")
            fields[f"{role}Country"] = c.get("country", "")
            fields[f"{role}Phone"] = c.get("phone", "")
            fields[f"{role}EmailAddress"] = c.get("email", "")
        return fields
