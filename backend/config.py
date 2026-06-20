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

    # ------------------------------------------------------------------
    # Safaricom Daraja (M-Pesa) settings.
    #
    # ``MPESA_ENV`` switches the base URL between the Daraja sandbox and
    # production. Credentials come from the developer portal; the shortcode and
    # passkey default to Safaricom's public sandbox test values so the STK Push
    # flow can be exercised end to end without real credentials.
    # ------------------------------------------------------------------
    MPESA_ENV = os.environ.get("MPESA_ENV", "sandbox")
    MPESA_CONSUMER_KEY = os.environ.get("DARAJA_CONSUMER_KEY", "")
    MPESA_CONSUMER_SECRET = os.environ.get("DARAJA_CONSUMER_SECRET", "")
    MPESA_SHORTCODE = os.environ.get("MPESA_SHORTCODE", "174379")
    MPESA_PASSKEY = os.environ.get(
        "MPESA_PASSKEY",
        "bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919",
    )
    # Transaction type: CustomerPayBillOnline (paybill) or CustomerBuyGoodsOnline (till).
    MPESA_TRANSACTION_TYPE = os.environ.get(
        "MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"
    )
    # Public base URL Daraja can POST the result to (e.g. an ngrok/cloudflared
    # tunnel during development). The callback path is appended automatically.
    MPESA_CALLBACK_BASE_URL = os.environ.get("MPESA_CALLBACK_BASE_URL", "")


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
