import os

import jinja2

from .ssh import get_ssh_session

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "systemd")
_env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATES_DIR))


def unit_name(domain: str) -> str:
    return f"funil-{domain}"


def render_unit(domain: str, app_dir: str, exec_start: str) -> str:
    tpl = _env.get_template("funnel.service.j2")
    return tpl.render(domain=domain, app_dir=app_dir, exec_start=exec_start)


def deploy_unit(vps, domain: str, unit_text: str, log=lambda msg: None):
    """Writes the systemd unit, reloads systemd and (re)starts + enables it (survives reboot)."""
    name = unit_name(domain)
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.write_file(f"/etc/systemd/system/{name}.service", unit_text)
        session.run("systemctl daemon-reload")
        log("Iniciando serviço Node...")
        session.run(f"systemctl enable --now {name}")
    finally:
        session.close()


def stop_unit(vps, domain: str, log=lambda msg: None):
    """Stops and disables the unit without removing its files — used when a deploy fails
    to become healthy. The unit is `enable`d with Restart=always, so left alone a
    crash-looping funnel keeps squatting whatever port it hardcoded (e.g. 3000), and the
    next deploy that wants that port dies with EADDRINUSE. Disabling --now frees it."""
    name = unit_name(domain)
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.run(f"systemctl disable --now {name} 2>/dev/null || true")
    finally:
        session.close()


def remove_unit(vps, domain: str, log=lambda msg: None):
    name = unit_name(domain)
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.run(f"systemctl disable --now {name} || true")
        session.run(f"rm -f /etc/systemd/system/{name}.service")
        session.run("systemctl daemon-reload || true")
    finally:
        session.close()


def recent_logs(vps, domain: str, lines: int = 50, since: str = "") -> str:
    if vps.provider == "mock":
        return ""
    name = unit_name(domain)
    session = get_ssh_session(vps)
    session.connect()
    try:
        # `since` scopes the log to the current deploy attempt. A funnel that crash-loops
        # (Restart=always) fills the last N lines with the SAME recurring error — often an
        # EADDRINUSE from an earlier restart colliding with itself — burying the real
        # first-boot cause. Pulling everything since the attempt began keeps that cause in
        # view; we drop -n so the window, not a line count, bounds the output.
        scope = f'--since "{since}"' if since else f"-n {lines}"
        return session.run(f"journalctl -u {name} {scope} --no-pager || true")
    except Exception:
        return ""
    finally:
        session.close()
