"""Development entry point.

Creates the application via the factory and, when run directly, ensures the
database tables exist before starting the server. For production use a WSGI
server (e.g. ``gunicorn 'app:create_app()'``).
"""
import os

from app import create_app
from app.extensions import db

app = create_app(os.environ.get("FLASK_CONFIG", "development"))


@app.shell_context_processor
def shell_context():
    """Expose common objects in ``flask shell`` for convenience."""
    from app.models import Book, Fine, Loan, Member, User

    return {
        "db": db,
        "User": User,
        "Book": Book,
        "Member": Member,
        "Loan": Loan,
        "Fine": Fine,
    }


if __name__ == "__main__":
    # Create tables automatically for a frictionless first run. In a real
    # deployment you would use ``flask db upgrade`` (Flask-Migrate) instead.
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000, debug=True)
