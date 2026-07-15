import os
import re
import shutil
import zipfile

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user

from .. import db
from ..models import Funnel, User

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.before_request
def _guard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login_get"))
    if not current_user.is_admin:
        flash("Acesso restrito a administradores.", "error")
        return redirect(url_for("dashboard.dashboard"))


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "funil"


def _safe_extract(zf: zipfile.ZipFile, dest_dir: str):
    dest_norm = os.path.normpath(dest_dir)
    for member in zf.namelist():
        member_path = os.path.normpath(os.path.join(dest_dir, member))
        if member_path != dest_norm and not member_path.startswith(dest_norm + os.sep):
            raise ValueError(f"Entrada de zip inválida (path traversal): {member}")
    zf.extractall(dest_dir)


@bp.route("/funis")
def admin_funnels():
    funnels = Funnel.query.order_by(Funnel.created_at.desc()).all()
    return render_template("admin_funnels.html", title="Admin — Funis", funnels=funnels)


@bp.route("/funis/novo", methods=["POST"])
def create_funnel():
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    file = request.files.get("zipfile")

    if not name or not file or not file.filename.lower().endswith(".zip"):
        flash("Informe um nome e um arquivo .zip válido.", "error")
        return redirect(url_for("admin.admin_funnels"))

    slug = _slugify(name)
    base_slug = slug
    i = 1
    while Funnel.query.filter_by(slug=slug).first():
        i += 1
        slug = f"{base_slug}-{i}"

    dest_dir = os.path.join(current_app.config["FUNNELS_DIR"], slug)
    os.makedirs(dest_dir, exist_ok=True)

    try:
        with zipfile.ZipFile(file.stream) as zf:
            _safe_extract(zf, dest_dir)
    except Exception as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        flash(f"Erro ao extrair zip: {exc}", "error")
        return redirect(url_for("admin.admin_funnels"))

    has_php = False
    for root, dirs, files in os.walk(dest_dir):
        if any(f.lower().endswith(".php") for f in files):
            has_php = True
            break

    entry_file = "index.php" if has_php and os.path.exists(os.path.join(dest_dir, "index.php")) else "index.html"

    funnel = Funnel(
        name=name,
        slug=slug,
        description=description,
        storage_path=slug,
        entry_file=entry_file,
        has_php=has_php,
        uploaded_by=current_user.id,
        is_active=True,
    )
    db.session.add(funnel)
    db.session.commit()

    flash(f"Funil '{name}' cadastrado.", "success")
    return redirect(url_for("admin.admin_funnels"))


@bp.route("/funis/<int:funnel_id>/alternar", methods=["POST"])
def toggle_funnel(funnel_id):
    funnel = Funnel.query.get_or_404(funnel_id)
    funnel.is_active = not funnel.is_active
    db.session.commit()
    return redirect(url_for("admin.admin_funnels"))


@bp.route("/funis/<int:funnel_id>/excluir", methods=["POST"])
def delete_funnel(funnel_id):
    funnel = Funnel.query.get_or_404(funnel_id)
    dest_dir = os.path.join(current_app.config["FUNNELS_DIR"], funnel.storage_path)
    shutil.rmtree(dest_dir, ignore_errors=True)
    db.session.delete(funnel)
    db.session.commit()
    flash("Funil removido.", "success")
    return redirect(url_for("admin.admin_funnels"))


@bp.route("/usuarios")
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin_users.html", title="Admin — Usuários", users=users)


@bp.route("/usuarios/<int:user_id>/banir", methods=["POST"])
def toggle_ban(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("Você não pode banir a si mesmo.", "error")
        return redirect(url_for("admin.admin_users"))
    user.is_banned = not user.is_banned
    db.session.commit()
    return redirect(url_for("admin.admin_users"))
