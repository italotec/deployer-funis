from functools import wraps

from flask import Blueprint, jsonify, request

from ..models import User, Vps, Domain, Deployment

bp = Blueprint("api", __name__, url_prefix="/api")


def require_api_key(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        key = request.headers.get("X-Api-Key") or request.args.get("api_key")
        user = User.query.filter_by(api_key=key).first() if key else None
        if not user:
            return jsonify({"error": "invalid api key"}), 401
        request.api_user = user
        return f(*args, **kwargs)
    return wrapper


@bp.route("/status")
@require_api_key
def status():
    user = request.api_user
    return jsonify({
        "vps_count": Vps.query.filter_by(user_id=user.id).count(),
        "domain_count": Domain.query.filter_by(user_id=user.id).count(),
        "deployments_live": Deployment.query.filter_by(user_id=user.id, status="live").count(),
    })


@bp.route("/vps")
@require_api_key
def list_vps():
    user = request.api_user
    vpses = Vps.query.filter_by(user_id=user.id).all()
    return jsonify([
        {
            "id": v.id,
            "label": v.label,
            "provider": v.provider,
            "ip_address": v.ip_address,
            "status": v.status,
            "deployment_count": v.deployment_count,
        }
        for v in vpses
    ])
