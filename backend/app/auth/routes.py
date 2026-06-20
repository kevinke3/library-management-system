"""Authentication endpoints: register, login, logout and the current user."""
from flask import Blueprint, request
from flask_login import current_user, login_required, login_user, logout_user

from ..extensions import db
from ..models import VALID_ROLES, ROLE_MEMBER, User
from ..utils import ApiError, ok, require_fields, role_required

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/register")
def register():
    """Create a new account.

    The very first account created becomes an administrator so the system is
    usable out of the box. After that, only administrators may create staff
    accounts; anonymous self-registration is limited to the ``member`` role.
    """
    data = request.get_json(silent=True) or {}
    require_fields(data, ["name", "email", "password"])

    email = data["email"].strip().lower()
    if User.query.filter_by(email=email).first():
        raise ApiError("An account with that email already exists.", 409)

    requested_role = (data.get("role") or ROLE_MEMBER).lower()
    if requested_role not in VALID_ROLES:
        raise ApiError("Invalid role.", 400, {"valid_roles": list(VALID_ROLES)})

    is_first_user = User.query.count() == 0
    if is_first_user:
        role = "admin"
    elif requested_role != ROLE_MEMBER:
        # Elevated roles can only be granted by an authenticated admin.
        if not (current_user.is_authenticated and current_user.is_admin):
            raise ApiError("Only administrators can create staff accounts.", 403)
        role = requested_role
    else:
        role = ROLE_MEMBER

    user = User(name=data["name"].strip(), email=email, role=role)
    user.set_password(data["password"])
    db.session.add(user)
    db.session.commit()

    return ok(user.to_dict(), 201)


@auth_bp.post("/login")
def login():
    """Authenticate a user and start a session."""
    data = request.get_json(silent=True) or {}
    require_fields(data, ["email", "password"])

    user = User.query.filter_by(email=data["email"].strip().lower()).first()
    if user is None or not user.check_password(data["password"]):
        raise ApiError("Invalid email or password.", 401)
    if not user.is_active:
        raise ApiError("This account has been deactivated.", 403)

    login_user(user, remember=bool(data.get("remember")))
    return ok(user.to_dict())


@auth_bp.post("/logout")
@login_required
def logout():
    """End the current session."""
    logout_user()
    return ok({"message": "Logged out."})


@auth_bp.get("/me")
def me():
    """Return the currently authenticated user (or ``null``)."""
    if not current_user.is_authenticated:
        return ok(None)
    return ok(current_user.to_dict())


@auth_bp.get("/users")
@role_required("admin")
def list_users():
    """Admin only: list every account."""
    users = User.query.order_by(User.created_at.desc()).all()
    return ok([u.to_dict() for u in users])
