"""Application factory for the Library Management System.

Creating the app inside a factory keeps configuration flexible (development,
testing, production) and avoids import-time side effects. The factory wires up
extensions, registers blueprints, serves the bundled frontend and installs JSON
error handlers.
"""
import os

from flask import Flask, jsonify, send_from_directory

from config import config_by_name

from .extensions import cors, db, login_manager, migrate
from .utils import ApiError

# The standalone frontend lives next to the backend package.
FRONTEND_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)


def create_app(config_name=None):
    """Build and return a configured :class:`flask.Flask` application."""
    config_name = config_name or os.environ.get("FLASK_CONFIG", "default")

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_by_name.get(config_name, config_by_name["default"]))

    # Ensure the instance folder (where the SQLite db lives) exists.
    os.makedirs(app.instance_path, exist_ok=True)
    _ensure_sqlite_dir(app)

    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_frontend(app)

    return app


def _ensure_sqlite_dir(app):
    """Create the directory for a file based SQLite database if needed."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
    prefix = "sqlite:///"
    if uri.startswith(prefix):
        db_path = uri[len(prefix):]
        if db_path and db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path), exist_ok=True)


def _init_extensions(app):
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}},
        supports_credentials=True,
    )

    # Flask-Login configuration. The API never redirects to an HTML login page;
    # instead it returns a 401 so the frontend can react.
    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.unauthorized_handler
    def unauthorized():
        return jsonify({"error": "Authentication required.", "details": {}}), 401


def _register_blueprints(app):
    from .auth.routes import auth_bp
    from .books.routes import books_bp
    from .dashboard.routes import dashboard_bp
    from .fines.routes import fines_bp
    from .loans.routes import loans_bp
    from .members.routes import members_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(books_bp, url_prefix="/api/books")
    app.register_blueprint(members_bp, url_prefix="/api/members")
    app.register_blueprint(loans_bp, url_prefix="/api/loans")
    app.register_blueprint(fines_bp, url_prefix="/api/fines")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")

    @app.route("/api/health")
    def health():
        return jsonify({"data": {"status": "ok"}})


def _register_error_handlers(app):
    """Install handlers that always return JSON for API style errors."""

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return (
            jsonify({"error": err.message, "details": err.details}),
            err.status_code,
        )

    @app.errorhandler(400)
    def bad_request(err):
        return jsonify({"error": "Bad request.", "details": {}}), 400

    @app.errorhandler(404)
    def not_found(err):
        # HTML (frontend) requests fall through to the SPA handler; only API
        # paths reach here as JSON 404s.
        return jsonify({"error": "Resource not found.", "details": {}}), 404

    @app.errorhandler(500)
    def server_error(err):
        db.session.rollback()
        return jsonify({"error": "Internal server error.", "details": {}}), 500


def _register_frontend(app):
    """Serve the bundled static frontend from the same origin as the API.

    Serving the frontend here keeps session cookies same-origin (so Flask-Login
    just works). The frontend can still be hosted separately if desired.
    """

    @app.route("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.route("/<path:filename>")
    def static_files(filename):
        target = os.path.join(FRONTEND_DIR, filename)
        if os.path.isfile(target):
            return send_from_directory(FRONTEND_DIR, filename)
        # Unknown non-API paths fall back to the single page app entry point.
        return send_from_directory(FRONTEND_DIR, "index.html")
