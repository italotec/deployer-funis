import os

import jinja2

from .ssh import get_ssh_session

_TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "nginx")
_env = jinja2.Environment(loader=jinja2.FileSystemLoader(_TEMPLATES_DIR))


_STACK_TEMPLATES = {
    "php": "php_site.conf.j2",
    "node": "node_site.conf.j2",
    "static": "site.conf.j2",
}


def render_site_conf(domain: str, webroot: str, stack: str, php_socket: str = "", app_port: int = 0) -> str:
    tpl = _env.get_template(_STACK_TEMPLATES.get(stack, "site.conf.j2"))
    return tpl.render(domain=domain, webroot=webroot, php_socket=php_socket, app_port=app_port)


def deploy_site_conf(vps, domain: str, conf_text: str, log=lambda msg: None) -> str:
    """Writes the nginx server block, enables it, tests, and reloads nginx. Returns the remote conf path."""
    session = get_ssh_session(vps)
    session.connect()
    try:
        available_path = f"/etc/nginx/sites-available/{domain}.conf"
        enabled_path = f"/etc/nginx/sites-enabled/{domain}.conf"
        session.write_file(available_path, conf_text)
        session.run(f"ln -sf {available_path} {enabled_path}")
        log("Testando configuração do nginx...")
        session.run("nginx -t")
        session.run("systemctl reload nginx")
        return available_path
    finally:
        session.close()


def remove_site_conf(vps, domain: str, log=lambda msg: None):
    session = get_ssh_session(vps)
    session.connect()
    try:
        session.run(f"rm -f /etc/nginx/sites-available/{domain}.conf /etc/nginx/sites-enabled/{domain}.conf")
        session.run("nginx -t && systemctl reload nginx || true")
    finally:
        session.close()
