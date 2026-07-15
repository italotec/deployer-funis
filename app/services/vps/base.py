from abc import ABC, abstractmethod


class VpsInstance:
    def __init__(self, instance_id, ip_address, status, ssh_user="root", ssh_private_key="", region="", plan=""):
        self.instance_id = instance_id
        self.ip_address = ip_address
        self.status = status  # "provisioning" | "ready" | "error"
        self.ssh_user = ssh_user
        self.ssh_private_key = ssh_private_key  # PEM, only populated on create_instance()
        self.region = region
        self.plan = plan


class VpsProvider(ABC):
    """Common interface every VPS provider integration must implement.

    `secret` is the decrypted credential dict the user saved for this provider
    (e.g. {"client_id": "...", "client_secret": "...", "api_user": "...", "api_password": "..."}).
    """

    FIELDS: list[dict] = []
    BILLING: str = ""

    def __init__(self, secret: dict):
        self.secret = secret or {}

    def test_connection(self) -> tuple[bool, str]:
        """Perform a lightweight, read-only call to confirm the stored credentials work.
        Providers should override this; default reports the check as unavailable."""
        return False, "Teste não suportado para este provedor."

    @abstractmethod
    def list_plans(self) -> list[dict]:
        """Return [{"id": "...", "label": "...", "price": "..."}]"""
        ...

    @abstractmethod
    def list_regions(self) -> list[dict]:
        """Return [{"id": "...", "label": "..."}]"""
        ...

    @abstractmethod
    def create_instance(self, plan_id: str, region_id: str, label: str) -> VpsInstance:
        ...

    @abstractmethod
    def get_instance(self, instance_id: str) -> VpsInstance:
        ...

    @abstractmethod
    def destroy(self, instance_id: str) -> None:
        ...
