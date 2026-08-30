"""Read-only Contabo diagnostic.

Uses a saved credential to check auth, list the Ubuntu 22.04 image catalog, list any
existing instances (to see real productId/region values on this account), and print
the exact body `create_instance()` would send — without ever calling
POST /compute/instances or POST /secrets. Nothing here creates resources or costs money.

Usage:
    python scripts/contabo_check.py [--credential-id N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from app import create_app
from app.models import ProviderCredential
from app.services.vps.contabo import (
    ContaboProvider, PLANS, REGIONS, DEFAULT_UBUNTU_IMAGE_ID, UBUNTU_2204_RE,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-id", type=int, default=None)
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        query = ProviderCredential.query.filter_by(kind="vps", provider="contabo")
        if args.credential_id:
            cred = query.filter_by(id=args.credential_id).first()
            if not cred:
                print(f"Nenhuma credencial Contabo com id={args.credential_id}.")
                sys.exit(1)
        else:
            creds = query.order_by(ProviderCredential.id).all()
            if not creds:
                print("Nenhuma credencial Contabo cadastrada.")
                sys.exit(1)
            if len(creds) > 1:
                print("Mais de uma credencial Contabo encontrada, use --credential-id:")
                for c in creds:
                    print(f"  id={c.id}  label={c.label!r}")
                sys.exit(1)
            cred = creds[0]

        print(f"Usando credencial id={cred.id} label={cred.label!r}\n")
        provider = ContaboProvider(cred.get_secret())

        print("== Autenticação ==")
        try:
            provider._token()
            print("OK — token obtido.\n")
        except Exception as exc:
            print(f"FALHOU: {exc}")
            sys.exit(1)

        print("== Catálogo de imagens (GET /compute/images) ==")
        try:
            body = provider._request("GET", "/compute/images", params={"standardImage": "true", "size": 100})
            images = body.get("data", [])
            ubuntu_images = [
                img for img in images
                if UBUNTU_2204_RE.match((img.get("name") or "").strip())
            ]
            hardcoded_present = any(img.get("imageId") == DEFAULT_UBUNTU_IMAGE_ID for img in images)
            print(f"{len(images)} imagens no catálogo, {len(ubuntu_images)} casam com Ubuntu 22.04.")
            print(f"DEFAULT_UBUNTU_IMAGE_ID ({DEFAULT_UBUNTU_IMAGE_ID}) está no catálogo? {hardcoded_present}")
            for img in ubuntu_images[:5]:
                print(f"  imageId={img.get('imageId')}  name={img.get('name')!r}  creationDate={img.get('creationDate')}")
            if not ubuntu_images:
                print("  Nenhuma imagem Ubuntu 22.04 encontrada — create_instance() usaria o fallback hardcoded.")
            print()
        except Exception as exc:
            print(f"FALHOU: {exc}\n")

        print("== Instâncias existentes (GET /compute/instances) ==")
        try:
            body = provider._request("GET", "/compute/instances")
            instances = body.get("data", [])
            print(f"{len(instances)} instância(s) na conta.")
            for inst in instances:
                print(f"  instanceId={inst.get('instanceId')}  productId={inst.get('productId')}  region={inst.get('region')}  status={inst.get('status')}")
            if not instances:
                print("  Nenhuma instância existente — não é possível confirmar productId/region reais por esta via.")
            print()
        except Exception as exc:
            print(f"FALHOU: {exc}\n")

        print("== Configuração atual do app ==")
        print(f"PLANS (productId) configurados: {[p['id'] for p in PLANS]}")
        print(f"REGIONS configuradas: {[r['id'] for r in REGIONS]}")
        print()

        print("== Corpo que create_instance() enviaria (dry-run, nada é criado) ==")
        try:
            resolved_image_id = provider._resolve_ubuntu_image_id()
        except Exception as exc:
            resolved_image_id = f"<falhou ao resolver: {exc}>"
        sample_plan = PLANS[0]["id"] if PLANS else "<sem plano configurado>"
        sample_region = REGIONS[0]["id"] if REGIONS else "<sem região configurada>"
        print({
            "imageId": resolved_image_id,
            "productId": sample_plan,
            "region": sample_region,
            "period": 1,
            "displayName": "deployer-funis-check",
            "sshKeys": ["<seria o secretId retornado por POST /secrets>"],
            "defaultUser": "root",
        })


if __name__ == "__main__":
    main()
