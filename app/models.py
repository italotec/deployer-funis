import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from . import db, login_manager
from .crypto import encrypt_str, decrypt_str

_SP = ZoneInfo("America/Sao_Paulo")


def _now_sp():
    return datetime.now(_SP)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    is_banned = db.Column(db.Boolean, default=False, nullable=False)

    api_key = db.Column(db.String(64), unique=True, nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)

    credentials = db.relationship("ProviderCredential", backref="user", lazy=True, cascade="all, delete-orphan")
    vpses = db.relationship("Vps", backref="user", lazy=True, cascade="all, delete-orphan")
    domains = db.relationship("Domain", backref="user", lazy=True, cascade="all, delete-orphan")

    def generate_api_key(self):
        self.api_key = secrets.token_urlsafe(32)

    def set_password(self, pw: str):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class ProviderCredential(db.Model):
    """Per-user API credentials for a VPS or registrar provider, encrypted at rest."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    kind = db.Column(db.String(16), nullable=False)       # "vps" | "registrar"
    provider = db.Column(db.String(32), nullable=False)    # "contabo" | "namecheap" | "njalla" | "mock"
    label = db.Column(db.String(128), default="", nullable=False)

    secret_enc = db.Column(db.Text, nullable=False)  # Fernet-encrypted JSON blob

    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)

    def set_secret(self, data: dict):
        self.secret_enc = encrypt_str(json.dumps(data))

    def get_secret(self) -> dict:
        try:
            return json.loads(decrypt_str(self.secret_enc))
        except Exception:
            return {}


class Vps(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    credential_id = db.Column(db.Integer, db.ForeignKey("provider_credential.id"), nullable=True)

    provider = db.Column(db.String(32), nullable=False)
    provider_instance_id = db.Column(db.String(128), default="", nullable=False)

    label = db.Column(db.String(128), default="", nullable=False)
    ip_address = db.Column(db.String(64), default="", nullable=False)
    region = db.Column(db.String(64), default="", nullable=False)
    plan = db.Column(db.String(64), default="", nullable=False)

    ssh_user = db.Column(db.String(32), default="root", nullable=False)
    ssh_port = db.Column(db.Integer, default=22, nullable=False)
    ssh_key_enc = db.Column(db.Text, nullable=True)  # encrypted private key (PEM)
    ssh_password_enc = db.Column(db.Text, nullable=True)  # encrypted password (manual VPSes)

    status = db.Column(db.String(32), default="provisioning", nullable=False)
    # provisioning | ready | error

    php_installed = db.Column(db.Boolean, default=False, nullable=False)
    bootstrapped = db.Column(db.Boolean, default=False, nullable=False)

    last_message = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)

    deployments = db.relationship("Deployment", backref="vps", lazy=True)

    def set_ssh_key(self, pem: str):
        self.ssh_key_enc = encrypt_str(pem)

    def get_ssh_key(self) -> str:
        if not self.ssh_key_enc:
            return ""
        try:
            return decrypt_str(self.ssh_key_enc)
        except Exception:
            return ""

    def set_ssh_password(self, password: str):
        self.ssh_password_enc = encrypt_str(password)

    def get_ssh_password(self) -> str:
        if not self.ssh_password_enc:
            return ""
        try:
            return decrypt_str(self.ssh_password_enc)
        except Exception:
            return ""

    @property
    def deployment_count(self):
        return sum(1 for d in self.deployments if d.status == "live")


class Domain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    registrar = db.Column(db.String(32), nullable=False)
    # Which registrar account this domain was registered/managed under. Nullable for
    # "manual" (external) domains and legacy rows; when an account owns the domain the
    # deploy pipeline must authenticate as this exact credential, not just any
    # credential that happens to share the provider name.
    credential_id = db.Column(db.Integer, db.ForeignKey("provider_credential.id"), nullable=True)
    credential = db.relationship("ProviderCredential")

    name = db.Column(db.String(255), nullable=False)
    registrar_order_id = db.Column(db.String(128), default="", nullable=False)

    status = db.Column(db.String(32), default="registering", nullable=False)
    # registering | registered | dns_set | error

    last_message = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)


class Funnel(db.Model):
    """Admin-managed funnel catalog entry."""
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    description = db.Column(db.Text, default="", nullable=False)

    storage_path = db.Column(db.String(255), nullable=False)  # relative to instance/funnels/
    entry_file = db.Column(db.String(64), default="index.html", nullable=False)
    has_php = db.Column(db.Boolean, default=False, nullable=False)

    stack = db.Column(db.String(16), default="static", nullable=False)  # static | php | node
    app_root = db.Column(db.String(255), default="", nullable=False)  # dir holding package.json, relative to storage_path

    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)


class DeployBatch(db.Model):
    """Groups a single 'deploy funnel X across N domains' request."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnel.id"), nullable=False)
    vps_id = db.Column(db.Integer, db.ForeignKey("vps.id"), nullable=False)

    quantity = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(32), default="queued", nullable=False)
    # queued | running | done | done_with_errors

    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)

    funnel = db.relationship("Funnel")
    deployments = db.relationship("Deployment", backref="batch", lazy=True, cascade="all, delete-orphan")


class Deployment(db.Model):
    """A single funnel live on a single domain on a single VPS.
    Counted (status == 'live') as the per-VPS deploy count shown on the dashboard."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("deploy_batch.id"), nullable=False, index=True)
    funnel_id = db.Column(db.Integer, db.ForeignKey("funnel.id"), nullable=False)
    domain_id = db.Column(db.Integer, db.ForeignKey("domain.id"), nullable=False)
    vps_id = db.Column(db.Integer, db.ForeignKey("vps.id"), nullable=False, index=True)

    status = db.Column(db.String(32), default="queued", nullable=False)
    # queued | registering_domain | dns | uploading | installing | starting | nginx | ssl | live | error

    live_url = db.Column(db.String(255), default="", nullable=False)
    nginx_conf_path = db.Column(db.String(255), default="", nullable=False)
    app_port = db.Column(db.Integer, default=0, nullable=False)  # local port of the Node process; 0 = not Node

    last_message = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime, default=_now_sp, nullable=False)

    funnel = db.relationship("Funnel")
    domain = db.relationship("Domain")


class AppSetting(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(255), default="", nullable=False)
