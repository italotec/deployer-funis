from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user

from .. import db, jobs
from ..models import Vps, Deployment, ProviderCredential
from ..services.vps import get_vps_provider

bp = Blueprint("vps", __name__, url_prefix="/vps")


@bp.route("/")
@login_required
def vps_page():
    vpses = Vps.query.filter_by(user_id=current_user.id).order_by(Vps.created_at.desc()).all()
    creds = ProviderCredential.query.filter_by(user_id=current_user.id, kind="vps").order_by(ProviderCredential.label).all()

    plans_by_provider = {}
    regions_by_provider = {}
    for c in creds:
        if c.provider not in plans_by_provider:
            try:
                provider = get_vps_provider(c.provider, {})
                plans_by_provider[c.provider] = provider.list_plans()
                regions_by_provider[c.provider] = provider.list_regions()
            except Exception:
                plans_by_provider[c.provider] = []
                regions_by_provider[c.provider] = []

    return render_template(
        "vps.html",
        title="VPS",
        vpses=vpses,
        creds=creds,
        plans_by_provider=plans_by_provider,
        regions_by_provider=regions_by_provider,
    )


@bp.route("/comprar", methods=["POST"])
@login_required
def buy_vps():
    credential_id = request.form.get("credential_id", type=int)
    plan = request.form.get("plan", "").strip()
    region = request.form.get("region", "").strip()
    label = request.form.get("label", "").strip()

    cred = ProviderCredential.query.filter_by(id=credential_id, user_id=current_user.id, kind="vps").first()
    if not cred:
        flash("Credencial de VPS inválida.", "error")
        return redirect(url_for("vps.vps_page"))

    if not plan or not region:
        flash("Selecione um plano e uma região.", "error")
        return redirect(url_for("vps.vps_page"))

    vps = Vps(
        user_id=current_user.id,
        credential_id=cred.id,
        provider=cred.provider,
        label=label or f"{cred.provider}-{plan}",
        region=region,
        plan=plan,
        status="provisioning",
        last_message="Iniciando compra...",
    )
    db.session.add(vps)
    db.session.commit()

    jobs.start_vps_purchase_job(vps.id)

    flash("Compra de VPS iniciada. Acompanhe o status nesta página.", "success")
    return redirect(url_for("vps.vps_page"))


@bp.route("/manual", methods=["POST"])
@login_required
def add_manual_vps():
    label = request.form.get("label", "").strip()
    user = request.form.get("user", "").strip()
    ip = request.form.get("ip", "").strip()
    port = request.form.get("port", type=int) or 22
    password = request.form.get("password", "")

    if not user or not ip or not password:
        flash("Preencha usuário, IP e senha.", "error")
        return redirect(url_for("vps.vps_page"))

    vps = Vps(
        user_id=current_user.id,
        provider="manual",
        label=label or ip,
        ip_address=ip,
        ssh_user=user,
        ssh_port=port,
        status="provisioning",
        last_message="Configurando VPS manual...",
    )
    vps.set_ssh_password(password)
    db.session.add(vps)
    db.session.commit()

    jobs.start_manual_vps_bootstrap_job(vps.id)

    flash("VPS manual adicionado. Configurando nginx/certbot em segundo plano.", "success")
    return redirect(url_for("vps.vps_page"))


@bp.route("/<int:vps_id>/reprovisionar", methods=["POST"])
@login_required
def reprovision_vps(vps_id):
    vps = Vps.query.filter_by(id=vps_id, user_id=current_user.id).first_or_404()

    if not vps.ip_address:
        flash("Este VPS ainda não tem um IP — aguarde o provisionamento inicial.", "error")
        return redirect(url_for("vps.vps_page"))

    vps.status = "provisioning"
    vps.last_message = "Reexecutando instalação de nginx/certbot..."
    db.session.commit()

    jobs.start_manual_vps_bootstrap_job(vps.id)

    flash("Reprovisionamento iniciado. Acompanhe o status nesta página.", "success")
    return redirect(url_for("vps.vps_page"))


@bp.route("/<int:vps_id>/destruir", methods=["POST"])
@login_required
def destroy_vps(vps_id):
    vps = Vps.query.filter_by(id=vps_id, user_id=current_user.id).first_or_404()

    remaining = Deployment.query.filter_by(vps_id=vps.id).count()
    if remaining:
        flash("Remova todos os deploys deste VPS antes de destruí-lo.", "error")
        return redirect(url_for("vps.vps_page"))

    db.session.delete(vps)
    db.session.commit()
    flash("VPS removido do painel. Se ele ainda existir no provedor, cancele-o manualmente no painel do provedor.", "success")
    return redirect(url_for("vps.vps_page"))
