import logging
from typing import Any

from flask import Blueprint, jsonify, request

from config.supabase import supabase_auth
from routes.users import _current_supabase_session
from services.billing_service import (
    BillingServiceError,
    cancel_user_subscription,
    create_plus_subscription,
    get_user_billing_status,
    process_webhook,
)


billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


def _current_user_with_email() -> tuple[str | None, str | None, tuple[Any, int] | None]:
    auth_user_id, access_token, auth_error = _current_supabase_session()
    if auth_error:
        return None, None, auth_error

    try:
        response = supabase_auth.auth.get_user(access_token)
        user = getattr(response, "user", None)
        return auth_user_id, getattr(user, "email", None), None
    except Exception:
        return None, None, _error("Token de autorizacion invalido", 401)


@billing_bp.get("/me")
def billing_me():
    auth_user_id, _email, auth_error = _current_user_with_email()
    if auth_error:
        return auth_error

    try:
        return jsonify({"success": True, **get_user_billing_status(auth_user_id)}), 200
    except BillingServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR billing_me: %r", exc)
        return _error("Error interno del servidor", 500)


@billing_bp.post("/subscribe")
def subscribe():
    auth_user_id, email, auth_error = _current_user_with_email()
    if auth_error:
        return auth_error

    try:
        data = create_plus_subscription(auth_user_id, email)
        return jsonify({"success": True, **data}), 201
    except BillingServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR billing_subscribe: %r", exc)
        return _error("Error interno del servidor", 500)


@billing_bp.post("/cancel")
def cancel():
    auth_user_id, _email, auth_error = _current_user_with_email()
    if auth_error:
        return auth_error

    try:
        data = cancel_user_subscription(auth_user_id)
        return jsonify({"success": True, **data}), 200
    except BillingServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR billing_cancel: %r", exc)
        return _error("Error interno del servidor", 500)


@billing_bp.post("/webhook")
def webhook():
    body = request.get_json(silent=True) or {}

    try:
        data = process_webhook(
            {key.lower(): value for key, value in request.headers.items()},
            request.args.to_dict(),
            body,
        )
        return jsonify({"success": True, **data}), 200
    except BillingServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR billing_webhook: %r", exc)
        return _error("Error interno del servidor", 500)
