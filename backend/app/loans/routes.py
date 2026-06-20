"""Borrowing endpoints: issue a book, return a book and track overdue loans.

This module also owns the fine calculation logic which runs automatically when
an overdue book is returned.
"""
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, request
from flask_login import login_required

from ..extensions import db
from ..models import Book, Fine, Loan, Member
from ..utils import ApiError, ok, require_fields, staff_required

loans_bp = Blueprint("loans", __name__)


@loans_bp.get("")
@login_required
def list_loans():
    """List loans, optionally filtered by ``status`` and ``member_id``.

    ``status`` may be ``borrowed``, ``returned`` or ``overdue``. Overdue is
    derived from due dates rather than stored, so it is filtered in Python.
    """
    query = Loan.query
    member_id = request.args.get("member_id")
    if member_id:
        query = query.filter(Loan.member_id == int(member_id))

    status = (request.args.get("status") or "").strip()
    loans = query.order_by(Loan.loan_date.desc(), Loan.id.desc()).all()

    if status == "overdue":
        loans = [loan for loan in loans if loan.display_status == "overdue"]
    elif status in ("borrowed", "returned"):
        loans = [loan for loan in loans if loan.display_status == status]

    return ok([loan.to_dict() for loan in loans])


@loans_bp.get("/<int:loan_id>")
@login_required
def get_loan(loan_id):
    loan = db.session.get(Loan, loan_id)
    if loan is None:
        raise ApiError("Loan not found.", 404)
    return ok(loan.to_dict())


@loans_bp.post("")
@staff_required
def issue_loan():
    """Issue a book to a member (staff only).

    Validates availability, member status and borrowing limits, then decrements
    the book's available copies and records the due date.
    """
    data = request.get_json(silent=True) or {}
    require_fields(data, ["book_id", "member_id"])

    book = db.session.get(Book, int(data["book_id"]))
    if book is None:
        raise ApiError("Book not found.", 404)
    member = db.session.get(Member, int(data["member_id"]))
    if member is None:
        raise ApiError("Member not found.", 404)

    if member.status != "active":
        raise ApiError("This member is not active and cannot borrow books.", 409)
    if book.available_copies < 1:
        raise ApiError("No copies of this book are currently available.", 409)

    max_loans = current_app.config["MAX_ACTIVE_LOANS"]
    if member.active_loans_count >= max_loans:
        raise ApiError(
            f"Member has reached the borrowing limit of {max_loans} books.", 409
        )

    loan_period = current_app.config["LOAN_PERIOD_DAYS"]
    loan = Loan(
        book_id=book.id,
        member_id=member.id,
        loan_date=date.today(),
        due_date=date.today() + timedelta(days=loan_period),
        status="borrowed",
    )
    book.available_copies -= 1
    db.session.add(loan)
    db.session.commit()
    return ok(loan.to_dict(), 201)


@loans_bp.post("/<int:loan_id>/return")
@staff_required
def return_loan(loan_id):
    """Return a borrowed book and raise an overdue fine when applicable."""
    loan = db.session.get(Loan, loan_id)
    if loan is None:
        raise ApiError("Loan not found.", 404)
    if loan.status == "returned":
        raise ApiError("This loan has already been returned.", 409)

    loan.return_date = date.today()
    loan.status = "returned"

    # Restore availability without exceeding the total owned copies.
    if loan.book:
        loan.book.available_copies = min(
            loan.book.available_copies + 1, loan.book.total_copies
        )

    # Automatic fine calculation for overdue returns.
    fine_per_day = current_app.config["FINE_PER_DAY"]
    days_overdue = loan.days_overdue
    if days_overdue > 0 and loan.fine is None:
        fine = Fine(
            loan_id=loan.id,
            member_id=loan.member_id,
            amount=round(days_overdue * fine_per_day, 2),
            reason=f"Overdue by {days_overdue} day(s).",
            status="unpaid",
        )
        db.session.add(fine)

    db.session.commit()
    return ok(loan.to_dict())


@loans_bp.get("/overdue")
@login_required
def overdue_loans():
    """Convenience endpoint returning only currently overdue loans."""
    loans = Loan.query.filter(Loan.status != "returned").all()
    overdue = [loan.to_dict() for loan in loans if loan.is_overdue]
    return ok(overdue, total=len(overdue))
