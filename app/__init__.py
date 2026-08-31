from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_sock import Sock

from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login_get"
sock = Sock()

_NON_TERMINAL_DEPLOYMENT_STATUSES = [
    "queued", "registering_domain", "dns", "uploading", "installing", "starting", "nginx", "ssl",
]
_NON_TERMINAL_BATCH_STATUSES = ["queued", "running"]


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    sock.init_app(app)

    from .routes.auth import bp as auth_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.credentials import bp as credentials_bp
    from .routes.vps import bp as vps_bp
    from .routes.domains import bp as domains_bp
    from .routes.funnels import bp as funnels_bp
    from .routes.deployments import bp as deployments_bp, handle_deployment_ws
    from .routes.admin import bp as admin_bp
    from .routes.api import bp as api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(vps_bp)
    app.register_blueprint(domains_bp)
    app.register_blueprint(funnels_bp)
    app.register_blueprint(deployments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    @sock.route("/deploys/ws")
    def deployment_ws_route(ws):
        handle_deployment_ws(ws)

    import os
    os.makedirs(app.config["FUNNELS_DIR"], exist_ok=True)
    os.makedirs(app.config["DEPLOY_LOGS_DIR"], exist_ok=True)

    with app.app_context():
        from . import models  # noqa
        db.create_all()

        db.session.execute(db.text("PRAGMA journal_mode=WAL"))
        db.session.commit()

        # db.create_all() only creates missing tables, not missing columns on existing
        # tables — this project has no Alembic, so new Vps columns need a manual guard.
        existing_vps_columns = {row[1] for row in db.session.execute(db.text("PRAGMA table_info(vps)"))}
        if "ssh_port" not in existing_vps_columns:
            db.session.execute(db.text("ALTER TABLE vps ADD COLUMN ssh_port INTEGER NOT NULL DEFAULT 22"))
        if "ssh_password_enc" not in existing_vps_columns:
            db.session.execute(db.text("ALTER TABLE vps ADD COLUMN ssh_password_enc TEXT"))
        db.session.commit()

        existing_funnel_columns = {row[1] for row in db.session.execute(db.text("PRAGMA table_info(funnel)"))}
        if "stack" not in existing_funnel_columns:
            db.session.execute(db.text("ALTER TABLE funnel ADD COLUMN stack VARCHAR(16) NOT NULL DEFAULT 'static'"))
            db.session.execute(db.text("UPDATE funnel SET stack='php' WHERE has_php=1"))
        if "app_root" not in existing_funnel_columns:
            db.session.execute(db.text("ALTER TABLE funnel ADD COLUMN app_root VARCHAR(255) NOT NULL DEFAULT ''"))
        db.session.commit()

        existing_deployment_columns = {row[1] for row in db.session.execute(db.text("PRAGMA table_info(deployment)"))}
        if "app_port" not in existing_deployment_columns:
            db.session.execute(db.text("ALTER TABLE deployment ADD COLUMN app_port INTEGER NOT NULL DEFAULT 0"))
        db.session.commit()

        existing_domain_columns = {row[1] for row in db.session.execute(db.text("PRAGMA table_info(domain)"))}
        if "credential_id" not in existing_domain_columns:
            db.session.execute(db.text("ALTER TABLE domain ADD COLUMN credential_id INTEGER REFERENCES provider_credential(id)"))
            # Backfill existing rows with the credential the deploy pipeline used to
            # resolve implicitly (first registrar credential matching the provider),
            # so behaviour is unchanged for domains registered before this column.
            db.session.execute(db.text("""
                UPDATE domain
                SET credential_id = (
                    SELECT pc.id FROM provider_credential pc
                    WHERE pc.user_id = domain.user_id
                      AND pc.kind = 'registrar'
                      AND pc.provider = domain.registrar
                    ORDER BY pc.id LIMIT 1
                )
                WHERE credential_id IS NULL AND registrar != 'manual'
            """))
            db.session.commit()

        # Recover state left behind by a crash/restart — in-process threads die with
        # the process, so anything mid-flight is stuck forever unless marked as failed here.
        from .models import Vps, Deployment, DeployBatch

        stuck_vps = Vps.query.filter(Vps.status == "provisioning").all()
        for v in stuck_vps:
            v.status = "error"
            v.last_message = "Interrompido: servidor reiniciou durante o provisionamento."

        stuck_deployments = Deployment.query.filter(Deployment.status.in_(_NON_TERMINAL_DEPLOYMENT_STATUSES)).all()
        for d in stuck_deployments:
            d.status = "error"
            d.last_message = "Interrompido: servidor reiniciou durante o deploy."

        stuck_batches = DeployBatch.query.filter(DeployBatch.status.in_(_NON_TERMINAL_BATCH_STATUSES)).all()
        for b in stuck_batches:
            b.status = "done_with_errors"

        if stuck_vps or stuck_deployments or stuck_batches:
            db.session.commit()

        # Seed admin df/df
        from .models import User
        admin = User.query.filter_by(username="df").first()
        if not admin:
            admin = User(username="df", is_admin=True, is_banned=False)
            admin.set_password("df")
            admin.generate_api_key()
            db.session.add(admin)
            db.session.commit()

        # Backfill api_key for any user that doesn't have one yet
        users_without_key = User.query.filter((User.api_key.is_(None)) | (User.api_key == "")).all()
        for u in users_without_key:
            u.generate_api_key()
        if users_without_key:
            db.session.commit()

    return app
