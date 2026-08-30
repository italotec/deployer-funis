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


def recent_logs(vps, domain: str, lines: int = 50) -> str:
    if vps.provider == "mock":
        return ""
    name = unit_name(domain)
    session = get_ssh_session(vps)
    session.connect()
    try:
        return session.run(f"journalctl -u {name} -n {lines} --no-pager || true")
    except Exception:
        return ""
    finally:
        session.close()
