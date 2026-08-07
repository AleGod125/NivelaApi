import logging
from typing import Any

from flask import Blueprint, jsonify, request

from routes.users import _current_supabase_user_id
from services.exercise_service import (
    ExerciseServiceError,
    check_exercise_answer,
    get_exercise_catalog,
    get_exercise_for_user,
    list_exercises,
)


exercises_bp = Blueprint("exercises", __name__, url_prefix="/api/exercises")
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


def _json_body() -> dict[str, Any] | None:
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def _validate_exercise_id(value: str | None) -> bool:
    return bool(value and len(value) <= 120)


def _current_user_or_error():
    auth_user_id, auth_error = _current_supabase_user_id()
    if auth_error:
        return None, auth_error
    return auth_user_id, None


def _parse_filters() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    filters: dict[str, Any] = {
        "difficulty": None,
        "category": None,
        "type": None,
    }

    difficulty = request.args.get("difficulty")
    if difficulty is not None:
        try:
            filters["difficulty"] = int(difficulty)
        except ValueError:
            return None, _error("Difficulty invalida", 400)

    category = request.args.get("category")
    if category is not None:
        if not category or len(category) > 120:
            return None, _error("Category invalida", 400)
        filters["category"] = category

    exercise_type = request.args.get("type")
    if exercise_type is not None:
        if not exercise_type or len(exercise_type) > 60:
            return None, _error("Type invalido", 400)
        filters["type"] = exercise_type

    return filters, None


@exercises_bp.get("/catalog")
def catalog():
    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    try:
        catalog_data = get_exercise_catalog(auth_user_id)
        return jsonify({"success": True, **catalog_data}), 200
    except ExerciseServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR exercises_catalog: %r", exc)
        return _error("Error interno del servidor", 500)


@exercises_bp.get("")
def index():
    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    filters, filter_error = _parse_filters()
    if filter_error:
        return filter_error

    try:
        exercises_data = list_exercises(auth_user_id, filters)
        return jsonify({"success": True, **exercises_data}), 200
    except ExerciseServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR list_exercises: %r", exc)
        return _error("Error interno del servidor", 500)


@exercises_bp.get("/<exercise_id>")
def show(exercise_id: str):
    if not _validate_exercise_id(exercise_id):
        return _error("ID de ejercicio invalido", 400)

    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    try:
        exercise = get_exercise_for_user(auth_user_id, exercise_id)
        if not exercise:
            return _error("Ejercicio no encontrado", 404)
        return jsonify({"success": True, "exercise": exercise}), 200
    except ExerciseServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR get_exercise: %r", exc)
        return _error("Error interno del servidor", 500)


@exercises_bp.post("/<exercise_id>/check")
def check(exercise_id: str):
    if not _validate_exercise_id(exercise_id):
        return _error("ID de ejercicio invalido", 400)

    auth_user_id, auth_error = _current_user_or_error()
    if auth_error:
        return auth_error

    body = _json_body()
    if body is None:
        return _error("El cuerpo de la solicitud debe ser JSON", 400)

    try:
        result = check_exercise_answer(auth_user_id, exercise_id, body)
        if not result:
            return _error("Ejercicio no encontrado", 404)
        return jsonify({"success": True, **result}), 200
    except ExerciseServiceError as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR check_exercise: %r", exc)
        return _error("Error interno del servidor", 500)
