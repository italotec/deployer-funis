from .base import VpsProvider
from .mock import MockVpsProvider
from .contabo import ContaboProvider

_PROVIDERS = {
    "mock": MockVpsProvider,
    "contabo": ContaboProvider,
}


def list_vps_providers(include_mock: bool = False):
    return [name for name in _PROVIDERS if include_mock or name != "mock"]


def get_vps_provider(name: str, secret: dict) -> VpsProvider:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Provedor de VPS desconhecido: {name}")
    return cls(secret)


def provider_meta(name: str) -> dict:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Provedor de VPS desconhecido: {name}")
    return {"fields": cls.FIELDS, "requires_contact": False, "billing": cls.BILLING}
