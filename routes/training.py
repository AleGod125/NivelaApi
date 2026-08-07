import logging
from typing import Any

from flask import Blueprint, jsonify, request

from routes.users import _current_supabase_user_id
from services.exercise_service import ExerciseServiceError
from services.training_service import (
    TrainingServiceError,
    answer_training_exercise,
    get_next_exercise,
    start_training_session,
)


training_bp = Blueprint("training", __name__, url_prefix="/api/training")
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


def _json_body() -> dict[str, Any] | None:
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def _current_user_or_error():
    auth_user_id, auth_error = _current_supabase_user_id()
    if auth_error:
        return None, auth_error
    return auth_user_id, None


def _parse_int(value: Any, field_name: str) -> tuple[int | None, tuple[Any, int] | None]:
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, _error(f"{field_name} invalido", 400)


@training_bp.post("/session")
def create_session():
    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    body = _json_body()
    if body is None:
        return _error("El cuerpo de la solicitud debe ser JSON", 400)

    difficulty, difficulty_error = _parse_int(body.get("difficulty"), "Difficulty")
    if difficulty_error:
        return difficulty_error

    module_number, module_error = _parse_int(body.get("module"), "Modulo")
    if module_error:
        return module_error

    try:
        data = start_training_session(auth_user_id, difficulty, module_number)
        return jsonify({"success": True, **data}), 201
    except (ExerciseServiceError, TrainingServiceError) as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR create_training_session: %r", exc)
        return _error("Error interno del servidor", 500)


@training_bp.get("/session/<session_id>/next")
def next_exercise(session_id: str):
    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    try:
        data = get_next_exercise(auth_user_id, session_id)
        return jsonify({"success": True, **data}), 200
    except (ExerciseServiceError, TrainingServiceError) as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR next_training_exercise: %r", exc)
        return _error("Error interno del servidor", 500)


@training_bp.post("/session/<session_id>/answer")
def answer_exercise(session_id: str):
    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    body = _json_body()
    if body is None:
        return _error("El cuerpo de la solicitud debe ser JSON", 400)

    try:
        data = answer_training_exercise(auth_user_id, session_id, body)
        return jsonify({"success": True, **data}), 200
    except (ExerciseServiceError, TrainingServiceError) as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR answer_training_exercise: %r", exc)
        return _error("Error interno del servidor", 500)
