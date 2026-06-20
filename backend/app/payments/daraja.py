"""Thin client for the Safaricom Daraja (M-Pesa) API.

The client is intentionally small and only implements what the Library
Management System needs: OAuth token retrieval (cached until it expires) and the
Lipa Na M-Pesa Online ("STK Push") request used to prompt a member to pay a fine
from their phone.

All network behaviour is contained here so the route handlers stay focused on
HTTP/JSON concerns and database updates.
"""
import base64
import time
from datetime import datetime

import requests
from flask import current_app

# Daraja API base URLs by environment.
_BASE_URLS = {
    "sandbox": "https://sandbox.safaricom.co.ke",
    "production": "https://api.safaricom.co.ke",
}

# Default request timeout (seconds) for all outbound Daraja calls.
_TIMEOUT = 30

# Process-local cache for the OAuth token: {"token": str, "expires_at": float}.
_token_cache = {"token": None, "expires_at": 0.0}


class DarajaError(Exception):
    """Raised when a Daraja request fails or the integration is misconfigured."""


def _base_url():
    env = (current_app.config.get("MPESA_ENV") or "sandbox").lower()
    return _BASE_URLS.get(env, _BASE_URLS["sandbox"])


def _require_credentials():
    key = current_app.config.get("MPESA_CONSUMER_KEY")
    secret = current_app.config.get("MPESA_CONSUMER_SECRET")
    if not key or not secret:
        raise DarajaError(
            "M-Pesa is not configured. Set DARAJA_CONSUMER_KEY and "
            "DARAJA_CONSUMER_SECRET in the environment."
        )
    return key, secret


def get_access_token(force_refresh=False):
    """Return a valid OAuth access token, fetching a new one when needed."""
    now = time.time()
    if (
        not force_refresh
        and _token_cache["token"]
        and now < _token_cache["expires_at"]
    ):
        return _token_cache["token"]

    key, secret = _require_credentials()
    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    try:
        resp = requests.get(url, auth=(key, secret), timeout=_TIMEOUT)
    except requests.RequestException as exc:  # pragma: no cover - network error
        raise DarajaError(f"Could not reach Daraja: {exc}") from exc

    if resp.status_code != 200:
        raise DarajaError(
            f"Daraja auth failed ({resp.status_code}): {resp.text[:200]}"
        )

    payload = resp.json()
    token = payload.get("access_token")
    if not token:
        raise DarajaError("Daraja auth response did not contain an access token.")

    # Tokens last 3600s; refresh a minute early to avoid edge-of-expiry failures.
    expires_in = int(payload.get("expires_in", 3600))
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(expires_in - 60, 0)
    return token


def normalize_phone(phone):
    """Convert a Kenyan phone number to Daraja's ``2547XXXXXXXX`` MSISDN format."""
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if digits.startswith("254"):
        msisdn = digits
    elif digits.startswith("0"):
        msisdn = "254" + digits[1:]
    elif digits.startswith("7") or digits.startswith("1"):
        msisdn = "254" + digits
    else:
        msisdn = digits
    if len(msisdn) != 12:
        raise DarajaError(f"Invalid Kenyan phone number: {phone!r}")
    return msisdn


def _password(shortcode, passkey, timestamp):
    """Build the base64 STK Push password = base64(shortcode + passkey + ts)."""
    raw = f"{shortcode}{passkey}{timestamp}".encode("utf-8")
    return base64.b64encode(raw).decode("utf-8")


def stk_push(phone, amount, account_reference, description, callback_url):
    """Initiate an STK Push and return the parsed Daraja JSON response.

    Raises :class:`DarajaError` on configuration or network problems, or when
    Daraja rejects the request.
    """
    token = get_access_token()
    shortcode = current_app.config["MPESA_SHORTCODE"]
    passkey = current_app.config["MPESA_PASSKEY"]
    txn_type = current_app.config.get(
        "MPESA_TRANSACTION_TYPE", "CustomerPayBillOnline"
    )
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

    body = {
        "BusinessShortCode": shortcode,
        "Password": _password(shortcode, passkey, timestamp),
        "Timestamp": timestamp,
        "TransactionType": txn_type,
        # Daraja requires a whole-number amount.
        "Amount": int(round(float(amount))),
        "PartyA": normalize_phone(phone),
        "PartyB": shortcode,
        "PhoneNumber": normalize_phone(phone),
        "CallBackURL": callback_url,
        "AccountReference": account_reference[:12],
        "TransactionDesc": description[:stk_desc_limit()],
    }

    url = f"{_base_url()}/mpesa/stkpush/v1/processrequest"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=_TIMEOUT)
    except requests.RequestException as exc:  # pragma: no cover - network error
        raise DarajaError(f"Could not reach Daraja: {exc}") from exc

    data = resp.json() if resp.content else {}
    # A successful STK Push returns ResponseCode "0".
    if resp.status_code != 200 or str(data.get("ResponseCode")) != "0":
        message = (
            data.get("errorMessage")
            or data.get("ResponseDescription")
            or resp.text[:200]
        )
        raise DarajaError(f"STK Push failed: {message}")
    return data


def stk_desc_limit():
    """Daraja caps TransactionDesc at 13 characters."""
    return 13
