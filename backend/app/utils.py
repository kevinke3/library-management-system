"""Shared helpers: JSON responses, validation and access control decorators."""
from functools import wraps

from flask import jsonify
from flask_login import current_user


class ApiError(Exception):
    """Raised by views to return a structured JSON error response.

    The application factory registers an error handler that converts these into
    ``{"error": message, "details": {...}}`` payloads with the right HTTP code.
    """

    def __init__(self, message, status_code=400, details=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def ok(data=None, status_code=200, **extra):
    """Return a successful JSON response."""
    payload = {"data": data}
    payload.update(extra)
    return jsonify(payload), status_code


def error(message, status_code=400, details=None):
    """Return an error JSON response."""
    return jsonify({"error": message, "details": details or {}}), status_code


def require_fields(data, fields):
    """Validate that ``data`` is a dict containing every key in ``fields``.

    Raises :class:`ApiError` (400) listing the missing/empty fields.
    """
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.", 400)
    missing = [
        f
        for f in fields
        if data.get(f) is None or (isinstance(data.get(f), str) and not data[f].strip())
    ]
    if missing:
        raise ApiError(
            "Missing required fields.",
            400,
            {"missing": missing},
        )


def role_required(*roles):
    """Decorator restricting a view to authenticated users with ``roles``."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return error("Authentication required.", 401)
            if roles and current_user.role not in roles:
                return error("You do not have permission to perform this action.", 403)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def staff_required(view):
    """Shortcut decorator allowing only admins and librarians."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return error("Authentication required.", 401)
        if not current_user.is_staff:
            return error("Staff access required.", 403)
        return view(*args, **kwargs)

    return wrapper
