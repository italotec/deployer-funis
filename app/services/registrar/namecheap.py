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

    def _get_hosts(self, domain: str) -> list[dict]:
        sld, _, tld = domain.partition(".")
        root = self._call("namecheap.domains.dns.getHosts", {"SLD": sld, "TLD": tld})
        return [
            {
                "Name": h.attrib.get("Name", ""),
                "Type": h.attrib.get("Type", ""),
                "Address": h.attrib.get("Address", ""),
                "MXPref": h.attrib.get("MXPref", "10"),
                "TTL": h.attrib.get("TTL", "1800"),
            }
            for h in root.iter(f"{NS}host")
        ]

    def _set_hosts(self, domain: str, hosts: list[dict]) -> None:
        # setHosts replaces the whole record set, so callers must pass every record to keep.
        sld, _, tld = domain.partition(".")
        extra = {"SLD": sld, "TLD": tld}
        for i, h in enumerate(hosts, start=1):
            extra[f"HostName{i}"] = h["Name"]
            extra[f"RecordType{i}"] = h["Type"]
            extra[f"Address{i}"] = h["Address"]
            extra[f"TTL{i}"] = h.get("TTL") or "1800"
            if h["Type"] == "MX":
                extra[f"MXPref{i}"] = h.get("MXPref") or "10"
        if any(h["Type"] == "MX" for h in hosts):
            extra["EmailType"] = "MX"
        self._call("namecheap.domains.dns.setHosts", extra)

    def set_dns_a(self, domain: str, ip_address: str) -> None:
        # Drop only what would conflict with the new A records (parking-page CNAME/URL
        # redirects on @ and www); keep the rest, e.g. the Search Console TXT record.
        conflicting = {"A", "AAAA", "CNAME", "URL", "URL301", "URLFRAME"}
        hosts = [h for h in self._get_hosts(domain) if not (h["Name"] in ("@", "www") and h["Type"] in conflicting)]
        hosts.append({"Name": "@", "Type": "A", "Address": ip_address, "TTL": "1800"})
        hosts.append({"Name": "www", "Type": "A", "Address": ip_address, "TTL": "1800"})
        self._set_hosts(domain, hosts)

    def add_txt_record(self, domain: str, value: str) -> None:
        hosts = self._get_hosts(domain)
        if any(h["Type"] == "TXT" and h["Name"] == "@" and h["Address"] == value for h in hosts):
            return
        hosts.append({"Name": "@", "Type": "TXT", "Address": value, "TTL": "1800"})
        self._set_hosts(domain, hosts)

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
