import logging
from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from config.supabase import get_supabase_admin_client
from services.billing_service import get_xp_multiplier
from services.exercise_service import get_difficulty_label, get_user_exercise_context
from services.user_service import get_profile_by_id


logger = logging.getLogger(__name__)

SUPPORTED_DIFFICULTIES = [1, 3, 5]
MODULES_PER_DIFFICULTY = 10
DEFAULT_TARGET_CORRECT_ANSWERS = 10
XP_PER_CORRECT_ANSWER = 5
XP_MODULE_COMPLETION = 50

PROGRESS_FIELDS = (
    "id, user_id, career, specialty, difficulty, module_number, status, "
    "target_correct_answers, best_correct_answers, total_attempts, "
    "completed_at, created_at, updated_at"
)


class ProgressServiceError(Exception):
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


def _safe_api_error(exc: APIError) -> dict[str, Any]:
    return {
        "code": getattr(exc, "code", None),
        "message": getattr(exc, "message", str(exc)),
        "details": getattr(exc, "details", None),
        "hint": getattr(exc, "hint", None),
    }


def _db():
    return get_supabase_admin_client()


def _difficulty_index(difficulty: int) -> int:
    try:
        return SUPPORTED_DIFFICULTIES.index(difficulty)
    except ValueError as exc:
        raise ProgressServiceError("Difficulty invalida", 400) from exc


def ensure_user_progress(user_id: str, career: str, specialty: str) -> None:
    try:
        existing = (
            _db()
            .table("user_module_progress")
            .select("id")
            .eq("user_id", user_id)
            .eq("career", career)
            .eq("specialty", specialty)
            .limit(1)
            .execute()
        )
        if existing.data:
            return

        rows = []
        for difficulty in SUPPORTED_DIFFICULTIES:
            for module_number in range(1, MODULES_PER_DIFFICULTY + 1):
                rows.append(
                    {
                        "user_id": user_id,
                        "career": career,
                        "specialty": specialty,
                        "difficulty": difficulty,
                        "module_number": module_number,
                        "status": (
                            "available"
                            if difficulty == SUPPORTED_DIFFICULTIES[0] and module_number == 1
                            else "locked"
                        ),
                        "target_correct_answers": DEFAULT_TARGET_CORRECT_ANSWERS,
                        "best_correct_answers": 0,
                        "total_attempts": 0,
                    }
                )

        _db().table("user_module_progress").insert(rows).execute()
    except APIError as exc:
        logger.error("SUPABASE API ERROR ensure_user_progress: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al inicializar progreso", 500) from exc


def get_user_progress_rows(user_id: str, career: str, specialty: str) -> list[dict[str, Any]]:
    ensure_user_progress(user_id, career, specialty)
    try:
        response = (
            _db()
            .table("user_module_progress")
            .select(PROGRESS_FIELDS)
            .eq("user_id", user_id)
            .eq("career", career)
            .eq("specialty", specialty)
            .order("difficulty")
            .order("module_number")
            .execute()
        )
        return response.data or []
    except APIError as exc:
        logger.error("SUPABASE API ERROR get_user_progress_rows: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al obtener progreso", 500) from exc


def get_module_progress(
    user_id: str,
    career: str,
    specialty: str,
    difficulty: int,
    module_number: int,
) -> dict[str, Any] | None:
    ensure_user_progress(user_id, career, specialty)
    try:
        response = (
            _db()
            .table("user_module_progress")
            .select(PROGRESS_FIELDS)
            .eq("user_id", user_id)
            .eq("career", career)
            .eq("specialty", specialty)
            .eq("difficulty", difficulty)
            .eq("module_number", module_number)
            .limit(1)
            .execute()
        )
        return _first_row(response)
    except APIError as exc:
        logger.error("SUPABASE API ERROR get_module_progress: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al obtener progreso del modulo", 500) from exc


def build_learning_map(user_id: str) -> dict[str, Any]:
    context = get_user_exercise_context(user_id)
    profile = get_profile_by_id(user_id)
    rows = get_user_progress_rows(user_id, context["career_id"], context["specialty_id"])

    rows_by_difficulty: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_difficulty.setdefault(int(row["difficulty"]), []).append(row)

    levels = []
    for difficulty in SUPPORTED_DIFFICULTIES:
        modules = []
        for row in sorted(rows_by_difficulty.get(difficulty, []), key=lambda item: item["module_number"]):
            modules.append(
                {
                    "module": row["module_number"],
                    "status": row["status"],
                    "target_correct_answers": row["target_correct_answers"],
                    "best_correct_answers": row.get("best_correct_answers", 0),
                    "total_attempts": row.get("total_attempts", 0),
                    "completed_at": row.get("completed_at"),
                }
            )

        levels.append(
            {
                "difficulty": difficulty,
                "name": get_difficulty_label(difficulty),
                "modules": modules,
            }
        )

    return {
        "career": context["career"],
        "specialization": context["specialization"],
        "total_xp": (profile or {}).get("total_xp", 0),
        "levels": levels,
    }


def add_user_xp(user_id: str, amount: int) -> int:
    if amount <= 0:
        profile = get_profile_by_id(user_id)
        return (profile or {}).get("total_xp", 0)

    profile = get_profile_by_id(user_id)
    if not profile:
        raise ProgressServiceError("Usuario no encontrado", 404)

    current_xp = profile.get("total_xp") or 0
    multiplier = get_xp_multiplier(user_id)
    earned_xp = amount * multiplier
    new_total = current_xp + earned_xp

    try:
        response = (
            _db()
            .table("profiles")
            .update({"total_xp": new_total, "updated_at": _now()})
            .eq("id", user_id)
            .select("total_xp")
            .execute()
        )
        updated = _first_row(response)
        return (updated or {}).get("total_xp", new_total)
    except APIError as exc:
        logger.error("SUPABASE API ERROR add_user_xp: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al sumar XP", 500) from exc


def _unlock_module(
    user_id: str,
    career: str,
    specialty: str,
    difficulty: int,
    module_number: int,
) -> None:
    try:
        current = get_module_progress(user_id, career, specialty, difficulty, module_number)
        if not current or current.get("status") != "locked":
            return

        (
            _db()
            .table("user_module_progress")
            .update({"status": "available", "updated_at": _now()})
            .eq("id", current["id"])
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR unlock_module: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al desbloquear modulo", 500) from exc


def _unlock_next_module(
    user_id: str,
    career: str,
    specialty: str,
    difficulty: int,
    module_number: int,
) -> None:
    if module_number < MODULES_PER_DIFFICULTY:
        _unlock_module(user_id, career, specialty, difficulty, module_number + 1)
        return

    difficulty_position = _difficulty_index(difficulty)
    if difficulty_position + 1 < len(SUPPORTED_DIFFICULTIES):
        next_difficulty = SUPPORTED_DIFFICULTIES[difficulty_position + 1]
        _unlock_module(user_id, career, specialty, next_difficulty, 1)


def complete_module(
    user_id: str,
    career: str,
    specialty: str,
    difficulty: int,
    module_number: int,
    correct_answers: int,
    total_attempts: int,
) -> dict[str, Any]:
    module_progress = get_module_progress(user_id, career, specialty, difficulty, module_number)
    if not module_progress:
        raise ProgressServiceError("Modulo no encontrado", 404)

    first_completion = module_progress.get("status") != "completed"
    best_correct_answers = max(
        module_progress.get("best_correct_answers") or 0,
        correct_answers,
    )
    accumulated_attempts = (module_progress.get("total_attempts") or 0) + total_attempts

    update_payload = {
        "status": "completed",
        "best_correct_answers": best_correct_answers,
        "total_attempts": accumulated_attempts,
        "updated_at": _now(),
    }
    if first_completion:
        update_payload["completed_at"] = _now()

    try:
        (
            _db()
            .table("user_module_progress")
            .update(update_payload)
            .eq("id", module_progress["id"])
            .execute()
        )
    except APIError as exc:
        logger.error("SUPABASE API ERROR complete_module: %s", _safe_api_error(exc))
        raise ProgressServiceError("Error al completar modulo", 500) from exc

    if first_completion:
        _unlock_next_module(user_id, career, specialty, difficulty, module_number)
        total_xp = add_user_xp(user_id, XP_MODULE_COMPLETION)
        completion_xp = XP_MODULE_COMPLETION * get_xp_multiplier(user_id)
    else:
        profile = get_profile_by_id(user_id)
        total_xp = (profile or {}).get("total_xp", 0)
        completion_xp = 0

    return {
        "first_completion": first_completion,
        "xp_earned": completion_xp,
        "total_xp": total_xp,
    }
