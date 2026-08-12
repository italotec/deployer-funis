import json
import os
import secrets
import time

from . import provisioner, systemd
from .nginx import render_site_conf, deploy_site_conf, remove_site_conf
from .ssh import get_ssh_session

_PERSISTENT_STATE_ROOT = "/var/lib/funis"


def _persistent_state_dir(domain_name: str) -> str:
    return f"{_PERSISTENT_STATE_ROOT}/{domain_name}"


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


def _snapshot_persistent_state(session, webroot: str, domain_name: str):
    """Copies *.db/*.sqlite*/.env out of the current webroot before it's overwritten.

    A retry re-deploys the exact same zip to the same domain, and that zip may itself
    contain a same-named placeholder DB or .env — without this, upload_dir would
    silently overwrite a live Node funnel's real SQLite data (users, Pix transactions)
    and its ProsperidadePay key (configured later in the funnel's own admin panel, so it
    only ever exists on the server). Snapshot-and-restore rather than a symlink because
    the app may create its DB file at a path this deployer doesn't know in advance.
    """
    state_dir = _persistent_state_dir(domain_name)
    session.run(
        f"mkdir -p {state_dir}; "
        f"if [ -d {webroot} ]; then "
        f"(cd {webroot} && find . \\( -iname '*.db' -o -iname '*.sqlite*' -o -iname '.env' \\) "
        f"-exec cp --parents -t {state_dir} {{}} +); "
        f"fi; true"
    )


def _restore_persistent_state(session, webroot: str, domain_name: str):
    state_dir = _persistent_state_dir(domain_name)
    session.run(f"if [ -d {state_dir} ]; then cp -a {state_dir}/. {webroot}/; fi; true")


def upload_funnel(vps, funnel, funnels_dir: str, domain_name: str, log=lambda msg: None) -> str:
    if funnel.stack == "php":
        provisioner.ensure_php(vps, log=log)
    elif funnel.stack == "node":
        provisioner.ensure_node(vps, log=log)

    log("Enviando arquivos do funil...")
    webroot = f"/var/www/{domain_name}"
    local_dir = os.path.join(funnels_dir, funnel.storage_path)
    session = get_ssh_session(vps)
    session.connect()
    try:
        if funnel.stack == "node":
            _snapshot_persistent_state(session, webroot, domain_name)
        session.upload_dir(local_dir, webroot)
        if funnel.stack == "node":
            _restore_persistent_state(session, webroot, domain_name)
        if funnel.stack == "php":
            # Files are uploaded over SFTP as root, so they land root:root. php-fpm runs
            # as www-data and the funnel writes to SQLite DBs, logs/ and cache dirs at
            # runtime — without giving www-data ownership, the first write 500s.
            session.run(f"chown -R www-data:www-data {webroot}")
            session.run(f"find {webroot} -type d -exec chmod 775 {{}} +")
            session.run(f"find {webroot} -type f -exec chmod 664 {{}} +")
        # Node's chown happens later, in install_node_deps — after npm ci/build run as
        # root, so the files they create are covered by the same ownership pass instead
        # of being re-created root:root on top of an earlier chown.
    finally:
        session.close()
    return webroot


def install_node_deps(vps, funnel, webroot: str, log=lambda msg: None):
    """npm ci (or npm install, if no lockfile) + optional build, then hands the whole
    webroot to www-data — the same user the systemd unit runs the app as (systemd.py),
    so it can write its own SQLite file and any cache/log dirs at runtime."""
    if vps.provider == "mock":
        return
    app_dir = f"{webroot}/{funnel.app_root}" if funnel.app_root else webroot
    session = get_ssh_session(vps)
    session.connect()
    try:
        log("Instalando dependências (npm ci)...")
        has_lock = session.run(f"test -f {app_dir}/package-lock.json && echo 1 || echo 0").strip() == "1"
        install_cmd = "npm ci --omit=dev" if has_lock else "npm install --omit=dev"
        session.run(f"cd {app_dir} && {install_cmd}", timeout=1800)

        try:
            pkg = json.loads(session.run(f"cat {app_dir}/package.json"))
        except Exception:
            pkg = {}
        if (pkg.get("scripts") or {}).get("build"):
            has_output = session.run(
                f"test -d {app_dir}/dist -o -d {app_dir}/build && echo 1 || echo 0"
            ).strip() == "1"
            if not has_output:
                log("Rodando build (npm run build)...")
                session.run(f"cd {app_dir} && npm run build", timeout=1800)

        log("Ajustando permissões...")
        session.run(f"chown -R www-data:www-data {webroot}")
    finally:
        session.close()


def _ensure_node_env(vps, app_dir: str, app_port: int):
    """Merges required runtime vars into the app's .env without touching anything
    already there — a preserved .env from a prior deploy (_restore_persistent_state) or
    whatever the zip shipped both win over these. Only PORT, NODE_ENV and, when the file
    has no JWT_SECRET at all yet, a generated one are ever added."""
    session = get_ssh_session(vps)
    session.connect()
    try:
        existing = session.run(f"test -f {app_dir}/.env && cat {app_dir}/.env || true")
        keys = {}
        order = []
        for line in existing.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, v = stripped.partition("=")
            k = k.strip()
            if k not in keys:
                order.append(k)
            keys[k] = v

        changed = False
        if keys.get("PORT") != str(app_port):
            keys["PORT"] = str(app_port)
            if "PORT" not in order:
                order.append("PORT")
            changed = True
        if "NODE_ENV" not in keys:
            keys["NODE_ENV"] = "production"
            order.append("NODE_ENV")
            changed = True
        if "JWT_SECRET" not in keys:
            keys["JWT_SECRET"] = secrets.token_urlsafe(48)
            order.append("JWT_SECRET")
            changed = True

        if changed:
            content = "\n".join(f"{k}={keys[k]}" for k in order) + "\n"
            session.write_file(f"{app_dir}/.env", content)
    finally:
        session.close()


_HEALTH_CHECK_ATTEMPTS = 20
_HEALTH_CHECK_DELAY = 3


def start_node_service(vps, funnel, domain_name: str, webroot: str, app_port: int, log=lambda msg: None):
    if vps.provider == "mock":
        log("Modo mock: pulando inicialização real do serviço Node.")
        return

    app_dir = f"{webroot}/{funnel.app_root}" if funnel.app_root else webroot
    exec_start = f"/usr/bin/node {funnel.entry_file}" if funnel.entry_file else "/usr/bin/npm start"

    _ensure_node_env(vps, app_dir, app_port)

    session = get_ssh_session(vps)
    session.connect()
    try:
        unit_name = systemd.unit_name(domain_name)
        log("Parando processo anterior (se existir)...")
        session.run(f"systemctl stop {unit_name} 2>/dev/null || true")
        session.run(f"fuser -k {app_port}/tcp 2>/dev/null || true")
        time.sleep(1)
    finally:
        session.close()

    unit_text = systemd.render_unit(domain_name, app_dir, exec_start)
    systemd.deploy_unit(vps, domain_name, unit_text, log=log)

    log("Aguardando aplicação responder...")
    session = get_ssh_session(vps)
    session.connect()
    try:
        for _ in range(_HEALTH_CHECK_ATTEMPTS):
            try:
                session.run(f"curl -fsS -o /dev/null http://127.0.0.1:{app_port}/", timeout=10)
                return
            except Exception:
                time.sleep(_HEALTH_CHECK_DELAY)
    finally:
        session.close()

    tail = systemd.recent_logs(vps, domain_name)
    raise RuntimeError(
        f"Aplicação Node não respondeu em http://127.0.0.1:{app_port}/ após a inicialização.\n"
        f"Últimas linhas do log do serviço:\n{tail}"
    )


def configure_nginx(vps, funnel, domain_name: str, webroot: str, log=lambda msg: None, app_port: int = 0) -> str:
    log("Configurando nginx...")
    php_socket = provisioner.discover_php_socket(vps) if funnel.stack == "php" else ""
    conf_text = render_site_conf(domain_name, webroot, funnel.stack, php_socket, app_port)
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
    # Best-effort and unconditional — removing a unit that was never created (a
    # static/php funnel) is a harmless no-op (`systemctl disable --now <name> || true`).
    systemd.remove_unit(vps, domain_name, log=log)
    if vps.provider != "mock":
        session = get_ssh_session(vps)
        session.connect()
        try:
            session.run(f"rm -rf /var/www/{domain_name} {_persistent_state_dir(domain_name)}")
        finally:
            session.close()
