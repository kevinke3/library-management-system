"""Dashboard statistics and analytical reports."""
from collections import Counter
from datetime import date, timedelta

from flask import Blueprint
from flask_login import login_required

from ..extensions import db
from ..models import Book, Fine, Loan, Member
from ..utils import ok

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/stats")
@login_required
def stats():
    """Return the headline figures shown on the dashboard cards."""
    total_books = Book.query.count()
    total_copies = db.session.query(db.func.sum(Book.total_copies)).scalar() or 0
    available_copies = (
        db.session.query(db.func.sum(Book.available_copies)).scalar() or 0
    )
    total_members = Member.query.count()
    active_members = Member.query.filter_by(status="active").count()

    active_loans = Loan.query.filter(Loan.status != "returned").all()
    borrowed_count = len(active_loans)
    overdue_count = sum(1 for loan in active_loans if loan.is_overdue)

    unpaid_fines = Fine.query.filter_by(status="unpaid").all()
    outstanding_fines = round(sum(f.amount for f in unpaid_fines), 2)

    return ok(
        {
            "total_books": total_books,
            "total_copies": int(total_copies),
            "available_copies": int(available_copies),
            "books_on_loan": int(total_copies) - int(available_copies),
            "total_members": total_members,
            "active_members": active_members,
            "active_loans": borrowed_count,
            "overdue_loans": overdue_count,
            "outstanding_fines": outstanding_fines,
        }
    )


@dashboard_bp.get("/reports")
@login_required
def reports():
    """Return data series used to render the reports & analytics charts."""
    # Most borrowed books (all time, top 5).
    loan_book_counts = Counter(loan.book_id for loan in Loan.query.all())
    popular = []
    for book_id, count in loan_book_counts.most_common(5):
        book = db.session.get(Book, book_id)
        if book:
            popular.append({"title": book.title, "loans": count})

    # Books grouped by category.
    category_rows = (
        db.session.query(Book.category, db.func.count(Book.id))
        .group_by(Book.category)
        .all()
    )
    categories = [
        {"category": (cat or "Uncategorised"), "count": cnt}
        for cat, cnt in category_rows
    ]

    # Loans issued per day over the last 14 days.
    today = date.today()
    start = today - timedelta(days=13)
    recent_loans = Loan.query.filter(Loan.loan_date >= start).all()
    per_day_counter = Counter(loan.loan_date for loan in recent_loans)
    loans_over_time = []
    for offset in range(14):
        day = start + timedelta(days=offset)
        loans_over_time.append(
            {"date": day.isoformat(), "loans": per_day_counter.get(day, 0)}
        )

    # Fine totals by status.
    fine_rows = (
        db.session.query(Fine.status, db.func.sum(Fine.amount))
        .group_by(Fine.status)
        .all()
    )
    fines_by_status = [
        {"status": status, "amount": round(amount or 0, 2)} for status, amount in fine_rows
    ]

    return ok(
        {
            "popular_books": popular,
            "books_by_category": categories,
            "loans_over_time": loans_over_time,
            "fines_by_status": fines_by_status,
        }
    )
