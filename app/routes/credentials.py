import json
import re

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from .. import db
from ..models import ProviderCredential, Domain, Vps
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


_PHONE_RE = re.compile(r"^\+\d{1,3}\.\d{4,14}$")


def _normalize_phone(raw: str) -> str:
    """Reformat a registrant phone into registrar-required '+CC.NUMBER' shape.

    Registrars like Namecheap reject anything that isn't exactly '+<country
    code>.<number>'. Users tend to paste digits-only numbers, so assume the
    first 2 digits are the country code when no explicit '+'/'.' split is
    given. Leaves already-valid values untouched.
    """
    raw = raw.strip()
    if not raw or _PHONE_RE.match(raw):
        return raw
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 8:
        return raw
    return f"+{digits[:2]}.{digits[2:]}"


def _parse_credential_form():
    """Validate kind/provider and rebuild the secret dict from the submitted form.

    Returns (kind, provider, label, secret) on success, or (None, None, None, None)
    with a flash message already set on validation failure.
    """
    kind = request.form.get("kind", "").strip()
    provider = request.form.get("provider", "").strip()
    label = request.form.get("label", "").strip()

    if kind not in ("vps", "registrar"):
        flash("Tipo de credencial inválido.", "error")
        return None, None, None, None

    valid_providers = list_vps_providers() if kind == "vps" else list_registrar_providers()
    if provider not in valid_providers:
        flash("Provedor inválido.", "error")
        return None, None, None, None

    # Collect provider-specific secret fields submitted by the form (secret_<field>=value)
    secret = {}
    for k, v in request.form.items():
        if k.startswith("secret_") and v.strip():
            secret[k[len("secret_"):]] = v.strip()

    contact = {}
    for field in ("first_name", "last_name", "address1", "city", "state", "postal_code", "country", "phone", "email"):
        v = request.form.get(f"contact_{field}", "").strip()
        if v:
            contact[field] = _normalize_phone(v) if field == "phone" else v
    if contact:
        secret["contact"] = contact

    return kind, provider, label, secret


@bp.route("/nova", methods=["POST"])
@login_required
def create_credential():
    kind, provider, label, secret = _parse_credential_form()
    if kind is None:
        return redirect(url_for("credentials.credentials_page"))

    cred = ProviderCredential(user_id=current_user.id, kind=kind, provider=provider, label=label or provider)
    cred.set_secret(secret)
    db.session.add(cred)
    db.session.commit()

    flash("Credencial salva.", "success")
    return redirect(url_for("credentials.credentials_page"))


@bp.route("/<int:cred_id>/dados", methods=["GET"])
@login_required
def credential_data(cred_id):
    cred = ProviderCredential.query.filter_by(id=cred_id, user_id=current_user.id).first_or_404()
    secret = cred.get_secret()
    contact = secret.pop("contact", {})
    return jsonify({
        "id": cred.id,
        "kind": cred.kind,
        "provider": cred.provider,
        "label": cred.label,
        "secret": secret,
        "contact": contact,
    })


@bp.route("/<int:cred_id>/editar", methods=["POST"])
@login_required
def edit_credential(cred_id):
    cred = ProviderCredential.query.filter_by(id=cred_id, user_id=current_user.id).first_or_404()

    kind, provider, label, secret = _parse_credential_form()
    if kind is None:
        return redirect(url_for("credentials.credentials_page"))

    # Merge onto the existing secret (when kind/provider are unchanged) so a field left
    # blank on the edit form keeps its previous value instead of being silently erased.
    existing = cred.get_secret() if (kind == cred.kind and provider == cred.provider) else {}
    merged_contact = {**existing.pop("contact", {}), **secret.pop("contact", {})}
    merged_secret = {**existing, **secret}
    if merged_contact:
        merged_secret["contact"] = merged_contact

    cred.kind = kind
    cred.provider = provider
    cred.label = label or provider
    cred.set_secret(merged_secret)
    db.session.commit()

    flash("Credencial atualizada.", "success")
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

    linked_domains = Domain.query.filter_by(credential_id=cred.id).count()
    linked_vpses = Vps.query.filter_by(credential_id=cred.id).count()
    if linked_domains or linked_vpses:
        parts = []
        if linked_domains:
            parts.append(f"{linked_domains} domínio(s)")
        if linked_vpses:
            parts.append(f"{linked_vpses} VPS(s)")
        flash(
            "Essa credencial está vinculada a " + " e ".join(parts) + ". Remova-os antes de excluí-la.",
            "error",
        )
        return redirect(url_for("credentials.credentials_page"))

    db.session.delete(cred)
    db.session.commit()
    flash("Credencial removida.", "success")
    return redirect(url_for("credentials.credentials_page"))
