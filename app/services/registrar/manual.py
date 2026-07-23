from .base import RegistrarProvider


class ManualRegistrarProvider(RegistrarProvider):
    """For domains bought outside the platform — DNS is managed by the user, so every
    registrar action is a no-op. The deploy flow still runs set_dns/wait_dns as usual;
    they just don't touch anything, and wait_dns's real DNS lookup confirms whether the
    user has actually pointed the A record at the VPS yet."""

    BILLING = "Domínio externo — DNS gerenciado manualmente pelo usuário."

    def test_connection(self):
        return True, "Domínio externo — nenhuma credencial necessária."

    def check_availability(self, domain: str) -> bool:
        return False

    def register(self, domain: str, years: int = 1) -> str:
        raise NotImplementedError("Domínios externos já estão registrados; não há registro a fazer.")

    def set_dns_a(self, domain: str, ip_address: str) -> None:
        return None
