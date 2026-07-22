import os
import time

from . import provisioner
from .nginx import render_site_conf, deploy_site_conf, remove_site_conf
from .ssh import get_ssh_session


def dns_propagated(domain: str, expected_ip: str, attempts: int = 10, delay: int = 6) -> bool:
    import dns.resolver

    resolver = dns.resolver.Resolver()
    for _ in range(attempts):
        try:
            answers = resolver.resolve(domain, "A")
            ips = {r.to_text() for r in answers}
            if expected_ip in ips:
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def register_domain(domain, registrar_provider, log=lambda msg: None) -> str:
    log(f"Registrando domínio {domain.name}...")
    return registrar_provider.register(domain.name)


_DOMAIN_READY_STATUSES = {"active"}


def wait_domain_registered(domain, registrar_provider, log=lambda msg: None,
                           attempts: int = 60, delay: int = 10):
    """Wait until the domain is actually owned by the account before touching DNS.

    Some registrars (Njalla) register asynchronously: register() returns a task id and
    the domain isn't usable yet — DNS edits are rejected with 'Permission denied' until
    the registration task completes. Poll get_status() until the domain reports ready.
    Synchronous registrars report 'active' immediately, so this returns on the first
    iteration for them. Status lookups may raise while the domain is still pending (it
    isn't in the account yet), so those are treated as 'not ready' and retried."""
    for _ in range(attempts):
        try:
            status = (registrar_provider.get_status(domain.name) or "").lower()
        except Exception:
            status = ""
        if status in _DOMAIN_READY_STATUSES:
            return
        log("Aguardando confirmação do registro do domínio...")
        time.sleep(delay)
    log("Aviso: registro do domínio ainda não confirmado — prosseguindo mesmo assim.")


def set_dns(domain, vps, registrar_provider, log=lambda msg: None):
    log(f"Apontando DNS de {domain.name} para {vps.ip_address}...")
    registrar_provider.set_dns_a(domain.name, vps.ip_address)


def wait_dns(domain, vps, log=lambda msg: None):
    if vps.provider == "mock":
        return
    log("Aguardando propagação de DNS...")
    if not dns_propagated(domain.name, vps.ip_address):
        log("Aviso: DNS ainda não propagou totalmente — prosseguindo mesmo assim.")


def upload_funnel(vps, funnel, funnels_dir: str, domain_name: str, log=lambda msg: None) -> str:
    if funnel.has_php:
        provisioner.ensure_php(vps, log=log)

    log("Enviando arquivos do funil...")
    webroot = f"/var/www/{domain_name}"
    local_dir = os.path.join(funnels_dir, funnel.storage_path)
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.upload_dir(local_dir, webroot)
        if funnel.has_php:
            # Files are uploaded over SFTP as root, so they land root:root. php-fpm runs
            # as www-data and the funnel writes to SQLite DBs, logs/ and cache dirs at
            # runtime — without giving www-data ownership, the first write 500s.
            session.run(f"chown -R www-data:www-data {webroot}")
            session.run(f"find {webroot} -type d -exec chmod 775 {{}} +")
            session.run(f"find {webroot} -type f -exec chmod 664 {{}} +")
    finally:
        session.close()
    return webroot


def configure_nginx(vps, funnel, domain_name: str, webroot: str, log=lambda msg: None) -> str:
    log("Configurando nginx...")
    php_socket = provisioner.discover_php_socket(vps) if funnel.has_php else ""
    conf_text = render_site_conf(domain_name, webroot, funnel.has_php, php_socket)
    return deploy_site_conf(vps, domain_name, conf_text, log=log)


_FORBIDDEN_LE_EMAIL_DOMAINS = ("example.com", "example.net", "example.org")


def issue_ssl(vps, domain_name: str, le_email: str, log=lambda msg: None):
    if vps.provider == "mock":
        log("Modo mock: pulando emissão real de certificado SSL.")
        return
    if not le_email or le_email.split("@")[-1].lower() in _FORBIDDEN_LE_EMAIL_DOMAINS:
        raise RuntimeError(
            "Configure um e-mail válido em LE_EMAIL — o Let's Encrypt recusa endereços vazios ou @example.com/.net/.org."
        )
    log("Emitindo certificado SSL (Let's Encrypt)...")
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.run(
            f"certbot --nginx -d {domain_name} -d www.{domain_name} "
            f"--non-interactive --agree-tos -m {le_email} --redirect",
            timeout=180,
        )
    finally:
        session.close()


def teardown(vps, domain_name: str, log=lambda msg: None):
    log("Removendo site do nginx...")
    remove_site_conf(vps, domain_name, log=log)
    if vps.provider != "mock":
        session = get_ssh_session(vps)
        session.connect()
        try:
            session.run(f"rm -rf /var/www/{domain_name}")
        finally:
            session.close()
