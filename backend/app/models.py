"""SQLAlchemy models for the Library Management System.

The schema is intentionally small but complete and covers the core entities of a
real library: people who use the system (:class:`User`), the catalogue
(:class:`Book`), library patrons (:class:`Member`), borrowing records
(:class:`Loan`) and monetary penalties (:class:`Fine`).
"""
from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db

# Roles recognised by the role based access control layer.
ROLE_ADMIN = "admin"
ROLE_LIBRARIAN = "librarian"
ROLE_MEMBER = "member"
VALID_ROLES = (ROLE_ADMIN, ROLE_LIBRARIAN, ROLE_MEMBER)


class User(UserMixin, db.Model):
    """An authenticated account that can sign in to the system.

    A user has one of three roles which determines what they are allowed to do.
    Members may optionally be linked to a :class:`Member` patron record.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_MEMBER)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Optional link to the patron profile (only relevant for member accounts).
    member = db.relationship("Member", back_populates="user", uselist=False)

    def set_password(self, password):
        """Hash and store ``password``."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Return ``True`` when ``password`` matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    # Convenience role checks used by views and decorators.
    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_staff(self):
        """Admins and librarians are considered staff."""
        return self.role in (ROLE_ADMIN, ROLE_LIBRARIAN)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"


class Book(db.Model):
    """A title held in the library catalogue.

    ``total_copies`` is the number of physical copies owned while
    ``available_copies`` tracks how many are currently on the shelf. Issuing a
    loan decrements the available count and returning increments it.
    """

    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, index=True)
    author = db.Column(db.String(150), nullable=False, index=True)
    isbn = db.Column(db.String(20), unique=True, nullable=False, index=True)
    category = db.Column(db.String(80), nullable=True, index=True)
    publisher = db.Column(db.String(150), nullable=True)
    published_year = db.Column(db.Integer, nullable=True)
    shelf_location = db.Column(db.String(50), nullable=True)
    description = db.Column(db.Text, nullable=True)
    total_copies = db.Column(db.Integer, nullable=False, default=1)
    available_copies = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    loans = db.relationship("Loan", back_populates="book", lazy="dynamic")

    @property
    def status(self):
        """Human friendly availability status."""
        return "available" if self.available_copies > 0 else "out_of_stock"

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "author": self.author,
            "isbn": self.isbn,
            "category": self.category,
            "publisher": self.publisher,
            "published_year": self.published_year,
            "shelf_location": self.shelf_location,
            "description": self.description,
            "total_copies": self.total_copies,
            "available_copies": self.available_copies,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Book {self.title!r} by {self.author!r}>"


class Member(db.Model):
    """A library patron who can borrow books."""

    __tablename__ = "members"

    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=True)
    address = db.Column(db.String(255), nullable=True)
    membership_type = db.Column(db.String(30), nullable=False, default="standard")
    status = db.Column(db.String(20), nullable=False, default="active")
    join_date = db.Column(db.Date, nullable=False, default=date.today)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    user = db.relationship("User", back_populates="member")

    loans = db.relationship("Loan", back_populates="member", lazy="dynamic")
    fines = db.relationship("Fine", back_populates="member", lazy="dynamic")

    @property
    def active_loans_count(self):
        return self.loans.filter(Loan.status != "returned").count()

    @property
    def outstanding_fines(self):
        """Total unpaid fine amount for this member."""
        rows = self.fines.filter(Fine.status == "unpaid").all()
        return round(sum(f.amount for f in rows), 2)

    def to_dict(self):
        return {
            "id": self.id,
            "membership_id": self.membership_id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "address": self.address,
            "membership_type": self.membership_type,
            "status": self.status,
            "join_date": self.join_date.isoformat() if self.join_date else None,
            "active_loans": self.active_loans_count,
            "outstanding_fines": self.outstanding_fines,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f"<Member {self.membership_id} {self.name!r}>"


class Loan(db.Model):
    """A borrowing record linking a :class:`Book` to a :class:`Member`."""

    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    loan_date = db.Column(db.Date, nullable=False, default=date.today)
    due_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date, nullable=True)
    # One of: borrowed, returned. Overdue is derived from the dates.
    status = db.Column(db.String(20), nullable=False, default="borrowed")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    book = db.relationship("Book", back_populates="loans")
    member = db.relationship("Member", back_populates="loans")
    fine = db.relationship(
        "Fine", back_populates="loan", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def is_overdue(self):
        """``True`` when the book is still out and past its due date."""
        if self.status == "returned":
            return False
        return date.today() > self.due_date

    @property
    def days_overdue(self):
        reference = self.return_date or date.today()
        delta = (reference - self.due_date).days
        return max(delta, 0)

    @property
    def display_status(self):
        if self.status == "returned":
            return "returned"
        return "overdue" if self.is_overdue else "borrowed"

    def to_dict(self):
        return {
            "id": self.id,
            "book_id": self.book_id,
            "book_title": self.book.title if self.book else None,
            "book_isbn": self.book.isbn if self.book else None,
            "member_id": self.member_id,
            "member_name": self.member.name if self.member else None,
            "membership_id": self.member.membership_id if self.member else None,
            "loan_date": self.loan_date.isoformat() if self.loan_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "return_date": self.return_date.isoformat() if self.return_date else None,
            "status": self.display_status,
            "days_overdue": self.days_overdue,
            "fine": self.fine.to_dict() if self.fine else None,
        }

    def __repr__(self):
        return f"<Loan book={self.book_id} member={self.member_id} {self.status}>"


class Fine(db.Model):
    """A monetary penalty raised against an overdue (or damaged) loan."""

    __tablename__ = "fines"

    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey("loans.id"), nullable=False)
    member_id = db.Column(db.Integer, db.ForeignKey("members.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    reason = db.Column(db.String(255), nullable=True)
    # One of: unpaid, paid, waived.
    status = db.Column(db.String(20), nullable=False, default="unpaid")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)

    loan = db.relationship("Loan", back_populates="fine")
    member = db.relationship("Member", back_populates="fines")

    def to_dict(self):
        return {
            "id": self.id,
            "loan_id": self.loan_id,
            "member_id": self.member_id,
            "member_name": self.member.name if self.member else None,
            "amount": round(self.amount, 2),
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
        }

    def __repr__(self):
        return f"<Fine loan={self.loan_id} {self.amount} {self.status}>"
