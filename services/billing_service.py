import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any

import requests
from postgrest.exceptions import APIError

from config.supabase import get_supabase_admin_client
from services.user_service import get_profile_by_id


logger = logging.getLogger(__name__)

PLAN_NORMAL = "normal"
PLAN_PLUS = "plus"
PROVIDER_MERCADO_PAGO = "mercado_pago"
NORMAL_XP_MULTIPLIER = 1
PLUS_XP_MULTIPLIER = 2
ACTIVE_PROVIDER_STATUSES = {"authorized", "active"}
INACTIVE_PROVIDER_STATUSES = {"cancelled", "paused", "finished", "inactive"}

SUBSCRIPTION_FIELDS = (
    "id, user_id, provider, provider_subscription_id, plan, status, "
    "created_at, updated_at, current_period_end"
)


class BillingServiceError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_row(response: Any) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _db():
    return get_supabase_admin_client()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise BillingServiceError(f"Variable de entorno requerida no configurada: {name}", 500)
    return value


def get_plan_benefits(plan: str | None) -> dict[str, Any]:
    active_plan = PLAN_PLUS if plan == PLAN_PLUS else PLAN_NORMAL
    is_plus = active_plan == PLAN_PLUS
    return {
        "plan": active_plan,
        "is_plus": is_plus,
        "benefits": {
            "unlimited_lives": is_plus,
            "xp_multiplier": PLUS_XP_MULTIPLIER if is_plus else NORMAL_XP_MULTIPLIER,
            "plus_badge": is_plus,
            "future_premium_features": is_plus,
            "future_ai_priority": is_plus,
        },
    }


def get_user_billing_status(user_id: str) -> dict[str, Any]:
    profile = get_profile_by_id(user_id)
    if not profile:
        raise BillingServiceError("Usuario no encontrado", 404)
    status = get_plan_benefits(profile.get("plan"))
    status["total_xp"] = profile.get("total_xp", 0)
    return status


def get_xp_multiplier(user_id: str) -> int:
    profile = get_profile_by_id(user_id)
    if not profile:
        raise BillingServiceError("Usuario no encontrado", 404)
    return PLUS_XP_MULTIPLIER if profile.get("plan") == PLAN_PLUS else NORMAL_XP_MULTIPLIER


def has_unlimited_lives(user_id: str) -> bool:
    return get_xp_multiplier(user_id) == PLUS_XP_MULTIPLIER


def _mp_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_required_env('MERCADO_PAGO_ACCESS_TOKEN')}",
        "Content-Type": "application/json",
    }


def _mp_request(method: str, path: str, **kwargs):
    url = f"https://api.mercadopago.com{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=_mp_headers(),
            timeout=20,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.exception("ERROR mercado_pago_request: %r", exc)
        raise BillingServiceError("Error al comunicarse con Mercado Pago", 502) from exc

    if response.status_code >= 400:
        logger.error("MERCADO PAGO API ERROR status=%s body=%s", response.status_code, response.text[:500])
        raise BillingServiceError("Mercado Pago rechazo la operacion", 502)

    return response.json() if response.content else {}


def _update_user_plan(user_id: str, plan: str) -> None:
    try:
        (
            _db()
            .table("profiles")
            .update({"plan": plan, "updated_at": _now()})
            .eq("id", user_id)
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR update_user_plan: %r", exc)
        raise BillingServiceError("Error al actualizar plan", 500) from exc


def _upsert_subscription(
    user_id: str,
    provider_subscription_id: str,
    status: str,
    current_period_end: str | None = None,
) -> None:
    payload = {
        "user_id": user_id,
        "provider": PROVIDER_MERCADO_PAGO,
        "provider_subscription_id": provider_subscription_id,
        "plan": PLAN_PLUS,
        "status": status,
        "current_period_end": current_period_end,
        "updated_at": _now(),
    }

    try:
        existing = (
            _db()
            .table("user_subscriptions")
            .select("id")
            .eq("provider", PROVIDER_MERCADO_PAGO)
            .eq("provider_subscription_id", provider_subscription_id)
            .limit(1)
            .execute()
        )

        current = _first_row(existing)
        if current:
            (
                _db()
                .table("user_subscriptions")
                .update(payload)
                .eq("id", current["id"])
                .execute()
            )
        else:
            _db().table("user_subscriptions").insert(payload).execute()
    except APIError as exc:
        logger.error("SUPABASE API ERROR upsert_subscription: %r", exc)
        raise BillingServiceError("Error al guardar suscripcion", 500) from exc


def _get_latest_user_subscription(user_id: str) -> dict[str, Any] | None:
    try:
        response = (
            _db()
            .table("user_subscriptions")
            .select(SUBSCRIPTION_FIELDS)
            .eq("user_id", user_id)
            .eq("provider", PROVIDER_MERCADO_PAGO)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        return _first_row(response)
    except APIError as exc:
        logger.error("SUPABASE API ERROR latest_subscription: %r", exc)
        raise BillingServiceError("Error al obtener suscripcion", 500) from exc


def create_plus_subscription(user_id: str, email: str | None) -> dict[str, Any]:
    if not email:
        raise BillingServiceError("El usuario autenticado no tiene email disponible", 400)

    frontend_url = _required_env("FRONTEND_URL").rstrip("/")
    payload = {
        "reason": "Nivela Plus",
        "preapproval_plan_id": _required_env("MERCADO_PAGO_PLUS_PLAN_ID"),
        "payer_email": email,
        "external_reference": user_id,
        "back_url": f"{frontend_url}/billing",
        "status": "pending",
    }

    subscription = _mp_request("POST", "/preapproval", json=payload)
    provider_id = subscription.get("id")
    checkout_url = subscription.get("init_point") or subscription.get("sandbox_init_point")
    if not provider_id or not checkout_url:
        raise BillingServiceError("Mercado Pago no devolvio una suscripcion valida", 502)

    _upsert_subscription(user_id, provider_id, "pending")

    return {
        "checkout_url": checkout_url,
        "provider": PROVIDER_MERCADO_PAGO,
        "subscription_id": provider_id,
    }


def get_provider_subscription(provider_subscription_id: str) -> dict[str, Any]:
    return _mp_request("GET", f"/preapproval/{provider_subscription_id}")


def _subscription_user_id(subscription: dict[str, Any]) -> str | None:
    return subscription.get("external_reference")


def _subscription_status(subscription: dict[str, Any]) -> str:
    status = subscription.get("status")
    if status in ACTIVE_PROVIDER_STATUSES:
        return "active"
    if status in INACTIVE_PROVIDER_STATUSES:
        return "cancelled" if status == "cancelled" else "paused"
    return "pending"


def sync_subscription_from_provider(provider_subscription_id: str) -> dict[str, Any]:
    subscription = get_provider_subscription(provider_subscription_id)
    user_id = _subscription_user_id(subscription)
    if not user_id:
        raise BillingServiceError("La suscripcion no tiene usuario asociado", 400)

    local_status = _subscription_status(subscription)
    current_period_end = subscription.get("next_payment_date") or subscription.get("date_modified")
    _upsert_subscription(user_id, provider_subscription_id, local_status, current_period_end)

    if local_status == "active":
        _update_user_plan(user_id, PLAN_PLUS)
    elif local_status in {"paused", "cancelled"}:
        _update_user_plan(user_id, PLAN_NORMAL)

    return {
        "user_id": user_id,
        "plan": PLAN_PLUS if local_status == "active" else PLAN_NORMAL,
        "status": local_status,
    }


def cancel_user_subscription(user_id: str) -> dict[str, Any]:
    subscription = _get_latest_user_subscription(user_id)
    if not subscription or not subscription.get("provider_subscription_id"):
        raise BillingServiceError("No hay suscripcion para cancelar", 404)

    provider_id = subscription["provider_subscription_id"]
    _mp_request("PUT", f"/preapproval/{provider_id}", json={"status": "cancelled"})
    return sync_subscription_from_provider(provider_id)


def validate_webhook_signature(x_signature: str | None, x_request_id: str | None, data_id: str | None) -> bool:
    secret = os.getenv("MERCADO_PAGO_WEBHOOK_SECRET")
    if not secret:
        logger.warning("MERCADO_PAGO_WEBHOOK_SECRET no configurado; webhook rechazado")
        return False
    if not x_signature or not x_request_id or not data_id:
        return False

    parts = {}
    for part in x_signature.split(","):
        key_value = part.split("=", 1)
        if len(key_value) == 2:
            parts[key_value[0].strip()] = key_value[1].strip()

    timestamp = parts.get("ts")
    received_hash = parts.get("v1")
    if not timestamp or not received_hash:
        return False

    manifest = f"id:{data_id};request-id:{x_request_id};ts:{timestamp};"
    expected_hash = hmac.new(
        secret.encode(),
        msg=manifest.encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_hash, received_hash)


def process_webhook(headers: dict[str, str], query_args: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    data_id = query_args.get("data.id") or query_args.get("id") or (body.get("data") or {}).get("id")
    if not validate_webhook_signature(
        headers.get("x-signature"),
        headers.get("x-request-id"),
        str(data_id) if data_id is not None else None,
    ):
        raise BillingServiceError("Webhook no autorizado", 401)

    provider_subscription_id = str(data_id) if data_id is not None else None
    if not provider_subscription_id:
        raise BillingServiceError("Webhook sin id de suscripcion", 400)

    return sync_subscription_from_provider(provider_subscription_id)
