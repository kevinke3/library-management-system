"""Populate the database with realistic sample data for demonstrations.

Running ``python seed.py`` drops and recreates all tables, then inserts users,
books, members, loans (including some overdue) and the resulting fines so the
dashboard, reports and every screen have meaningful content immediately.

The script is safe to re-run: it always starts from a clean schema.
"""
from datetime import date, datetime, timedelta

from app import create_app
from app.extensions import db
from app.models import Book, Fine, Loan, Member, User

app = create_app("development")

# Default loan/fine rules mirror the application configuration.
LOAN_PERIOD_DAYS = 14
FINE_PER_DAY = 10.0


def seed_users():
    """Create one account per role. Passwords are shown in the README."""
    users = [
        ("Amina Director", "admin@library.test", "admin123", "admin"),
        ("James Librarian", "librarian@library.test", "librarian123", "librarian"),
        ("Grace Member", "member@library.test", "member123", "member"),
    ]
    created = []
    for name, email, password, role in users:
        user = User(name=name, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        created.append(user)
    db.session.flush()
    return created


def seed_books():
    """A small but varied catalogue across several categories."""
    catalogue = [
        ("Clean Code", "Robert C. Martin", "9780132350884", "Software", "Prentice Hall", 2008, "A1", 4),
        ("The Pragmatic Programmer", "Andrew Hunt", "9780201616224", "Software", "Addison-Wesley", 1999, "A2", 3),
        ("Introduction to Algorithms", "Thomas H. Cormen", "9780262033848", "Computer Science", "MIT Press", 2009, "A3", 2),
        ("Design Patterns", "Erich Gamma", "9780201633610", "Software", "Addison-Wesley", 1994, "A4", 2),
        ("Sapiens", "Yuval Noah Harari", "9780099590088", "History", "Vintage", 2011, "B1", 5),
        ("Thinking, Fast and Slow", "Daniel Kahneman", "9780374533557", "Psychology", "FSG", 2011, "B2", 3),
        ("The Lean Startup", "Eric Ries", "9780307887894", "Business", "Crown", 2011, "C1", 4),
        ("Atomic Habits", "James Clear", "9780735211292", "Self-Help", "Avery", 2018, "C2", 6),
        ("A Brief History of Time", "Stephen Hawking", "9780553380163", "Science", "Bantam", 1998, "D1", 2),
        ("The Selfish Gene", "Richard Dawkins", "9780198788607", "Science", "Oxford", 1976, "D2", 2),
        ("To Kill a Mockingbird", "Harper Lee", "9780061120084", "Fiction", "Harper", 1960, "E1", 3),
        ("1984", "George Orwell", "9780451524935", "Fiction", "Signet", 1949, "E2", 4),
        ("Educated", "Tara Westover", "9780399590504", "Biography", "Random House", 2018, "F1", 3),
        ("Deep Work", "Cal Newport", "9781455586691", "Self-Help", "Grand Central", 2016, "C3", 2),
        ("The Mythical Man-Month", "Frederick P. Brooks Jr.", "9780201835953", "Software", "Addison-Wesley", 1995, "A5", 1),
    ]
    books = []
    for title, author, isbn, category, publisher, year, shelf, copies in catalogue:
        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            category=category,
            publisher=publisher,
            published_year=year,
            shelf_location=shelf,
            total_copies=copies,
            available_copies=copies,
            description=f"{title} by {author}.",
        )
        db.session.add(book)
        books.append(book)
    db.session.flush()
    return books


def seed_members():
    """A handful of patrons of different membership tiers."""
    people = [
        ("Brian Otieno", "brian.otieno@example.com", "+254700111222", "Nairobi", "student"),
        ("Cynthia Wanjiru", "cynthia.w@example.com", "+254700333444", "Mombasa", "standard"),
        ("David Kimani", "david.kimani@example.com", "+254700555666", "Kisumu", "premium"),
        ("Esther Achieng", "esther.a@example.com", "+254700777888", "Nakuru", "student"),
        ("Felix Mwangi", "felix.mwangi@example.com", "+254700999000", "Eldoret", "standard"),
        ("Hellen Njoroge", "hellen.n@example.com", "+254701222333", "Thika", "premium"),
    ]
    members = []
    for idx, (name, email, phone, address, mtype) in enumerate(people, start=1):
        member = Member(
            membership_id=f"LIB-{idx:06d}",
            name=name,
            email=email,
            phone=phone,
            address=address,
            membership_type=mtype,
            status="active",
            join_date=date.today() - timedelta(days=30 * idx),
        )
        db.session.add(member)
        members.append(member)
    db.session.flush()
    return members


def seed_loans_and_fines(books, members):
    """Create active, overdue and returned loans plus the resulting fines."""
    today = date.today()

    def make_loan(book, member, loan_offset, returned_offset=None):
        loan = Loan(
            book_id=book.id,
            member_id=member.id,
            loan_date=today - timedelta(days=loan_offset),
            due_date=today - timedelta(days=loan_offset) + timedelta(days=LOAN_PERIOD_DAYS),
        )
        if returned_offset is not None:
            loan.return_date = today - timedelta(days=returned_offset)
            loan.status = "returned"
        else:
            loan.status = "borrowed"
            book.available_copies -= 1
        db.session.add(loan)
        db.session.flush()
        return loan

    # Currently borrowed, not yet due.
    make_loan(books[0], members[0], loan_offset=3)
    make_loan(books[7], members[1], loan_offset=5)
    make_loan(books[4], members[2], loan_offset=1)

    # Currently borrowed and overdue (will surface in overdue tracking).
    make_loan(books[2], members[3], loan_offset=25)
    make_loan(books[11], members[0], loan_offset=20)

    # Returned on time (no fine).
    make_loan(books[5], members[4], loan_offset=40, returned_offset=30)

    # Returned late -> generate a fine just like the return endpoint does.
    late_loan = make_loan(books[8], members[5], loan_offset=45, returned_offset=20)
    days_overdue = (late_loan.return_date - late_loan.due_date).days
    if days_overdue > 0:
        db.session.add(
            Fine(
                loan_id=late_loan.id,
                member_id=late_loan.member_id,
                amount=round(days_overdue * FINE_PER_DAY, 2),
                reason=f"Overdue by {days_overdue} day(s).",
                status="unpaid",
            )
        )

    # An already-paid fine for variety in the reports.
    paid_loan = make_loan(books[10], members[1], loan_offset=60, returned_offset=40)
    paid_days = (paid_loan.return_date - paid_loan.due_date).days
    if paid_days > 0:
        db.session.add(
            Fine(
                loan_id=paid_loan.id,
                member_id=paid_loan.member_id,
                amount=round(paid_days * FINE_PER_DAY, 2),
                reason=f"Overdue by {paid_days} day(s).",
                status="paid",
                paid_at=datetime.utcnow(),
            )
        )


def main():
    with app.app_context():
        print("Resetting database schema ...")
        db.drop_all()
        db.create_all()

        print("Seeding users ...")
        seed_users()
        print("Seeding books ...")
        books = seed_books()
        print("Seeding members ...")
        members = seed_members()
        print("Seeding loans and fines ...")
        seed_loans_and_fines(books, members)

        db.session.commit()
        print("Done. Sample login: admin@library.test / admin123")


if __name__ == "__main__":
    main()
