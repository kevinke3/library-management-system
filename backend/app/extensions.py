"""Flask extension instances.

The extensions are created here without an application bound to them so they can
be imported throughout the project without causing circular imports. They are
initialised against the real app inside the application factory
(:func:`app.create_app`).
"""
from flask_cors import CORS
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# Database ORM.
db = SQLAlchemy()

# Database migrations (Alembic under the hood).
migrate = Migrate()

# Session based authentication.
login_manager = LoginManager()

# Cross-origin resource sharing for the standalone frontend.
cors = CORS()
