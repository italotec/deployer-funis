from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from .. import db
from ..models import Domain, Deployment, ProviderCredential
from ..services.registrar import get_registrar_provider

bp = Blueprint("domains", __name__, url_prefix="/dominios")


@bp.route("/")
@login_required
def domains_page():
    domains = Domain.query.filter_by(user_id=current_user.id).order_by(Domain.created_at.desc()).all()
    creds = ProviderCredential.query.filter_by(user_id=current_user.id, kind="registrar").order_by(ProviderCredential.label).all()
    return render_template("domains.html", title="Domínios", domains=domains, creds=creds)


@bp.route("/verificar", methods=["POST"])
@login_required
def check_domain():
    name = request.form.get("name", "").strip().lower()
    credential_id = request.form.get("credential_id", type=int)
    cred = ProviderCredential.query.filter_by(id=credential_id, user_id=current_user.id, kind="registrar").first()
    if not cred or not name:
        flash("Preencha o domínio e selecione uma credencial.", "error")
        return redirect(url_for("domains.domains_page"))
    try:
        provider = get_registrar_provider(cred.provider, cred.get_secret())
        available = provider.check_availability(name)
        flash(f"{name} está {'DISPONÍVEL' if available else 'INDISPONÍVEL'}.", "success" if available else "error")
    except Exception as exc:
        flash(f"Erro ao verificar domínio: {exc}", "error")
    return redirect(url_for("domains.domains_page"))


@bp.route("/verificar-json", methods=["POST"])
@login_required
def check_domain_json():
    name = request.form.get("name", "").strip().lower()
    credential_id = request.form.get("credential_id", type=int)
    cred = ProviderCredential.query.filter_by(id=credential_id, user_id=current_user.id, kind="registrar").first()
    if not cred or not name:
        return jsonify({"ok": False, "message": "Domínio ou credencial inválidos."}), 400
    try:
        provider = get_registrar_provider(cred.provider, cred.get_secret())
        available = provider.check_availability(name)
        return jsonify({"ok": True, "available": available, "name": name})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})


@bp.route("/externo", methods=["POST"])
@login_required
def add_manual_domain():
    name = request.form.get("name", "").strip().lower()
    if not name:
        flash("Informe o domínio.", "error")
        return redirect(url_for("domains.domains_page"))

    if Domain.query.filter_by(user_id=current_user.id, name=name).first():
        flash("Você já tem esse domínio cadastrado.", "error")
        return redirect(url_for("domains.domains_page"))

    domain = Domain(
        user_id=current_user.id,
        registrar="manual",
        name=name,
        status="registered",
        last_message="Domínio externo — aponte o registro DNS tipo A para o IP do VPS de destino.",
    )
    db.session.add(domain)
    db.session.commit()

    flash(f"{name} adicionado. Aponte o DNS dele para o IP do VPS de destino ao implantar.", "success")
    return redirect(url_for("domains.domains_page"))


@bp.route("/<int:domain_id>/excluir", methods=["POST"])
@login_required
def delete_domain(domain_id):
    domain = Domain.query.filter_by(id=domain_id, user_id=current_user.id).first_or_404()

    in_use = Deployment.query.filter_by(domain_id=domain.id).count()
    if in_use:
        flash("Remova os funis implantados neste domínio antes de excluí-lo.", "error")
        return redirect(url_for("domains.domains_page"))

    name = domain.name
    db.session.delete(domain)
    db.session.commit()
    flash(
        f"{name} removido do painel. Se ele foi registrado num provedor, "
        "o registro continua ativo lá — cancele-o no painel do registrador se quiser.",
        "success",
    )
    return redirect(url_for("domains.domains_page"))


@bp.route("/registrar", methods=["POST"])
@login_required
def register_domain():
    name = request.form.get("name", "").strip().lower()
    credential_id = request.form.get("credential_id", type=int)
    cred = ProviderCredential.query.filter_by(id=credential_id, user_id=current_user.id, kind="registrar").first()
    if not cred or not name:
        flash("Preencha o domínio e selecione uma credencial.", "error")
        return redirect(url_for("domains.domains_page"))

    if Domain.query.filter_by(user_id=current_user.id, name=name).first():
        flash("Você já tem esse domínio cadastrado.", "error")
        return redirect(url_for("domains.domains_page"))

    domain = Domain(user_id=current_user.id, registrar=cred.provider, name=name, status="registering")
    db.session.add(domain)
    db.session.commit()

    try:
        provider = get_registrar_provider(cred.provider, cred.get_secret())
        order_id = provider.register(name)
        domain.registrar_order_id = order_id or ""
        domain.status = "registered"
        domain.last_message = "Registrado com sucesso."
        db.session.commit()
        flash(f"{name} registrado com sucesso.", "success")
    except Exception as exc:
        domain.status = "error"
        domain.last_message = str(exc)
        db.session.commit()
        flash(f"Erro ao registrar {name}: {exc}", "error")

    return redirect(url_for("domains.domains_page"))
