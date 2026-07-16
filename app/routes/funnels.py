from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from .. import db, jobs
from ..models import Funnel, Vps, Domain, DeployBatch, Deployment, ProviderCredential

bp = Blueprint("funnels", __name__, url_prefix="/funis")


@bp.route("/")
@login_required
def funnels_page():
    funnels = Funnel.query.filter_by(is_active=True).order_by(Funnel.name).all()
    return render_template("funnels.html", title="Funis", funnels=funnels)


@bp.route("/<int:funnel_id>")
@login_required
def funnel_detail(funnel_id):
    funnel = Funnel.query.filter_by(id=funnel_id, is_active=True).first_or_404()
    vpses = Vps.query.filter_by(user_id=current_user.id, status="ready").order_by(Vps.created_at.desc()).all()
    registrar_creds = ProviderCredential.query.filter_by(user_id=current_user.id, kind="registrar").order_by(ProviderCredential.label).all()
    return render_template(
        "funnel_detail.html",
        title=funnel.name,
        funnel=funnel,
        vpses=vpses,
        registrar_creds=registrar_creds,
    )


@bp.route("/<int:funnel_id>/deploy", methods=["POST"])
@login_required
def deploy_funnel(funnel_id):
    funnel = Funnel.query.filter_by(id=funnel_id, is_active=True).first_or_404()

    vps_id = request.form.get("vps_id", type=int)
    registrar_credential_id = request.form.get("registrar_credential_id", type=int)
    quantity = request.form.get("quantity", type=int) or 0

    vps = Vps.query.filter_by(id=vps_id, user_id=current_user.id, status="ready").first()
    if not vps:
        flash("Selecione um VPS válido (status 'ready').", "error")
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    registrar_cred = ProviderCredential.query.filter_by(
        id=registrar_credential_id, user_id=current_user.id, kind="registrar"
    ).first()
    if not registrar_cred:
        flash("Selecione uma credencial de registrador válida.", "error")
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    names = [n.strip().lower() for n in request.form.getlist("domains") if n.strip()]
    if quantity < 1 or len(names) != quantity:
        flash(f"Informe exatamente {quantity or 'a'} domínio(s), igual à quantidade escolhida.", "error")
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    batch = DeployBatch(user_id=current_user.id, funnel_id=funnel.id, vps_id=vps.id, quantity=quantity, status="queued")
    db.session.add(batch)
    db.session.flush()

    for name in names:
        domain = Domain.query.filter_by(user_id=current_user.id, name=name).first()
        if not domain:
            domain = Domain(user_id=current_user.id, registrar=registrar_cred.provider, name=name, status="registering")
            db.session.add(domain)
            db.session.flush()

        dep = Deployment(
            user_id=current_user.id,
            batch_id=batch.id,
            funnel_id=funnel.id,
            domain_id=domain.id,
            vps_id=vps.id,
            status="queued",
        )
        db.session.add(dep)

    db.session.commit()
    jobs.start_deploy_batch_job(batch.id)

    flash(f"Deploy iniciado para {quantity} domínio(s). Acompanhe em Deploys.", "success")
    return redirect(url_for("deployments.deployments_page"))
