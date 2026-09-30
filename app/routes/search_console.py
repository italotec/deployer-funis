from urllib.parse import quote

from flask import Blueprint, render_template, request, jsonify, current_app, session, redirect, url_for, flash
from flask_login import login_required, current_user

from .. import db, jobs
from ..models import Domain
from ..services.google import accounts
from ..services.google.safe_browsing import check_domains

bp = Blueprint("search_console", __name__, url_prefix="/search-console")

_STATE_KEY = "gsc_oauth_state"


def _site_domain(site_url: str) -> str:
    """'sc-domain:x.com' / 'https://www.x.com/' -> 'x.com'."""
    host = site_url.removeprefix("sc-domain:")
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].lower()
    return host.removeprefix("www.")


def _redirect_uri() -> str:
    return current_app.config["GOOGLE_OAUTH_REDIRECT_URI"] or url_for("search_console.oauth_callback", _external=True)


def _norm(name: str) -> str:
    return name.lower().removeprefix("www.")


def _panel_domains() -> dict:
    """The current user's real (registered) panel domains, by normalized name."""
    return {
        _norm(d.name): d
        for d in Domain.query.filter_by(user_id=current_user.id)
        if d.status in ("registered", "dns_set")
    }


@bp.route("/")
@login_required
def search_console_page():
    error = ""
    sites = []
    connection = accounts.get_connection(current_user.id)
    panel = _panel_domains()
    try:
        client, account = accounts.client_for_user(current_app.config, current_user.id)
        entries = client.list_sites()

        # A connected Google account only exposes that user's own properties. The shared
        # service account sees everyone's, so regular users are limited to their own domains.
        mine = None if (account or current_user.is_admin) else set(panel)
        rows: dict[str, dict] = {}
        for e in entries:
            domain = _site_domain(e["siteUrl"])
            if mine is not None and domain not in mine:
                continue
            perm = e.get("permissionLevel", "")
            # Domain property and URL-prefix property of the same domain: keep the better one.
            if domain in rows and rows[domain]["permission"] == "siteOwner":
                continue
            rows[domain] = {
                "domain": domain, "in_gsc": True, "site_url": e["siteUrl"], "permission": perm,
                "review_url": "https://search.google.com/search-console/security-issues?resource_id="
                              + quote(e["siteUrl"], safe=""),
            }
        # Every panel domain shows up, even when Google's list doesn't have it yet.
        for name in panel:
            rows.setdefault(name, {"domain": name, "in_gsc": False, "site_url": "", "permission": "", "review_url": ""})

        for name, row in rows.items():
            d = panel.get(name)
            row["panel_id"] = d.id if d else None
            row["gsc_status"] = d.gsc_status if d else ""
            row["gsc_message"] = d.gsc_message if d else ""
            row["state"] = ("missing" if not row["in_gsc"]
                            else "unverified" if row["permission"] == "siteUnverifiedUser" else "ok")
        sites = sorted(rows.values(), key=lambda s: s["domain"])
    except Exception as exc:
        error = str(exc)

    return render_template(
        "search_console.html", title="Search Console", sites=sites, error=error,
        safe_browsing_enabled=bool(current_app.config["SAFE_BROWSING_API_KEY"]),
        oauth_configured=accounts.oauth_configured(current_app.config),
        connected_email=(connection.label if connection else ""),
    )


@bp.route("/oauth/start")
@login_required
def oauth_start():
    if not accounts.oauth_configured(current_app.config):
        flash("Login com Google não configurado (GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET).", "error")
        return redirect(url_for("search_console.search_console_page"))
    state = accounts.new_state()
    session[_STATE_KEY] = state
    return redirect(accounts.build_auth_url(current_app.config, _redirect_uri(), state))


@bp.route("/oauth/callback")
@login_required
def oauth_callback():
    back = redirect(url_for("search_console.search_console_page"))

    expected = session.pop(_STATE_KEY, None)
    if request.args.get("error"):
        flash(f"Login com Google cancelado: {request.args['error']}", "error")
        return back
    if not expected or request.args.get("state") != expected or not request.args.get("code"):
        flash("Resposta de login inválida ou expirada. Tente conectar de novo.", "error")
        return back

    first_connection = accounts.get_connection(current_user.id) is None
    try:
        email = accounts.complete_connection(current_app.config, current_user.id, request.args["code"], _redirect_uri())
    except Exception as exc:
        flash(f"Erro ao conectar a conta Google: {exc}", "error")
        return back

    if first_connection:
        # Everything verified so far was verified by the shared service account, not by
        # this user's own account — let them redo it so the domains become theirs.
        Domain.query.filter_by(user_id=current_user.id, gsc_status="verified").update(
            {"gsc_status": "", "gsc_message": ""}
        )
        db.session.commit()

    flash(f"Conta Google conectada: {email}. Novos domínios serão verificados por ela.", "success")
    return back


@bp.route("/oauth/disconnect", methods=["POST"])
@login_required
def oauth_disconnect():
    cred = accounts.get_connection(current_user.id)
    if cred:
        db.session.delete(cred)
        db.session.commit()
    flash("Conta Google desconectada. Voltando a usar a conta de serviço.", "success")
    return redirect(url_for("search_console.search_console_page"))


@bp.route("/bulk-add", methods=["POST"])
@login_required
def bulk_add():
    """Start the add-to-Search-Console job for the given panel domains."""
    wanted = {_norm(d) for d in (request.get_json(silent=True) or {}).get("domains", []) if isinstance(d, str)}
    ids = []
    for name, d in _panel_domains().items():
        if name in wanted and d.gsc_status != "running":
            d.gsc_status = "running"
            d.gsc_message = "Na fila..."
            ids.append(d.id)
    db.session.commit()
    for domain_id in ids:
        jobs.start_gsc_add_job(domain_id)
    return jsonify({"ok": True, "started": len(ids)})


@bp.route("/remove", methods=["POST"])
@login_required
def remove():
    """Remove properties from the connected account's Search Console."""
    wanted = {_norm(d) for d in (request.get_json(silent=True) or {}).get("domains", []) if isinstance(d, str)}
    try:
        client, _account = accounts.client_for_user(current_app.config, current_user.id)
        entries = client.list_sites()
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})

    panel = _panel_domains()
    is_service_account = not accounts.get_connection(current_user.id)
    results = {}
    for e in entries:
        domain = _site_domain(e["siteUrl"])
        if domain not in wanted:
            continue
        # The shared service account sees everyone's properties; never let a user remove
        # one that isn't in their own panel.
        if is_service_account and not current_user.is_admin and domain not in panel:
            continue
        try:
            client.delete_site(e["siteUrl"])
            results[domain] = "ok"
            if domain in panel:
                panel[domain].gsc_status = ""
                panel[domain].gsc_message = ""
        except Exception as exc:
            results[domain] = str(exc)
    db.session.commit()
    return jsonify({"ok": True, "results": results})


@bp.route("/status")
@login_required
def status():
    return jsonify({
        name: {"status": d.gsc_status, "message": d.gsc_message}
        for name, d in _panel_domains().items() if d.gsc_status
    })


@bp.route("/safe-browsing", methods=["POST"])
@login_required
def safe_browsing_check():
    domains = (request.get_json(silent=True) or {}).get("domains", [])
    domains = [d.strip().lower() for d in domains if isinstance(d, str) and d.strip()]

    if not current_user.is_admin and not accounts.get_connection(current_user.id):
        allowed = {d.name.lower().removeprefix("www.") for d in Domain.query.filter_by(user_id=current_user.id)}
        domains = [d for d in domains if d in allowed]

    try:
        flagged = check_domains(current_app.config["SAFE_BROWSING_API_KEY"], domains)
        return jsonify({"ok": True, "flagged": flagged})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})
