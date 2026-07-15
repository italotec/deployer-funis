import random

from .base import RegistrarProvider


class MockRegistrarProvider(RegistrarProvider):
    """Simulates a registrar — always available, instant fake registration.
    Used for local end-to-end testing of the deploy flow with zero spend."""

    BILLING = "Provedor de teste — nenhuma cobrança real."

    def test_connection(self):
        return True, "Mock OK — nenhuma chamada de rede realizada."

    def check_availability(self, domain: str) -> bool:
        return True

    def register(self, domain: str, years: int = 1) -> str:
        return f"mock-order-{random.randint(100000, 999999)}"

    def set_dns_a(self, domain: str, ip_address: str) -> None:
        return None
