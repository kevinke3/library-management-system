"""Library member (patron) endpoints with search and CRUD."""
from datetime import date

from flask import Blueprint, request
from flask_login import login_required

from ..extensions import db
from ..models import Member
from ..utils import ApiError, ok, require_fields, staff_required

members_bp = Blueprint("members", __name__)


def _generate_membership_id():
    """Produce a sequential, human readable membership id like ``LIB-000123``."""
    last = Member.query.order_by(Member.id.desc()).first()
    next_num = (last.id + 1) if last else 1
    return f"LIB-{next_num:06d}"


@members_bp.get("")
@login_required
def list_members():
    """List members with optional ``q`` search and ``status`` filter."""
    query = Member.query

    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Member.name.ilike(like),
                Member.email.ilike(like),
                Member.membership_id.ilike(like),
                Member.phone.ilike(like),
            )
        )

    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(Member.status == status)

    members = query.order_by(Member.name.asc()).all()
    return ok([m.to_dict() for m in members])


@members_bp.get("/<int:member_id>")
@login_required
def get_member(member_id):
    member = db.session.get(Member, member_id)
    if member is None:
        raise ApiError("Member not found.", 404)
    return ok(member.to_dict())


@members_bp.post("")
@staff_required
def create_member():
    """Register a new patron (staff only)."""
    data = request.get_json(silent=True) or {}
    require_fields(data, ["name", "email"])

    email = data["email"].strip().lower()
    if Member.query.filter_by(email=email).first():
        raise ApiError("A member with that email already exists.", 409)

    member = Member(
        membership_id=_generate_membership_id(),
        name=data["name"].strip(),
        email=email,
        phone=(data.get("phone") or "").strip() or None,
        address=(data.get("address") or "").strip() or None,
        membership_type=(data.get("membership_type") or "standard").strip(),
        status=(data.get("status") or "active").strip(),
        join_date=date.today(),
    )
    db.session.add(member)
    db.session.commit()
    return ok(member.to_dict(), 201)


@members_bp.put("/<int:member_id>")
@staff_required
def update_member(member_id):
    member = db.session.get(Member, member_id)
    if member is None:
        raise ApiError("Member not found.", 404)

    data = request.get_json(silent=True) or {}

    if "email" in data:
        new_email = data["email"].strip().lower()
        existing = Member.query.filter_by(email=new_email).first()
        if existing and existing.id != member.id:
            raise ApiError("A member with that email already exists.", 409)
        member.email = new_email

    for field in ("name", "phone", "address", "membership_type", "status"):
        if field in data:
            value = data[field]
            member.__setattr__(field, value.strip() if isinstance(value, str) else value)

    db.session.commit()
    return ok(member.to_dict())


@members_bp.delete("/<int:member_id>")
@staff_required
def delete_member(member_id):
    """Delete a member. Blocked while they have books on loan."""
    member = db.session.get(Member, member_id)
    if member is None:
        raise ApiError("Member not found.", 404)
    if member.loans.filter_by(status="borrowed").count() > 0:
        raise ApiError("Cannot delete a member with active loans.", 409)

    db.session.delete(member)
    db.session.commit()
    return ok({"message": "Member deleted."})
