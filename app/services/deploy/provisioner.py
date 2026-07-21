from .ssh import get_ssh_session

BOOTSTRAP_CMD = (
    "export DEBIAN_FRONTEND=noninteractive && "
    "apt-get update -y && "
    "apt-get install -y nginx certbot python3-certbot-nginx && "
    "systemctl enable nginx && systemctl start nginx"
)

PHP_CMD = (
    "export DEBIAN_FRONTEND=noninteractive && "
    "apt-get update -y && "
    # php-fpm alone ships without the SQLite PDO driver (funnels store config, rate
    # limits and PIX transactions in SQLite) nor curl (PIX gateway calls) — without
    # these, every DB/gateway call throws and PHP returns a bare HTTP 500.
    "apt-get install -y php-fpm php-sqlite3 php-curl php-mbstring && "
    "systemctl enable 'php*-fpm' 2>/dev/null || true"
)


def bootstrap_vps(vps, log=lambda msg: None):
    """Idempotent: installs nginx + certbot. Safe to run again on an already-bootstrapped VPS."""
    session = get_ssh_session(vps)
    log("Conectando via SSH...")
    session.connect()
    try:
        log("Instalando nginx e certbot...")
        session.run(BOOTSTRAP_CMD, timeout=600)
    finally:
        session.close()


def ensure_php(vps, log=lambda msg: None):
    """Installs php-fpm on demand for the first PHP funnel deployed to this VPS."""
    if vps.php_installed:
        return
    session = get_ssh_session(vps)
    session.connect()
    try:
        log("Instalando PHP-FPM...")
        session.run(PHP_CMD, timeout=300)
    finally:
        session.close()


def discover_php_socket(vps) -> str:
    """Returns the live php-fpm unix socket path on this VPS (version-dependent, e.g.
    /run/php/php8.1-fpm.sock), discovered fresh since it varies with the Ubuntu image's
    default PHP version and doesn't survive being hardcoded."""
    if vps.provider == "mock":
        return "/run/php/php-fpm.sock"
    session = get_ssh_session(vps)
    session.connect()
    try:
        out = session.run("ls /run/php/php*-fpm.sock 2>/dev/null | head -1").strip()
        if not out:
            raise RuntimeError("Socket do PHP-FPM não encontrado — verifique se php-fpm está instalado e rodando.")
        return out
    finally:
        session.close()
