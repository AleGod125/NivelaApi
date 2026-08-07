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
    update_profile,
)


users_bp = Blueprint("users", __name__, url_prefix="/api/users")
logger = logging.getLogger(__name__)
VALID_USER_TYPES = {"student", "professional", "specialized"}
PATCH_PROFILE_FIELDS = {
    "username",
    "full_name",
    "avatar_url",
    "user_type",
    "career",
    "specialization",
}
PROTECTED_PROFILE_FIELDS = {"id", "created_at"}


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


def _validate_nullable_string(value: Any, max_length: int, field_name: str):
    if value is not None and (not isinstance(value, str) or len(value) > max_length):
        return _error(f"{field_name} invalido", 400)
    return None


def _validate_profile_fields(body: dict[str, Any], partial: bool = False):
    if "username" in body or not partial:
        error = _validate_nullable_string(body.get("username"), 50, "Username")
        if error:
            return error

    if "full_name" in body or not partial:
        error = _validate_nullable_string(body.get("full_name"), 120, "Nombre completo")
        if error:
            return error

    if "avatar_url" in body or not partial:
        error = _validate_nullable_string(body.get("avatar_url"), 500, "URL de avatar")
        if error:
            return error

    if "user_type" in body or not partial:
        user_type = body.get("user_type")
        if user_type is not None and user_type not in VALID_USER_TYPES:
            return _error("Tipo de usuario invalido", 400)

    if "career" in body or not partial:
        error = _validate_nullable_string(body.get("career"), 120, "Career")
        if error:
            return error

    if "specialization" in body or not partial:
        error = _validate_nullable_string(body.get("specialization"), 120, "Specialization")
        if error:
            return error

    return None


def _patch_changes(body: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    protected_fields = PROTECTED_PROFILE_FIELDS.intersection(body)
    if protected_fields:
        return None, _error("No se permite modificar campos protegidos", 400)

    unknown_fields = set(body) - PATCH_PROFILE_FIELDS
    if unknown_fields:
        return None, _error("Campos no permitidos en el perfil", 400)

    if not body:
        return None, _error("No hay campos para actualizar", 400)

    validation_error = _validate_profile_fields(body, partial=True)
    if validation_error:
        return None, validation_error

    return {field: body[field] for field in PATCH_PROFILE_FIELDS if field in body}, None


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

    validation_error = _validate_profile_fields(body)
    if validation_error:
        return validation_error

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


@users_bp.patch("/me")
def update_my_profile():
    auth_user_id, _access_token, auth_error = _current_supabase_session()
    if auth_error:
        return auth_error

    body = _json_body()
    if body is None:
        return _error("El cuerpo de la solicitud debe ser JSON", 400)

    changes, validation_error = _patch_changes(body)
    if validation_error:
        return validation_error

    try:
        user = update_profile(auth_user_id, changes)
        if not user:
            return _error("Usuario no encontrado", 404)
        return jsonify({"success": True, "user": user}), 200
    except UserServiceError as exc:
        logger.warning("ERROR update_my_profile: %r", exc)
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR update_my_profile: %r", exc)
        return _error("Error interno del servidor", 500)
