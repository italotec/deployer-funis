import random
import time

from .base import VpsProvider, VpsInstance

_FAKE_KEY = (
    "-----BEGIN OPENSSH PRIVATE KEY-----\n"
    "MOCKKEYNOTAREALKEYFORLOCALTESTINGONLY==\n"
    "-----END OPENSSH PRIVATE KEY-----\n"
)


class MockVpsProvider(VpsProvider):
    """Simulates a VPS provider — no network calls, instant 'ready' status.
    Used for local end-to-end testing of the deploy flow with zero spend."""

    BILLING = "Provedor de teste — nenhuma cobrança real."

    def test_connection(self):
        return True, "Mock OK — nenhuma chamada de rede realizada."

    def list_plans(self):
        return [
            {"id": "mock-small", "label": "Mock Small (1 vCPU / 2GB)", "price": "R$ 0,00"},
            {"id": "mock-medium", "label": "Mock Medium (2 vCPU / 4GB)", "price": "R$ 0,00"},
        ]

    def list_regions(self):
        return [
            {"id": "mock-region", "label": "Mock Region (local)"},
        ]

    def create_instance(self, plan_id, region_id, label):
        fake_ip = f"10.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        instance_id = f"mock-{int(time.time())}-{random.randint(1000, 9999)}"
        return VpsInstance(
            instance_id=instance_id,
            ip_address=fake_ip,
            status="ready",
            ssh_user="root",
            ssh_private_key=_FAKE_KEY,
            region=region_id,
            plan=plan_id,
        )

    def get_instance(self, instance_id):
        return VpsInstance(instance_id=instance_id, ip_address="10.0.0.1", status="ready")

    def destroy(self, instance_id):
        return None
