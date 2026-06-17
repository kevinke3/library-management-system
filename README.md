# LibraryOS — Library Management System

A modern, production-ready Library Management System with a clean white & blue
interface. It combines a **Flask** REST API backend with a **standalone
vanilla HTML/CSS/JS** frontend. The UI is fully responsive, uses the **Outfit**
font and real **SVG icons** (no emoji), and feels like an enterprise tool used by
universities and public libraries.

## Features

- **Authentication & RBAC** — session login (Flask-Login) with three roles:
  `admin`, `librarian`, `member`. Staff (admin/librarian) manage data; members
  have read access.
- **Books** — full CRUD, ISBN uniqueness, copies tracking, search & filtering by
  category and availability.
- **Members** — patron CRUD with auto-generated membership IDs, search & status
  filtering.
- **Bulk book import** — librarians can import many books at once from a
  **CSV or Excel (.xlsx)** file (downloadable template provided). New ISBNs
  create books; existing ISBNs add copies; invalid rows are skipped and reported
  individually.
- **Borrowing & Returns** — issue books (availability, member status and
  borrowing-limit checks), return books, automatic **overdue tracking**.
- **Fines** — automatic **fine calculation** on overdue return, pay/waive
  workflow, outstanding balance per member.
- **M-Pesa payments** — settle fines via Safaricom **Daraja STK Push**
  (Lipa Na M-Pesa Online); asynchronous callback marks the fine paid and stores
  the M-Pesa receipt.
- **Dashboard** — headline statistics cards.
- **Reports & Analytics** — most borrowed books, books by category, loans over
  time, fines by status.
- **UX** — collapsible sidebar, top navigation bar, modal forms, toast
  notifications, smooth animations, mobile responsive.
- **Quality** — input validation, consistent JSON API responses, JSON error
  handling, realistic seed data.

## Tech stack

| Layer    | Technology |
|----------|------------|
| Backend  | Flask, Flask-SQLAlchemy, Flask-Login, Flask-Migrate, Flask-CORS, SQLite |
| Frontend | HTML5, CSS3, vanilla JavaScript (no build step) |

## Project structure

```
library-management-system/
├── backend/
│   ├── app/
│   │   ├── __init__.py        # application factory, error handlers, frontend serving
│   │   ├── extensions.py      # db, login_manager, migrate, cors
│   │   ├── models.py          # User, Book, Member, Loan, Fine
│   │   ├── utils.py           # JSON helpers, validation, RBAC decorators
│   │   ├── auth/              # register / login / logout / me
│   │   ├── books/             # catalogue CRUD + search
│   │   ├── members/           # patron CRUD + search
│   │   ├── loans/             # issue / return / overdue (fine calculation)
│   │   ├── fines/             # list / pay / waive
│   │   └── dashboard/         # stats + reports
│   ├── config.py              # environment-aware configuration
│   ├── run.py                 # dev entry point
│   ├── seed.py                # realistic sample data
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── index.html
    ├── style.css
    └── script.js
```

## Getting started

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt

# (optional) configure environment
cp .env.example .env

# create the database schema via migrations
export FLASK_APP=run.py             # Windows: set FLASK_APP=run.py
flask db upgrade

# load realistic sample data (drops & recreates tables)
python seed.py

# run the server
python run.py
```

The API and the bundled frontend are now served at <http://localhost:5000>.

### 2. Frontend

The frontend is served automatically by Flask at `/`, so just open
<http://localhost:5000>. Because it is plain static files, you can also host
`frontend/` from any static server; in that case set the API base before
`script.js` loads:

```html
<script>window.LMS_API_BASE = "http://localhost:5000";</script>
```

## Demo accounts

The seed script creates one account per role:

| Role      | Email                     | Password      |
|-----------|---------------------------|---------------|
| Admin     | `admin@library.test`      | `admin123`    |
| Librarian | `librarian@library.test`  | `librarian123`|
| Member    | `member@library.test`     | `member123`   |

> The first account ever registered (when the database is empty) automatically
> becomes an admin, so a fresh install is usable immediately.

## API overview

All endpoints are under `/api` and return JSON shaped as `{ "data": ... }` on
success or `{ "error": "...", "details": {...} }` on failure.

| Method | Endpoint | Description | Access |
|--------|----------|-------------|--------|
| POST | `/api/auth/register` | Create account (first user = admin) | public |
| POST | `/api/auth/login` | Log in | public |
| POST | `/api/auth/logout` | Log out | auth |
| GET  | `/api/auth/me` | Current user | public |
| GET/POST | `/api/books` | List (search/filter) / create | auth / staff |
| GET/PUT/DELETE | `/api/books/<id>` | Retrieve / update / delete | auth / staff |
| GET | `/api/books/categories` | Distinct categories | auth |
| GET | `/api/books/import/template` | Download import template (`?format=csv\|xlsx`) | staff |
| POST | `/api/books/import` | Bulk import books from CSV/XLSX upload | staff |
| GET/POST | `/api/members` | List (search/filter) / create | auth / staff |
| GET/PUT/DELETE | `/api/members/<id>` | Retrieve / update / delete | auth / staff |
| GET/POST | `/api/loans` | List (filter) / issue | auth / staff |
| POST | `/api/loans/<id>/return` | Return a book (auto fine) | staff |
| GET | `/api/loans/overdue` | Overdue loans | auth |
| GET | `/api/fines` | List fines | auth |
| POST | `/api/fines/<id>/pay` | Mark fine paid | staff |
| POST | `/api/fines/<id>/waive` | Waive fine | staff |
| GET | `/api/payments` | List M-Pesa payment attempts | auth |
| POST | `/api/payments/stkpush` | Start STK Push for a fine | auth |
| GET | `/api/payments/<checkout_request_id>` | Poll payment status | auth |
| POST | `/api/payments/callback` | Daraja result webhook | public |
| GET | `/api/dashboard/stats` | Dashboard statistics | auth |
| GET | `/api/dashboard/reports` | Analytics series | auth |

## Configuration

Behaviour is controlled via environment variables (see `.env.example`):

- `LOAN_PERIOD_DAYS` (default `14`) — borrowing period length.
- `FINE_PER_DAY` (default `10`) — fine charged per overdue day.
- `MAX_ACTIVE_LOANS` (default `5`) — concurrent loans per member.
- `SECRET_KEY`, `DATABASE_URL`, `CORS_ORIGINS`.

### M-Pesa (Daraja) — paying fines

The STK Push flow needs Safaricom Daraja credentials and a publicly reachable
callback URL (Daraja cannot reach `localhost`). Set these in `.env`:

- `MPESA_ENV` — `sandbox` (default) or `production`.
- `DARAJA_CONSUMER_KEY`, `DARAJA_CONSUMER_SECRET` — from your app on
  <https://developer.safaricom.co.ke>.
- `MPESA_SHORTCODE`, `MPESA_PASSKEY` — default to Safaricom's public sandbox
  paybill `174379` and test passkey; override for production.
- `MPESA_TRANSACTION_TYPE` — `CustomerPayBillOnline` (paybill) or
  `CustomerBuyGoodsOnline` (till).
- `MPESA_CALLBACK_BASE_URL` — public base URL Daraja posts results to, e.g. an
  ngrok/cloudflared tunnel during development. The path
  `/api/payments/callback` is appended automatically.

For local testing, expose the backend with a tunnel
(`cloudflared tunnel --url http://localhost:5000`) and set
`MPESA_CALLBACK_BASE_URL` to the generated HTTPS URL. In the sandbox, use a Daraja
test MSISDN (e.g. `254708374149`) as the payer phone number.

## Production notes

- Run behind a WSGI server: `gunicorn 'app:create_app()'`.
- Set a strong `SECRET_KEY` and a specific `CORS_ORIGINS`.
- Use `flask db upgrade` for schema changes (do **not** run `seed.py`, which
  resets the database).
