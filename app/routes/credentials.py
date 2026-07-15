import json

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from .. import db
from ..models import ProviderCredential
from ..services.vps import list_vps_providers, get_vps_provider, provider_meta as vps_provider_meta
from ..services.registrar import list_registrar_providers, get_registrar_provider, provider_meta as registrar_provider_meta

bp = Blueprint("credentials", __name__, url_prefix="/credenciais")


def _build_provider_meta():
    return {
        "vps": {name: vps_provider_meta(name) for name in list_vps_providers()},
        "registrar": {name: registrar_provider_meta(name) for name in list_registrar_providers()},
    }


@bp.route("/")
@login_required
def credentials_page():
    creds = ProviderCredential.query.filter_by(user_id=current_user.id).order_by(ProviderCredential.created_at.desc()).all()
    return render_template(
        "credentials.html",
        title="Credenciais",
        creds=creds,
        vps_providers=list_vps_providers(),
        registrar_providers=list_registrar_providers(),
        provider_meta_json=json.dumps(_build_provider_meta()),
    )


@bp.route("/nova", methods=["POST"])
@login_required
def create_credential():
    kind = request.form.get("kind", "").strip()
    provider = request.form.get("provider", "").strip()
    label = request.form.get("label", "").strip()

    if kind not in ("vps", "registrar"):
        flash("Tipo de credencial inválido.", "error")
        return redirect(url_for("credentials.credentials_page"))

    valid_providers = list_vps_providers() if kind == "vps" else list_registrar_providers()
    if provider not in valid_providers:
        flash("Provedor inválido.", "error")
        return redirect(url_for("credentials.credentials_page"))

    # Collect provider-specific secret fields submitted by the form (secret_<field>=value)
    secret = {}
    for k, v in request.form.items():
        if k.startswith("secret_") and v.strip():
            secret[k[len("secret_"):]] = v.strip()

    contact = {}
    for field in ("first_name", "last_name", "address1", "city", "state", "postal_code", "country", "phone", "email"):
        v = request.form.get(f"contact_{field}", "").strip()
        if v:
            contact[field] = v
    if contact:
        secret["contact"] = contact

    cred = ProviderCredential(user_id=current_user.id, kind=kind, provider=provider, label=label or provider)
    cred.set_secret(secret)
    db.session.add(cred)
    db.session.commit()

    flash("Credencial salva.", "success")
    return redirect(url_for("credentials.credentials_page"))


@bp.route("/<int:cred_id>/testar", methods=["POST"])
@login_required
def test_credential(cred_id):
    cred = ProviderCredential.query.filter_by(id=cred_id, user_id=current_user.id).first_or_404()
    secret = cred.get_secret()
    try:
        if cred.kind == "vps":
            provider = get_vps_provider(cred.provider, secret)
        else:
            provider = get_registrar_provider(cred.provider, secret)
        ok, message = provider.test_connection()
    except Exception as exc:
        ok, message = False, str(exc)
    return jsonify({"ok": ok, "message": message})


@bp.route("/<int:cred_id>/excluir", methods=["POST"])
@login_required
def delete_credential(cred_id):
    cred = ProviderCredential.query.filter_by(id=cred_id, user_id=current_user.id).first_or_404()
    db.session.delete(cred)
    db.session.commit()
    flash("Credencial removida.", "success")
    return redirect(url_for("credentials.credentials_page"))
