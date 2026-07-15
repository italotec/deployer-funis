from flask import Blueprint, render_template
from flask_login import login_required, current_user

from ..models import Funnel, Vps, Domain, Deployment

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
def dashboard():
    funnels = Funnel.query.filter_by(is_active=True).order_by(Funnel.name).all()
    vpses = Vps.query.filter_by(user_id=current_user.id).order_by(Vps.created_at.desc()).all()
    domains = Domain.query.filter_by(user_id=current_user.id).order_by(Domain.created_at.desc()).all()
    recent_deployments = (
        Deployment.query.filter_by(user_id=current_user.id)
        .order_by(Deployment.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "dashboard.html",
        title="Dashboard",
        funnels=funnels,
        vpses=vpses,
        domains=domains,
        recent_deployments=recent_deployments,
    )
