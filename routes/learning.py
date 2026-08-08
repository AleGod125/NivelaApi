import logging

from flask import Blueprint, jsonify

from routes.users import _current_supabase_user_id
from services.exercise_service import ExerciseServiceError
from services.progress_service import ProgressServiceError, build_learning_map


learning_bp = Blueprint("learning", __name__, url_prefix="/api")
logger = logging.getLogger(__name__)


def _error(message: str, status_code: int):
    return jsonify({"success": False, "error": message}), status_code


@learning_bp.get("/learning-map")
def learning_map():
    auth_user_id, auth_error = _current_supabase_user_id()
    if auth_error:
        return auth_error

    try:
        data = build_learning_map(auth_user_id)
        return jsonify({"success": True, **data}), 200
    except (ExerciseServiceError, ProgressServiceError) as exc:
        return _error(exc.message, exc.status_code)
    except Exception as exc:
        logger.exception("ERROR learning_map: %r", exc)
        return _error("Error interno del servidor", 500)
