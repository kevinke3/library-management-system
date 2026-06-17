"""Application configuration.

Configuration values are read from environment variables where available so the
same code base can run in development, testing and production without changes.
Sensible defaults are provided for local development.
"""
import os
from datetime import timedelta

# Absolute path to the ``backend`` directory so paths work regardless of the
# directory the app is launched from.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration shared by every environment."""

    # Secret key used to sign session cookies. Override in production.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # SQLite database stored inside the Flask ``instance`` folder.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(BASE_DIR, "instance", "library.db"),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session / cookie behaviour. ``SameSite=Lax`` lets the bundled frontend
    # (served from the same origin) authenticate without extra configuration.
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Domain rules for the library.
    LOAN_PERIOD_DAYS = int(os.environ.get("LOAN_PERIOD_DAYS", 14))
    FINE_PER_DAY = float(os.environ.get("FINE_PER_DAY", 10.0))
    MAX_ACTIVE_LOANS = int(os.environ.get("MAX_ACTIVE_LOANS", 5))

    # Origins allowed to call the API when the frontend is hosted separately.
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")


class DevelopmentConfig(Config):
    DEBUG = True


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


class ProductionConfig(Config):
    DEBUG = False


# Lookup table used by the application factory.
config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
