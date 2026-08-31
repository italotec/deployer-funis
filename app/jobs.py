import os
import threading
import time

from flask import current_app

from . import db
from .models import Vps, Domain, Funnel, DeployBatch, Deployment, ProviderCredential
from .services.vps import get_vps_provider
from .services.registrar import get_registrar_provider
from .services.deploy import provisioner, deployer, ports


def _deploy_log_path(app, deployment_id):
    return os.path.join(app.config["DEPLOY_LOGS_DIR"], f"{deployment_id}.log")


def append_deploy_log(app, deployment_id, msg):
    os.makedirs(app.config["DEPLOY_LOGS_DIR"], exist_ok=True)
    with open(_deploy_log_path(app, deployment_id), "a", encoding="utf-8") as f:
        f.write(msg.rstrip("\n") + "\n")


def reset_deploy_log(app, deployment_id):
    os.makedirs(app.config["DEPLOY_LOGS_DIR"], exist_ok=True)
    open(_deploy_log_path(app, deployment_id), "w", encoding="utf-8").close()


def _run_single_deployment(app, deployment_id: int) -> bool:
    dep = db.session.get(Deployment, deployment_id)
    if not dep:
        return False

    reset_deploy_log(app, deployment_id)

    domain = db.session.get(Domain, dep.domain_id)
    vps = db.session.get(Vps, dep.vps_id)
    funnel = db.session.get(Funnel, dep.funnel_id)

    def log(msg):
        append_deploy_log(app, deployment_id, msg)
        d = db.session.get(Deployment, deployment_id)
        if d:
            d.last_message = msg
            db.session.commit()

    try:
        if domain.registrar == "manual":
            registrar_provider = get_registrar_provider("manual", {})
        else:
            # Authenticate as the exact account this domain belongs to. Falling back to
            # the first credential of the provider only covers legacy rows with no link;
            # with multiple accounts of the same registrar, the wrong one can't manage
            # the domain (Njalla returns "Permission denied" on its DNS records).
            cred = None
            if domain.credential_id:
                cred = ProviderCredential.query.filter_by(
                    id=domain.credential_id, user_id=dep.user_id, kind="registrar"
                ).first()
            if not cred:
                cred = ProviderCredential.query.filter_by(
                    user_id=dep.user_id, kind="registrar", provider=domain.registrar
                ).order_by(ProviderCredential.id).first()
            if not cred:
                raise RuntimeError(f"Nenhuma credencial cadastrada para o registrador '{domain.registrar}'.")
            registrar_provider = get_registrar_provider(cred.provider, cred.get_secret())

        if domain.status == "registering":
            dep.status = "registering_domain"
            db.session.commit()
            order_id = deployer.register_domain(domain, registrar_provider, log=log)
            domain.registrar_order_id = order_id or domain.registrar_order_id
            db.session.commit()
            deployer.wait_domain_registered(domain, registrar_provider, log=log)
            domain.status = "registered"
            db.session.commit()

        dep.status = "dns"
        db.session.commit()
        deployer.set_dns(domain, vps, registrar_provider, log=log)
        domain.status = "dns_set"
        db.session.commit()
        deployer.wait_dns(domain, vps, log=log)

        dep.status = "uploading"
        db.session.commit()
        webroot = deployer.upload_funnel(vps, funnel, app.config["FUNNELS_DIR"], domain.name, log=log)
        if funnel.has_php and not vps.php_installed:
            vps.php_installed = True
            db.session.commit()

        app_port = 0
        if funnel.stack == "node":
            # Reserved against the DB (not chosen later) because different batches run
            # in separate threads (start_deploy_batch_job) and could otherwise race to
            # pick the same port on the same VPS.
            app_port = ports.allocate_port(dep)

            dep.status = "installing"
            db.session.commit()
            deployer.install_node_deps(vps, funnel, webroot, log=log)

            dep.status = "starting"
            db.session.commit()
            deployer.start_node_service(vps, funnel, domain.name, webroot, app_port, log=log)

        dep.status = "nginx"
        db.session.commit()
        conf_path = deployer.configure_nginx(vps, funnel, domain.name, webroot, log=log, app_port=app_port)
        dep.nginx_conf_path = conf_path
        db.session.commit()

        dep.status = "ssl"
        db.session.commit()
        deployer.issue_ssl(vps, domain.name, app.config["LE_EMAIL"], log=log)

        dep.status = "live"
        dep.live_url = f"https://{domain.name}"
        dep.last_message = "Live."
        db.session.commit()
        log(f"Deploy concluído: {dep.live_url}")
        return True
    except Exception as exc:
        db.session.rollback()
        dep = db.session.get(Deployment, deployment_id)
        if dep:
            dep.status = "error"
            dep.last_message = f"Erro: {exc}"
            db.session.commit()
        append_deploy_log(app, deployment_id, f"ERRO: {exc}")
        return False


def start_deploy_batch_job(batch_id: int):
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            batch = db.session.get(DeployBatch, batch_id)
            if not batch:
                return
            batch.status = "running"
            db.session.commit()

            dep_ids = [d.id for d in Deployment.query.filter_by(batch_id=batch.id).all()]
            any_error = False
            for dep_id in dep_ids:
                ok = _run_single_deployment(app, dep_id)
                any_error = any_error or not ok

            batch = db.session.get(DeployBatch, batch_id)
            if batch:
                batch.status = "done_with_errors" if any_error else "done"
                db.session.commit()

    threading.Thread(target=runner, daemon=True).start()


def start_retry_deployment_job(deployment_id: int):
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            _run_single_deployment(app, deployment_id)

    threading.Thread(target=runner, daemon=True).start()


def start_teardown_deployment_job(deployment_id: int):
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            dep = db.session.get(Deployment, deployment_id)
            if not dep:
                return
            vps = db.session.get(Vps, dep.vps_id)
            domain = db.session.get(Domain, dep.domain_id)
            try:
                deployer.teardown(vps, domain.name, log=lambda m: append_deploy_log(app, deployment_id, m))
            except Exception as exc:
                append_deploy_log(app, deployment_id, f"Erro ao remover: {exc}")
            dep = db.session.get(Deployment, deployment_id)
            if dep:
                db.session.delete(dep)
                db.session.commit()

            log_path = _deploy_log_path(app, deployment_id)
            if os.path.exists(log_path):
                os.remove(log_path)

    threading.Thread(target=runner, daemon=True).start()


IP_POLL_ATTEMPTS = 90  # 90 x IP_POLL_INTERVAL ~= 15 min
IP_POLL_INTERVAL = 10  # seconds


def start_vps_purchase_job(vps_id: int):
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            vps = db.session.get(Vps, vps_id)
            if not vps:
                return
            reset_deploy_log(app, f"vps-{vps.id}")
            try:
                cred = db.session.get(ProviderCredential, vps.credential_id) if vps.credential_id else None
                secret = cred.get_secret() if cred else {}
                provider = get_vps_provider(vps.provider, secret)

                vps.last_message = "Criando instância no provedor..."
                db.session.commit()

                instance = provider.create_instance(vps.plan, vps.region, vps.label or f"vps-{vps.id}")
                vps.provider_instance_id = instance.instance_id
                vps.ip_address = instance.ip_address
                vps.ssh_user = instance.ssh_user or "root"
                if instance.ssh_private_key:
                    vps.set_ssh_key(instance.ssh_private_key)
                vps.last_message = "Instância criada, aguardando IP/boot..."
                db.session.commit()

                if vps.provider != "mock":
                    for _ in range(IP_POLL_ATTEMPTS):
                        info = provider.get_instance(vps.provider_instance_id)
                        if info.ip_address:
                            vps.ip_address = info.ip_address
                            db.session.commit()
                        if info.status == "ready" and vps.ip_address:
                            break
                        time.sleep(IP_POLL_INTERVAL)

                if not vps.ip_address:
                    raise RuntimeError("Provedor não retornou um endereço IP para a instância.")

                vps.last_message = "Instalando nginx e certbot..."
                db.session.commit()
                provisioner.bootstrap_vps(vps, log=lambda m: append_deploy_log(app, f"vps-{vps.id}", m))
                vps.bootstrapped = True
                vps.status = "ready"
                vps.last_message = "Pronto."
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                vps = db.session.get(Vps, vps_id)
                if vps:
                    vps.status = "error"
                    vps.last_message = f"Erro: {exc}"
                    db.session.commit()

    threading.Thread(target=runner, daemon=True).start()


def start_manual_vps_bootstrap_job(vps_id: int):
    app = current_app._get_current_object()

    def runner():
        with app.app_context():
            vps = db.session.get(Vps, vps_id)
            if not vps:
                return
            reset_deploy_log(app, f"vps-{vps.id}")
            try:
                vps.last_message = "Instalando nginx e certbot..."
                db.session.commit()
                provisioner.bootstrap_vps(vps, log=lambda m: append_deploy_log(app, f"vps-{vps.id}", m))
                vps.bootstrapped = True
                vps.status = "ready"
                vps.last_message = "Pronto."
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                vps = db.session.get(Vps, vps_id)
                if vps:
                    vps.status = "error"
                    vps.last_message = f"Erro: {exc}"
                    db.session.commit()

    threading.Thread(target=runner, daemon=True).start()
