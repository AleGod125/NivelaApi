import logging
import re
import unicodedata
from typing import Any

from postgrest.exceptions import APIError

from config.supabase import get_supabase_admin_client
from services.user_service import get_profile_by_id


logger = logging.getLogger(__name__)

PUBLIC_EXERCISE_FIELDS = (
    "id, career, specialty, category, difficulty, type, "
    "title, statement, content"
)
CHECK_EXERCISE_FIELDS = (
    "id, career, specialty, category, difficulty, type, "
    "title, statement, content, solution, explanation"
)
PUBLISHED_STATUS = "published"
DIFFICULTY_LABELS = {
    1: "Principiante",
    3: "Intermedio",
    5: "Avanzado",
}


class ExerciseServiceError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _first_row(response: Any) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        return data[0] if data else None
    if isinstance(data, dict):
        return data
    return None


def _safe_api_error(exc: APIError) -> dict[str, Any]:
    return {
        "code": getattr(exc, "code", None),
        "message": getattr(exc, "message", str(exc)),
        "details": getattr(exc, "details", None),
        "hint": getattr(exc, "hint", None),
    }


def normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_value.lower().strip()
    collapsed = re.sub(r"[^a-z0-9]+", "_", lowered)
    return collapsed.strip("_") or None


def get_difficulty_label(difficulty: int) -> str:
    return DIFFICULTY_LABELS.get(difficulty, f"Nivel {difficulty}")


def _category_name(category: str) -> str:
    return category.replace("_", " ").capitalize()


def _require_profile_context(user_id: str) -> dict[str, str]:
    profile = get_profile_by_id(user_id)
    if not profile:
        raise ExerciseServiceError("Usuario no encontrado", 404)

    career = profile.get("career")
    specialization = profile.get("specialization")
    if not career or not specialization:
        raise ExerciseServiceError("Perfil profesional incompleto", 409)

    normalized_career = normalize_identifier(career)
    normalized_specialty = normalize_identifier(specialization)
    if not normalized_career or not normalized_specialty:
        raise ExerciseServiceError("Perfil profesional incompleto", 409)

    return {
        "career": career,
        "specialization": specialization,
        "career_id": normalized_career,
        "specialty_id": normalized_specialty,
    }


def _base_query(fields: str, context: dict[str, str]):
    return (
        get_supabase_admin_client()
        .table("exercises")
        .select(fields)
        .eq("status", PUBLISHED_STATUS)
        .eq("career", context["career_id"])
        .eq("specialty", context["specialty_id"])
    )


def get_exercise_catalog(user_id: str) -> dict[str, Any]:
    context = _require_profile_context(user_id)

    try:
        response = (
            _base_query("id, category, difficulty", context)
            .order("difficulty")
            .order("category")
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR get_exercise_catalog: %s", _safe_api_error(exc))
        raise ExerciseServiceError("Error al obtener catalogo de ejercicios", 500) from exc

    levels_by_difficulty: dict[int, dict[str, Any]] = {}
    for row in response.data or []:
        difficulty = row.get("difficulty")
        category = row.get("category")
        if difficulty is None or category is None:
            continue

        level = levels_by_difficulty.setdefault(
            int(difficulty),
            {
                "difficulty": int(difficulty),
                "name": get_difficulty_label(int(difficulty)),
                "exercise_count": 0,
                "categories": {},
            },
        )
        level["exercise_count"] += 1

        category_data = level["categories"].setdefault(
            category,
            {
                "id": category,
                "name": _category_name(category),
                "exercise_count": 0,
            },
        )
        category_data["exercise_count"] += 1

    levels = []
    for difficulty in sorted(levels_by_difficulty):
        level = levels_by_difficulty[difficulty]
        categories = sorted(
            level["categories"].values(),
            key=lambda item: item["id"],
        )
        levels.append({**level, "categories": categories})

    return {
        "career": context["career"],
        "specialization": context["specialization"],
        "levels": levels,
    }


def list_exercises(user_id: str, filters: dict[str, Any]) -> dict[str, Any]:
    context = _require_profile_context(user_id)
    query = _base_query(PUBLIC_EXERCISE_FIELDS, context)

    if filters.get("difficulty") is not None:
        query = query.eq("difficulty", filters["difficulty"])
    if filters.get("category"):
        query = query.eq("category", normalize_identifier(filters["category"]))
    if filters.get("type"):
        query = query.eq("type", filters["type"])

    try:
        response = (
            query.order("difficulty")
            .order("category")
            .order("created_at")
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR list_exercises: %s", _safe_api_error(exc))
        raise ExerciseServiceError("Error al obtener ejercicios", 500) from exc

    return {
        "career": context["career"],
        "specialization": context["specialization"],
        "filters": filters,
        "exercises": response.data or [],
    }


def get_exercise_for_user(user_id: str, exercise_id: str, include_solution: bool = False) -> dict[str, Any] | None:
    context = _require_profile_context(user_id)
    fields = CHECK_EXERCISE_FIELDS if include_solution else PUBLIC_EXERCISE_FIELDS

    try:
        response = (
            _base_query(fields, context)
            .eq("id", exercise_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR get_exercise_for_user: %s", _safe_api_error(exc))
        raise ExerciseServiceError("Error al obtener ejercicio", 500) from exc

    return _first_row(response)


def _normalize_answer(value: Any) -> str:
    return str(value).strip().casefold()


def _check_numeric_answer(answer: Any, solution: dict[str, Any]) -> bool | None:
    if "correct_value" not in solution:
        return None

    try:
        expected = float(solution["correct_value"])
        received = float(answer)
        tolerance = float(solution.get("tolerance", 0))
    except (TypeError, ValueError):
        return False

    return abs(received - expected) <= tolerance


def _check_text_answer(answer: Any, solution: dict[str, Any]) -> bool:
    numeric_result = _check_numeric_answer(answer, solution)
    if numeric_result is not None:
        return numeric_result

    expected_answers = solution.get("expected_answers")
    if isinstance(expected_answers, list):
        received = _normalize_answer(answer)
        return any(received == _normalize_answer(expected) for expected in expected_answers)

    correct_answer = solution.get("correct_answer", solution.get("answer"))
    if correct_answer is None:
        return False
    return _normalize_answer(answer) == _normalize_answer(correct_answer)


def _check_matching_answer(matches: Any, solution: dict[str, Any]) -> bool:
    expected_matches = solution.get("matches")
    if not isinstance(matches, dict) or not isinstance(expected_matches, dict):
        return False

    normalized_matches = {str(key): str(value) for key, value in matches.items()}
    normalized_expected = {str(key): str(value) for key, value in expected_matches.items()}
    return normalized_matches == normalized_expected


def check_exercise_answer(user_id: str, exercise_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    exercise = get_exercise_for_user(user_id, exercise_id, include_solution=True)
    if not exercise:
        return None

    solution = exercise.get("solution") or {}
    exercise_type = exercise.get("type")

    if exercise_type == "matching":
        correct = _check_matching_answer(body.get("matches"), solution)
    elif exercise_type in {"multiple_choice", "case_study", "free_response"}:
        correct = _check_text_answer(body.get("answer"), solution)
    else:
        correct = False

    return {
        "correct": correct,
        "explanation": exercise.get("explanation"),
    }
