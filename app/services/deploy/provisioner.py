import re

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
    # Brace groups keep each systemctl best-effort without the trailing `|| true`
    # swallowing an apt failure the way `install && enable || true` did.
    "{ systemctl enable 'php*-fpm' 2>/dev/null || true; } && "
    # A newly installed extension is only picked up once the FPM workers respawn;
    # without this the deploy finishes green and the site keeps returning 500.
    "{ systemctl restart 'php*-fpm' 2>/dev/null || true; }"
)

# Funnels store config, rate limits and PIX transactions in SQLite, call the PIX
# gateway over curl and normalise UTF-8 text with mbstring. php-fpm ships with none
# of them, and one missing module throws on every request (PDOException: could not
# find driver) — nginx turns that into a bare HTTP 500 on an otherwise "live" funnel.
REQUIRED_PHP_MODULES = ("pdo_sqlite", "curl", "mbstring")


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


def _missing_php_modules(session) -> list[str]:
    """Which of REQUIRED_PHP_MODULES the remote PHP does not load.

    Reads the CLI SAPI (`php -m`) rather than the FPM binary because /usr/bin/php
    keeps its path across PHP versions while /usr/sbin/php-fpm8.1 does not — the
    same versioning problem discover_php_socket works around. On Debian/Ubuntu the
    cli and fpm conf.d directories carry identical extension symlinks, so the two
    report the same set. No php binary at all exits non-zero, which correctly counts
    everything as missing.
    """
    try:
        out = session.run("php -m")
    except Exception:
        return list(REQUIRED_PHP_MODULES)
    loaded = {line.strip().lower() for line in out.splitlines()}
    return [mod for mod in REQUIRED_PHP_MODULES if mod not in loaded]


def ensure_php(vps, log=lambda msg: None):
    """Installs php-fpm and the extensions funnels need, on demand.

    Checks the server itself instead of trusting vps.php_installed: that flag only
    records that some earlier deploy *ran* the install step, so a reused or
    pre-provisioned VPS — or one where apt half-failed — passes the flag check while
    PHP still has no pdo_sqlite. Every page of the resulting "live" funnel then 500s,
    and a retry skips the install too. Verifying makes the flag advisory and makes
    "Tentar novamente" an actual repair.
    """
    if vps.provider == "mock":
        return
    session = get_ssh_session(vps)
    session.connect()
    try:
        missing = _missing_php_modules(session)
        if not missing:
            return
        log(f"Instalando PHP-FPM e extensões ({', '.join(missing)})...")
        session.run(PHP_CMD, timeout=600)
        still_missing = _missing_php_modules(session)
        if still_missing:
            raise RuntimeError(
                "Extensões do PHP ausentes mesmo após a instalação: "
                f"{', '.join(still_missing)}. O funil responderia HTTP 500 — "
                "verifique o apt no VPS."
            )
    finally:
        session.close()


NODE_CMD = (
    "export DEBIAN_FRONTEND=noninteractive && "
    "apt-get update -y && "
    # build-essential + python3 back node-gyp, which better-sqlite3 falls back to
    # compiling from source whenever there's no prebuilt binary for this Node/ABI combo.
    "apt-get install -y curl ca-certificates build-essential python3 && "
    "curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && "
    "apt-get install -y nodejs"
)

REQUIRED_NODE_MAJOR = 20


def _installed_node_major(session) -> int:
    try:
        out = session.run("node --version").strip()  # e.g. "v20.11.0"
    except Exception:
        return 0
    m = re.match(r"^v(\d+)\.", out)
    return int(m.group(1)) if m else 0


def ensure_node(vps, log=lambda msg: None):
    """Installs Node (via NodeSource) on demand, verifying on the server rather than
    trusting any cached flag — mirrors ensure_php's reasoning: a reused or
    pre-provisioned VPS can silently lack Node even if an earlier deploy "installed" it."""
    if vps.provider == "mock":
        return
    session = get_ssh_session(vps)
    session.connect()
    try:
        if _installed_node_major(session) >= REQUIRED_NODE_MAJOR:
            return
        log(f"Instalando Node.js {REQUIRED_NODE_MAJOR}.x...")
        session.run(NODE_CMD, timeout=600)
        if _installed_node_major(session) < REQUIRED_NODE_MAJOR:
            raise RuntimeError(
                f"Node.js {REQUIRED_NODE_MAJOR}.x não encontrado mesmo após a instalação — "
                "verifique o apt/NodeSource no VPS."
            )
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
