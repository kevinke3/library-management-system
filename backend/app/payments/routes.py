"""M-Pesa (Daraja) payment endpoints.

Flow:
1. ``POST /api/payments/stkpush`` creates a ``pending`` :class:`Payment` and asks
   Daraja to send an STK Push prompt to the member's phone.
2. The member enters their M-Pesa PIN; Daraja then calls
   ``POST /api/payments/callback`` with the result.
3. On success the linked :class:`Fine` is marked ``paid`` and the receipt number
   is stored. The frontend polls ``GET /api/payments/<checkout_request_id>``
   until the status settles.
"""
from datetime import datetime

from flask import Blueprint, current_app, request
from flask_login import login_required

from ..extensions import db
from ..models import Fine, Payment
from ..utils import ApiError, ok, require_fields
from .daraja import DarajaError, normalize_phone, stk_push

payments_bp = Blueprint("payments", __name__)

# Path Daraja POSTs the asynchronous result to, appended to the public base URL.
CALLBACK_PATH = "/api/payments/callback"


@payments_bp.get("")
@login_required
def list_payments():
    """List payment attempts, newest first (optionally filtered by fine)."""
    query = Payment.query
    fine_id = request.args.get("fine_id")
    if fine_id:
        query = query.filter(Payment.fine_id == int(fine_id))
    payments = query.order_by(Payment.created_at.desc()).all()
    return ok([p.to_dict() for p in payments])


@payments_bp.post("/stkpush")
@login_required
def initiate_stk_push():
    """Trigger an STK Push for an unpaid fine."""
    data = request.get_json(silent=True) or {}
    require_fields(data, ["fine_id", "phone"])

    fine = db.session.get(Fine, int(data["fine_id"]))
    if fine is None:
        raise ApiError("Fine not found.", 404)
    if fine.status != "unpaid":
        raise ApiError(f"Fine is already {fine.status}.", 409)

    try:
        phone = normalize_phone(data["phone"])
    except DarajaError as exc:
        raise ApiError(str(exc), 400)

    base_url = (current_app.config.get("MPESA_CALLBACK_BASE_URL") or "").rstrip("/")
    if not base_url:
        raise ApiError(
            "Payment callback URL is not configured. Set MPESA_CALLBACK_BASE_URL.",
            503,
        )
    callback_url = base_url + CALLBACK_PATH

    payment = Payment(
        fine_id=fine.id,
        member_id=fine.member_id,
        amount=fine.amount,
        phone=phone,
        status="pending",
    )
    db.session.add(payment)
    db.session.flush()

    reference = fine.member.membership_id if fine.member else f"FINE{fine.id}"
    try:
        result = stk_push(
            phone=phone,
            amount=fine.amount,
            account_reference=reference,
            description="Library fine",
            callback_url=callback_url,
        )
    except DarajaError as exc:
        payment.status = "failed"
        payment.result_desc = str(exc)[:255]
        db.session.commit()
        raise ApiError(str(exc), 502)

    payment.merchant_request_id = result.get("MerchantRequestID")
    payment.checkout_request_id = result.get("CheckoutRequestID")
    db.session.commit()

    return ok(
        payment.to_dict(),
        status_code=201,
        customer_message=result.get("CustomerMessage"),
    )


@payments_bp.get("/<checkout_request_id>")
@login_required
def payment_status(checkout_request_id):
    """Return the latest state of a payment so the frontend can poll it."""
    payment = (
        Payment.query.filter_by(checkout_request_id=checkout_request_id)
        .order_by(Payment.created_at.desc())
        .first()
    )
    if payment is None:
        raise ApiError("Payment not found.", 404)
    return ok(payment.to_dict())


@payments_bp.post("/callback")
def daraja_callback():
    """Public webhook Daraja calls with the STK Push result.

    This endpoint is intentionally unauthenticated (Daraja cannot present our
    session cookie). It is idempotent and always returns the JSON acknowledgement
    Daraja expects, even when we cannot match the payment, so Safaricom does not
    retry indefinitely.
    """
    body = request.get_json(silent=True) or {}
    stk = (body.get("Body") or {}).get("stkCallback") or {}

    checkout_id = stk.get("CheckoutRequestID")
    result_code = stk.get("ResultCode")
    result_desc = stk.get("ResultDesc")

    payment = None
    if checkout_id:
        payment = Payment.query.filter_by(
            checkout_request_id=checkout_id
        ).first()

    if payment is not None and payment.status == "pending":
        payment.result_desc = (result_desc or "")[:255]
        if str(result_code) == "0":
            payment.status = "success"
            payment.mpesa_receipt = _extract_receipt(stk)
            fine = payment.fine
            if fine is not None and fine.status == "unpaid":
                fine.status = "paid"
                fine.paid_at = datetime.utcnow()
        else:
            payment.status = "failed"
        db.session.commit()

    # Daraja expects this acknowledgement shape.
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


def _extract_receipt(stk_callback):
    """Pull ``MpesaReceiptNumber`` out of the callback metadata items."""
    items = (stk_callback.get("CallbackMetadata") or {}).get("Item") or []
    for item in items:
        if item.get("Name") == "MpesaReceiptNumber":
            return item.get("Value")
    return None
