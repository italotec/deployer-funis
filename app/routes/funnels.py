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

    live_deployment_by_domain = {}
    for dep in Deployment.query.filter_by(user_id=current_user.id, status="live").all():
        live_deployment_by_domain[dep.domain_id] = dep

    owned_domains = []
    for d in Domain.query.filter_by(user_id=current_user.id).order_by(Domain.name).all():
        live_dep = live_deployment_by_domain.get(d.id)
        if live_dep:
            label = f'em uso por "{live_dep.funnel.name}"'
        elif d.status == "registering":
            label = "registrando…"
        elif d.status == "error":
            label = f"erro: {d.last_message}" if d.last_message else "erro"
        else:
            label = "pronto"
        owned_domains.append({"domain": d, "in_use": live_dep is not None, "label": label})

    return render_template(
        "funnel_detail.html",
        title=funnel.name,
        funnel=funnel,
        vpses=vpses,
        registrar_creds=registrar_creds,
        owned_domains=owned_domains,
    )


@bp.route("/<int:funnel_id>/deploy", methods=["POST"])
@login_required
def deploy_funnel(funnel_id):
    funnel = Funnel.query.filter_by(id=funnel_id, is_active=True).first_or_404()

    vps_id = request.form.get("vps_id", type=int)
    registrar_credential_id = request.form.get("registrar_credential_id", type=int)

    vps = Vps.query.filter_by(id=vps_id, user_id=current_user.id, status="ready").first()
    if not vps:
        flash("Selecione um VPS válido (status 'ready').", "error")
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    registrar_cred = None
    if registrar_credential_id:
        registrar_cred = ProviderCredential.query.filter_by(
            id=registrar_credential_id, user_id=current_user.id, kind="registrar"
        ).first()
        if not registrar_cred:
            flash("Selecione uma credencial de registrador válida.", "error")
            return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    seen = set()
    names = []
    for n in request.form.getlist("domains"):
        n = n.strip().lower()
        if n and n not in seen:
            seen.add(n)
            names.append(n)

    if not names:
        flash("Selecione ao menos um domínio (já seu ou novo).", "error")
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    existing_by_name = {
        d.name: d for d in Domain.query.filter_by(user_id=current_user.id).filter(Domain.name.in_(names)).all()
    }
    new_names = [n for n in names if n not in existing_by_name]
    if new_names and not registrar_cred:
        flash(
            "Selecione um registrador para registrar os novos domínios: " + ", ".join(new_names),
            "error",
        )
        return redirect(url_for("funnels.funnel_detail", funnel_id=funnel_id))

    batch = DeployBatch(user_id=current_user.id, funnel_id=funnel.id, vps_id=vps.id, quantity=len(names), status="queued")
    db.session.add(batch)
    db.session.flush()

    for name in names:
        domain = existing_by_name.get(name)
        if not domain:
            domain = Domain(user_id=current_user.id, registrar=registrar_cred.provider, name=name, status="registering")
            db.session.add(domain)
            db.session.flush()
        elif domain.status not in ("registered", "dns_set"):
            domain.status = "registering"

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

    flash(f"Deploy iniciado para {len(names)} domínio(s). Acompanhe em Deploys.", "success")
    return redirect(url_for("deployments.deployments_page"))
