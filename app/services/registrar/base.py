from abc import ABC, abstractmethod


class RegistrarProvider(ABC):
    """Common interface every domain registrar integration must implement.

    `secret` is the decrypted credential dict the user saved for this provider.
    """

    FIELDS: list[dict] = []
    REQUIRES_CONTACT: bool = False
    BILLING: str = ""

    def __init__(self, secret: dict):
        self.secret = secret or {}

    def test_connection(self) -> tuple[bool, str]:
        """Perform a lightweight, read-only call to confirm the stored credentials work.
        Providers should override this; default reports the check as unavailable."""
        return False, "Teste não suportado para este provedor."

    @abstractmethod
    def check_availability(self, domain: str) -> bool:
        ...

    @abstractmethod
    def register(self, domain: str, years: int = 1) -> str:
        """Register the domain. Returns a provider order/reference id (may be empty string)."""
        ...

    @abstractmethod
    def set_dns_a(self, domain: str, ip_address: str) -> None:
        """Point the domain's A record (root + www) at ip_address."""
        ...

    def get_status(self, domain: str) -> str:
        """Provider-side status of a domain already ordered on this account.

        Synchronous registrars own the domain the moment register() returns, so the
        default reports it active. Registrars that register asynchronously (e.g. Njalla,
        where register() only returns a task id) override this so callers can poll until
        the registration lands before editing DNS."""
        return "active"
