"""Fine management endpoints: list, pay and waive penalties."""
from datetime import datetime

from flask import Blueprint, request
from flask_login import login_required

from ..extensions import db
from ..models import Fine
from ..utils import ApiError, ok, staff_required

fines_bp = Blueprint("fines", __name__)


@fines_bp.get("")
@login_required
def list_fines():
    """List fines, optionally filtered by ``status`` or ``member_id``."""
    query = Fine.query

    status = (request.args.get("status") or "").strip()
    if status:
        query = query.filter(Fine.status == status)

    member_id = request.args.get("member_id")
    if member_id:
        query = query.filter(Fine.member_id == int(member_id))

    fines = query.order_by(Fine.created_at.desc()).all()
    total_unpaid = round(
        sum(f.amount for f in fines if f.status == "unpaid"), 2
    )
    return ok([f.to_dict() for f in fines], total_unpaid=total_unpaid)


@fines_bp.post("/<int:fine_id>/pay")
@staff_required
def pay_fine(fine_id):
    """Mark a fine as paid (staff only)."""
    fine = db.session.get(Fine, fine_id)
    if fine is None:
        raise ApiError("Fine not found.", 404)
    if fine.status != "unpaid":
        raise ApiError(f"Fine is already {fine.status}.", 409)

    fine.status = "paid"
    fine.paid_at = datetime.utcnow()
    db.session.commit()
    return ok(fine.to_dict())


@fines_bp.post("/<int:fine_id>/waive")
@staff_required
def waive_fine(fine_id):
    """Waive (cancel) a fine (staff only)."""
    fine = db.session.get(Fine, fine_id)
    if fine is None:
        raise ApiError("Fine not found.", 404)
    if fine.status != "unpaid":
        raise ApiError(f"Fine is already {fine.status}.", 409)

    fine.status = "waived"
    fine.paid_at = datetime.utcnow()
    db.session.commit()
    return ok(fine.to_dict())
