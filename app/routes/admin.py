import json
import os
import re
import shutil
import zipfile

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import current_user

from .. import db
from ..models import Funnel, User

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Checked in this order once scripts.start / package.json "main" don't resolve to an
# existing file — covers the layouts real Express boilerplates actually ship.
_NODE_ENTRY_CANDIDATES = ("server.js", "app.js", "index.js", "src/server.js", "src/index.js")


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


def _find_package_json_dir(dest_dir: str) -> str | None:
    """Directory (relative to dest_dir) holding package.json, or None. Zips often wrap
    their contents in a single top-level folder, so root and one level down are checked."""
    if os.path.exists(os.path.join(dest_dir, "package.json")):
        return ""
    for entry in os.listdir(dest_dir):
        sub = os.path.join(dest_dir, entry)
        if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "package.json")):
            return entry
    return None


def _resolve_node_entry(app_dir: str, pkg: dict) -> str:
    """Best-effort Node entrypoint, relative to app_dir. Empty string means the deploy
    should fall back to `npm start` (a scripts.start was found but not further resolvable)."""
    start_script = str((pkg.get("scripts") or {}).get("start", "")).strip()

    m = re.match(r"^node\s+(\S+)$", start_script)
    if m and os.path.exists(os.path.join(app_dir, m.group(1))):
        return m.group(1)

    main = str(pkg.get("main", "")).strip()
    if main and os.path.exists(os.path.join(app_dir, main)):
        return main

    for candidate in _NODE_ENTRY_CANDIDATES:
        if os.path.exists(os.path.join(app_dir, candidate)):
            return candidate

    return ""


def _detect_stack(dest_dir: str) -> tuple[str, str, str]:
    """Returns (stack, app_root, entry_file) for a freshly extracted funnel.

    app_root is the directory (relative to dest_dir) holding package.json, "" for
    static/php funnels. Raises ValueError (shown to the admin) when a Node funnel has
    no discoverable way to start — better to reject at upload than fail deep in a deploy.
    """
    node_dir = _find_package_json_dir(dest_dir)
    if node_dir is not None:
        app_dir = os.path.join(dest_dir, node_dir)
        # Never uploaded: node_modules built on the admin's machine targets the wrong
        # OS/ABI for the VPS (better-sqlite3 is a native module) and would also mean
        # tens of thousands of individual SFTP puts in upload_dir. npm ci runs on the
        # server instead (see provisioner.ensure_node / deployer.install_node_deps).
        shutil.rmtree(os.path.join(app_dir, "node_modules"), ignore_errors=True)

        try:
            with open(os.path.join(app_dir, "package.json"), "r", encoding="utf-8") as f:
                pkg = json.load(f)
        except Exception:
            pkg = {}

        entry_file = _resolve_node_entry(app_dir, pkg)
        has_start_script = bool(str((pkg.get("scripts") or {}).get("start", "")).strip())
        if not entry_file and not has_start_script:
            raise ValueError(
                "package.json não define \"scripts.start\" nem um arquivo de entrada "
                "reconhecível (server.js, app.js, index.js) — não é possível iniciar o funil Node."
            )
        return "node", node_dir, entry_file

    has_php = False
    for root, dirs, files in os.walk(dest_dir):
        if any(f.lower().endswith(".php") for f in files):
            has_php = True
            break

    if has_php:
        entry_file = "index.php" if os.path.exists(os.path.join(dest_dir, "index.php")) else "index.html"
        return "php", "", entry_file

    return "static", "", "index.html"


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

    try:
        stack, app_root, entry_file = _detect_stack(dest_dir)
    except ValueError as exc:
        shutil.rmtree(dest_dir, ignore_errors=True)
        flash(str(exc), "error")
        return redirect(url_for("admin.admin_funnels"))
    except Exception as exc:
        # Detection walks the extracted tree (package.json parsing, node_modules
        # removal) — an unexpected OS/encoding error here shouldn't surface as a raw
        # 500; report it the same way a bad zip is reported above.
        current_app.logger.exception("Falha ao detectar stack do funil em %s", dest_dir)
        shutil.rmtree(dest_dir, ignore_errors=True)
        flash(f"Erro ao analisar o conteúdo do zip: {exc}", "error")
        return redirect(url_for("admin.admin_funnels"))

    funnel = Funnel(
        name=name,
        slug=slug,
        description=description,
        storage_path=slug,
        entry_file=entry_file,
        has_php=(stack == "php"),
        stack=stack,
        app_root=app_root,
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
