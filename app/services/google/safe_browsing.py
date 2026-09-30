import requests

_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
_THREAT_TYPES = ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE", "POTENTIALLY_HARMFUL_APPLICATION"]
_BATCH = 250  # domains per request (2 URLs each; the API accepts up to 500 entries)


class SafeBrowsingError(RuntimeError):
    pass


def check_domains(api_key: str, domains: list[str]) -> dict[str, list[str]]:
    """Look the domains up on Google's Safe Browsing lists.
    Returns {domain: [threat types]} for the flagged ones only; clean domains are absent."""
    if not api_key:
        raise SafeBrowsingError("SAFE_BROWSING_API_KEY não configurada no .env.")

    flagged: dict[str, list[str]] = {}
    for i in range(0, len(domains), _BATCH):
        chunk = domains[i:i + _BATCH]
        url_to_domain = {}
        for d in chunk:
            url_to_domain[f"https://{d}/"] = d
            url_to_domain[f"http://{d}/"] = d
        body = {
            "client": {"clientId": "deployer-funis", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": _THREAT_TYPES,
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": u} for u in url_to_domain],
            },
        }
        r = requests.post(_URL, params={"key": api_key}, json=body, timeout=30)
        if r.status_code != 200:
            try:
                msg = r.json()["error"]["message"]
            except Exception:
                msg = f"HTTP {r.status_code}"
            raise SafeBrowsingError(msg)
        for m in r.json().get("matches", []):
            domain = url_to_domain.get(m.get("threat", {}).get("url", ""))
            if domain:
                threats = flagged.setdefault(domain, [])
                if m["threatType"] not in threats:
                    threats.append(m["threatType"])
    return flagged
