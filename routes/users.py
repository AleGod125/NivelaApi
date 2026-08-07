import uuid
import logging
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from config.supabase import supabase_auth
from services.user_service import (
    UserServiceError,
    create_profile_if_missing,
    get_profile_by_id,
    get_profiles,
)


users_bp = Blueprint("users", __name__, url_prefix="/api/users")
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


def _json_body() -> dict[str, Any] | None:
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def _validate_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _current_supabase_session() -> tuple[str | None, str | None, tuple[Any, int] | None]:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header:
        return None, None, _error("No autenticado", 401)

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None, None, _error("Token de autorizacion invalido", 401)

    try:
        response = supabase_auth.auth.get_user(token)
        user = getattr(response, "user", None)
        user_id = getattr(user, "id", None)
        if not user_id:
            return None, None, _error("Token de autorizacion invalido", 401)
        return user_id, token, None
    except Exception:
        return None, None, _error("Token de autorizacion invalido", 401)


def _current_supabase_user_id() -> tuple[str | None, tuple[Any, int] | None]:
    user_id, _token, error = _current_supabase_session()
    return user_id, error


def _admin_user_ids() -> set[str]:
    raw_ids = current_app.config.get("ADMIN_USER_IDS", "")
    return {user_id.strip() for user_id in raw_ids.split(",") if user_id.strip()}


def _is_admin(user_id: str) -> bool:
    return user_id in _admin_user_ids()


@users_bp.get("")
def list_users():
    auth_user_id, _access_token, auth_error = _current_supabase_session()
    if auth_error:
        return auth_error

    if not _is_admin(auth_user_id):
        return _error("No autorizado", 403)

    try:
        return jsonify({"success": True, "users": get_profiles()}), 200
    except Exception as exc:
        logger.exception("ERROR list_users: %r", exc)
        return _error("Error interno del servidor", 500)


@users_bp.get("/<user_id>")
def get_user(user_id: str):
    if not _validate_uuid(user_id):
        return _error("ID de usuario invalido", 400)

    auth_user_id, _access_token, auth_error = _current_supabase_session()
    if auth_error:
        return auth_error

    if user_id != auth_user_id and not _is_admin(auth_user_id):
        return _error("No autorizado", 403)

    try:
        user = get_profile_by_id(user_id)
        if not user:
            return _error("Usuario no encontrado", 404)
        return jsonify({"success": True, "user": user}), 200
    except Exception as exc:
        logger.exception("ERROR get_user: %r", exc)
        return _error("Error interno del servidor", 500)


@users_bp.post("")
def create_user_profile():
    auth_user_id, _access_token, auth_error = _current_supabase_session()
    if auth_error:
        return auth_error

    body = _json_body()
    if body is None:
        return _error("El cuerpo de la solicitud debe ser JSON", 400)

    requested_user_id = body.get("id")
    if not _validate_uuid(requested_user_id):
        return _error("ID de usuario invalido", 400)

    if requested_user_id != auth_user_id:
        return _error("No autorizado para modificar este usuario", 403)

    username = body.get("username")
    if username is not None and (not isinstance(username, str) or len(username) > 50):
        return _error("Username invalido", 400)

    full_name = body.get("full_name")
    if full_name is not None and (not isinstance(full_name, str) or len(full_name) > 120):
        return _error("Nombre completo invalido", 400)

    avatar_url = body.get("avatar_url")
    if avatar_url is not None and (not isinstance(avatar_url, str) or len(avatar_url) > 500):
        return _error("URL de avatar invalida", 400)

    try:
        user, created = create_profile_if_missing(body)
        status_code = 201 if created else 200
        return jsonify({"success": True, "created": created, "user": user}), status_code
    except UserServiceError as exc:
        logger.warning("ERROR create_user_profile: %r", exc)
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR create_user_profile: %r", exc)
        return _error("Error interno del servidor", 500)
