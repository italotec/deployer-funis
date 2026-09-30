from urllib.parse import quote

from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user

from ..models import Domain
from ..services.google.search_console import SearchConsoleClient
from ..services.google.safe_browsing import check_domains

bp = Blueprint("search_console", __name__, url_prefix="/search-console")


def _site_domain(site_url: str) -> str:
    """'sc-domain:x.com' / 'https://www.x.com/' -> 'x.com'."""
    host = site_url.removeprefix("sc-domain:")
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0].lower()
    return host.removeprefix("www.")


@bp.route("/")
@login_required
def search_console_page():
    error = ""
    sites = []
    try:
        client = SearchConsoleClient(
            current_app.config["GOOGLE_SERVICE_ACCOUNT_FILE"], current_app.config["GSC_OWNER_EMAIL"]
        )
        entries = client.list_sites()

        # The service account sees every property; regular users only see their own domains.
        mine = None if current_user.is_admin else {
            d.name.lower().removeprefix("www.") for d in Domain.query.filter_by(user_id=current_user.id)
        }
        for e in entries:
            domain = _site_domain(e["siteUrl"])
            if mine is not None and domain not in mine:
                continue
            sites.append({
                "site_url": e["siteUrl"],
                "domain": domain,
                "permission": e.get("permissionLevel", ""),
                "review_url": "https://search.google.com/search-console/security-issues?resource_id="
                              + quote(e["siteUrl"], safe=""),
            })
        sites.sort(key=lambda s: s["domain"])
    except Exception as exc:
        error = str(exc)

    return render_template(
        "search_console.html", title="Search Console", sites=sites, error=error,
        safe_browsing_enabled=bool(current_app.config["SAFE_BROWSING_API_KEY"]),
    )


@bp.route("/safe-browsing", methods=["POST"])
@login_required
def safe_browsing_check():
    domains = (request.get_json(silent=True) or {}).get("domains", [])
    domains = [d.strip().lower() for d in domains if isinstance(d, str) and d.strip()]

    if not current_user.is_admin:
        allowed = {d.name.lower().removeprefix("www.") for d in Domain.query.filter_by(user_id=current_user.id)}
        domains = [d for d in domains if d in allowed]

    try:
        flagged = check_domains(current_app.config["SAFE_BROWSING_API_KEY"], domains)
        return jsonify({"ok": True, "flagged": flagged})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)})
