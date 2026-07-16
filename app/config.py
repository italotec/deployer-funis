import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 20,
        "max_overflow": 40,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_pre_ping": True,
        "connect_args": {"timeout": 30},
    }

    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False

    # Fernet key used to encrypt provider credentials and SSH keys at rest.
    FERNET_KEY = os.getenv("FERNET_KEY", "")

    # Let's Encrypt registration email (certbot --non-interactive -m <email>)
    LE_EMAIL = os.getenv("LE_EMAIL", "")

    FUNNELS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "funnels")
    DEPLOY_LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance", "deploy_logs")

    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200MB max funnel zip upload
