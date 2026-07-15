from .base import RegistrarProvider
from .mock import MockRegistrarProvider
from .namecheap import NamecheapProvider
from .njalla import NjallaProvider

_PROVIDERS = {
    "mock": MockRegistrarProvider,
    "namecheap": NamecheapProvider,
    "njalla": NjallaProvider,
}


def list_registrar_providers(include_mock: bool = False):
    return [name for name in _PROVIDERS if include_mock or name != "mock"]


def get_registrar_provider(name: str, secret: dict) -> RegistrarProvider:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Registrador desconhecido: {name}")
    return cls(secret)


def provider_meta(name: str) -> dict:
    cls = _PROVIDERS.get(name)
    if not cls:
        raise ValueError(f"Registrador desconhecido: {name}")
    return {"fields": cls.FIELDS, "requires_contact": cls.REQUIRES_CONTACT, "billing": cls.BILLING}
