import os
import time

from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user

from .. import db, jobs
from ..models import Deployment, User

bp = Blueprint("deployments", __name__, url_prefix="/deploys")

_TERMINAL_STATUSES = {"live", "error"}


@bp.route("/")
@login_required
def deployments_page():
    deployments = Deployment.query.filter_by(user_id=current_user.id).order_by(Deployment.created_at.desc()).all()
    return render_template("deployments.html", title="Deploys", deployments=deployments)


@bp.route("/<int:deployment_id>")
@login_required
def deployment_detail(deployment_id):
    dep = Deployment.query.filter_by(id=deployment_id, user_id=current_user.id).first_or_404()
    if not current_user.api_key:
        current_user.generate_api_key()
        db.session.commit()
    return render_template("deployment_detail.html", title="Deploy", dep=dep)


@bp.route("/<int:deployment_id>/retry", methods=["POST"])
@login_required
def retry_deployment(deployment_id):
    dep = Deployment.query.filter_by(id=deployment_id, user_id=current_user.id).first_or_404()
    dep.status = "queued"
    dep.last_message = "Reenfileirado."
    db.session.commit()
    jobs.start_retry_deployment_job(dep.id)
    flash("Deploy reenviado.", "success")
    return redirect(url_for("deployments.deployment_detail", deployment_id=dep.id))


@bp.route("/<int:deployment_id>/remover", methods=["POST"])
@login_required
def teardown_deployment(deployment_id):
    dep = Deployment.query.filter_by(id=deployment_id, user_id=current_user.id).first_or_404()
    jobs.start_teardown_deployment_job(dep.id)
    flash("Removendo deploy...", "success")
    return redirect(url_for("deployments.deployments_page"))


# ── WebSocket: live deploy log tail (registered via sock.route in __init__.py) ──

def handle_deployment_ws(ws):
    token = request.args.get("token", "").strip()
    deployment_id = request.args.get("id", type=int)

    user = User.query.filter_by(api_key=token).first() if token else None
    dep = db.session.get(Deployment, deployment_id) if deployment_id else None
    valid = bool(user and dep and dep.user_id == user.id)
    db.session.remove()

    if not valid:
        ws.close()
        return

    log_path = os.path.join(current_app.config["DEPLOY_LOGS_DIR"], f"{deployment_id}.log")
    sent_bytes = 0

    while True:
        if os.path.exists(log_path):
            with open(log_path, "rb") as f:
                f.seek(sent_bytes)
                chunk = f.read()
            if chunk:
                sent_bytes += len(chunk)
                for line in chunk.decode("utf-8", errors="replace").splitlines():
                    try:
                        ws.send(line)
                    except Exception:
                        return

        dep = db.session.get(Deployment, deployment_id)
        status = dep.status if dep else "error"
        db.session.remove()

        if status in _TERMINAL_STATUSES:
            try:
                ws.send(f"__STATUS__:{status}")
            except Exception:
                pass
            break

        time.sleep(1)
