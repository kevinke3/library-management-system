"""Book catalogue endpoints with search, filtering and CRUD."""
import csv
import io

from flask import Blueprint, request, send_file
from flask_login import login_required

from ..extensions import db
from ..models import Book
from ..utils import ApiError, ok, require_fields, staff_required
from .importer import (
    EXAMPLE_ROW,
    TEMPLATE_COLUMNS,
    ImportError_,
    parse_upload,
)

books_bp = Blueprint("books", __name__)


def _coerce_int(value, field):
    """Parse ``value`` into an int, raising a friendly error on failure."""
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"'{field}' must be a whole number.", 400)


@books_bp.get("")
@login_required
def list_books():
    """List books with optional search, category filter and pagination.

    Query params: ``q`` (title/author/isbn search), ``category``,
    ``availability`` (available|out_of_stock), ``page``, ``per_page``.
    """
    query = Book.query

    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Book.title.ilike(like),
                Book.author.ilike(like),
                Book.isbn.ilike(like),
            )
        )

    category = (request.args.get("category") or "").strip()
    if category:
        query = query.filter(Book.category == category)

    availability = (request.args.get("availability") or "").strip()
    if availability == "available":
        query = query.filter(Book.available_copies > 0)
    elif availability == "out_of_stock":
        query = query.filter(Book.available_copies <= 0)

    page = _coerce_int(request.args.get("page"), "page") or 1
    per_page = min(_coerce_int(request.args.get("per_page"), "per_page") or 50, 200)

    pagination = query.order_by(Book.title.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    return ok(
        [b.to_dict() for b in pagination.items],
        total=pagination.total,
        page=page,
        per_page=per_page,
    )


@books_bp.get("/categories")
@login_required
def list_categories():
    """Return the distinct list of categories used in the catalogue."""
    rows = (
        db.session.query(Book.category)
        .filter(Book.category.isnot(None))
        .distinct()
        .order_by(Book.category.asc())
        .all()
    )
    return ok([r[0] for r in rows if r[0]])


@books_bp.get("/<int:book_id>")
@login_required
def get_book(book_id):
    book = db.session.get(Book, book_id)
    if book is None:
        raise ApiError("Book not found.", 404)
    return ok(book.to_dict())


@books_bp.post("")
@staff_required
def create_book():
    """Add a new title to the catalogue (staff only)."""
    data = request.get_json(silent=True) or {}
    require_fields(data, ["title", "author", "isbn"])

    isbn = str(data["isbn"]).strip()
    if Book.query.filter_by(isbn=isbn).first():
        raise ApiError("A book with that ISBN already exists.", 409)

    total = _coerce_int(data.get("total_copies"), "total_copies")
    total = total if total is not None else 1
    if total < 1:
        raise ApiError("'total_copies' must be at least 1.", 400)

    book = Book(
        title=data["title"].strip(),
        author=data["author"].strip(),
        isbn=isbn,
        category=(data.get("category") or "").strip() or None,
        publisher=(data.get("publisher") or "").strip() or None,
        published_year=_coerce_int(data.get("published_year"), "published_year"),
        shelf_location=(data.get("shelf_location") or "").strip() or None,
        description=(data.get("description") or "").strip() or None,
        total_copies=total,
        available_copies=total,
    )
    db.session.add(book)
    db.session.commit()
    return ok(book.to_dict(), 201)


@books_bp.get("/import/template")
@staff_required
def import_template():
    """Download a bulk-import template (``?format=csv`` or ``xlsx``)."""
    fmt = (request.args.get("format") or "csv").lower()

    if fmt == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Books"
        ws.append(TEMPLATE_COLUMNS)
        ws.append([EXAMPLE_ROW[c] for c in TEMPLATE_COLUMNS])
        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        return send_file(
            buffer,
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name="books-import-template.xlsx",
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(TEMPLATE_COLUMNS)
    writer.writerow([EXAMPLE_ROW[c] for c in TEMPLATE_COLUMNS])
    buffer = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(
        buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name="books-import-template.csv",
    )


@books_bp.post("/import")
@staff_required
def import_books():
    """Bulk import books from an uploaded CSV/XLSX file (staff only).

    For each row: a new ISBN creates a book; an existing ISBN adds the row's
    copies to that book's total (and available) count. Rows that fail validation
    are skipped and reported individually so a single bad row never blocks the
    rest of the import.
    """
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        raise ApiError("No file uploaded. Attach a CSV or XLSX file.", 400)

    try:
        rows = parse_upload(upload.filename, upload.read())
    except ImportError_ as exc:
        raise ApiError(str(exc), 400)

    created = 0
    copies_added = 0
    skipped = []

    for index, row in enumerate(rows):
        # Row number as seen by the user: +2 accounts for the header row and
        # 1-based counting.
        row_no = index + 2
        title = (row.get("title") or "").strip()
        author = (row.get("author") or "").strip()
        isbn = (row.get("isbn") or "").strip()

        if not (title and author and isbn):
            skipped.append({"row": row_no, "reason": "Missing title, author or ISBN."})
            continue

        try:
            total = _coerce_int(row.get("total_copies"), "total_copies")
        except ApiError:
            skipped.append({"row": row_no, "reason": "total_copies must be a whole number."})
            continue
        total = total if total is not None else 1
        if total < 1:
            skipped.append({"row": row_no, "reason": "total_copies must be at least 1."})
            continue

        try:
            year = _coerce_int(row.get("published_year"), "published_year")
        except ApiError:
            skipped.append({"row": row_no, "reason": "published_year must be a whole number."})
            continue

        existing = Book.query.filter_by(isbn=isbn).first()
        if existing is not None:
            existing.total_copies += total
            existing.available_copies += total
            copies_added += total
            continue

        book = Book(
            title=title,
            author=author,
            isbn=isbn,
            category=(row.get("category") or "").strip() or None,
            publisher=(row.get("publisher") or "").strip() or None,
            published_year=year,
            total_copies=total,
            available_copies=total,
        )
        db.session.add(book)
        # Flush so a duplicate ISBN appearing twice in the same file is caught
        # by the lookup above on the next iteration.
        db.session.flush()
        created += 1

    db.session.commit()
    return ok(
        {
            "created": created,
            "copies_added": copies_added,
            "skipped": skipped,
            "total_rows": len(rows),
        }
    )


@books_bp.put("/<int:book_id>")
@staff_required
def update_book(book_id):
    """Update an existing book (staff only)."""
    book = db.session.get(Book, book_id)
    if book is None:
        raise ApiError("Book not found.", 404)

    data = request.get_json(silent=True) or {}

    if "isbn" in data:
        new_isbn = str(data["isbn"]).strip()
        existing = Book.query.filter_by(isbn=new_isbn).first()
        if existing and existing.id != book.id:
            raise ApiError("A book with that ISBN already exists.", 409)
        book.isbn = new_isbn

    for field in ("title", "author", "category", "publisher", "shelf_location", "description"):
        if field in data:
            value = data[field]
            book.__setattr__(field, value.strip() if isinstance(value, str) else value)

    if "published_year" in data:
        book.published_year = _coerce_int(data.get("published_year"), "published_year")

    if "total_copies" in data:
        new_total = _coerce_int(data.get("total_copies"), "total_copies")
        if new_total is None or new_total < 1:
            raise ApiError("'total_copies' must be at least 1.", 400)
        on_loan = book.total_copies - book.available_copies
        if new_total < on_loan:
            raise ApiError(
                f"Cannot set total below copies currently on loan ({on_loan}).", 400
            )
        book.total_copies = new_total
        book.available_copies = new_total - on_loan

    db.session.commit()
    return ok(book.to_dict())


@books_bp.delete("/<int:book_id>")
@staff_required
def delete_book(book_id):
    """Delete a book. Blocked while copies are out on loan."""
    book = db.session.get(Book, book_id)
    if book is None:
        raise ApiError("Book not found.", 404)
    if book.loans.filter_by(status="borrowed").count() > 0:
        raise ApiError("Cannot delete a book that has active loans.", 409)

    db.session.delete(book)
    db.session.commit()
    return ok({"message": "Book deleted."})
