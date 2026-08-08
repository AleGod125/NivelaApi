import random
import uuid
from typing import Any

from services.billing_service import get_xp_multiplier
from services.exercise_service import (
    check_exercise_answer,
    get_user_exercise_context,
    list_published_exercises_for_difficulty,
)
from services.progress_service import (
    MODULES_PER_DIFFICULTY,
    SUPPORTED_DIFFICULTIES,
    XP_PER_CORRECT_ANSWER,
    add_user_xp,
    complete_module,
    get_module_progress,
)


_sessions: dict[str, dict[str, Any]] = {}


class TrainingServiceError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _session_response(session: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": session["id"],
        "difficulty": session["difficulty"],
        "module": session["module"],
        "target_correct_answers": session["target_correct_answers"],
        "correct_answers": session["correct_answers"],
    }


def _summary(session: dict[str, Any]) -> dict[str, int]:
    return {
        "correct_answers": session["correct_answers"],
        "incorrect_answers": session["incorrect_answers"],
        "total_attempts": session["total_attempts"],
    }


def _public_exercise(exercise: dict[str, Any]) -> dict[str, Any]:
    return {
        key: exercise.get(key)
        for key in (
            "id",
            "career",
            "specialty",
            "category",
            "difficulty",
            "type",
            "title",
            "statement",
            "content",
        )
    }


def _get_session_for_user(session_id: str, user_id: str) -> dict[str, Any]:
    session = _sessions.get(session_id)
    if not session or session["user_id"] != user_id:
        raise TrainingServiceError("Sesion no encontrada", 404)
    return session


def _available_exercises(user_id: str, difficulty: int) -> list[dict[str, Any]]:
    data = list_published_exercises_for_difficulty(user_id, difficulty)
    return data["exercises"]


def _pick_random_exercise(session: dict[str, Any]) -> dict[str, Any] | None:
    exercises = _available_exercises(session["user_id"], session["difficulty"])
    if not exercises:
        return None

    seen_ids = set(session["seen_exercise_ids"])
    unseen = [exercise for exercise in exercises if exercise.get("id") not in seen_ids]
    pool = unseen or exercises

    if len(pool) > 1 and session.get("last_exercise_id") is not None:
        without_last = [
            exercise
            for exercise in pool
            if exercise.get("id") != session["last_exercise_id"]
        ]
        if without_last:
            pool = without_last

    exercise = random.choice(pool)
    exercise_id = exercise.get("id")
    if exercise_id is not None:
        session["seen_exercise_ids"].add(exercise_id)
        session["last_exercise_id"] = exercise_id
        session["awaiting_answer"] = True

    return _public_exercise(exercise)


def start_training_session(user_id: str, difficulty: int, module_number: int) -> dict[str, Any]:
    if difficulty not in SUPPORTED_DIFFICULTIES:
        raise TrainingServiceError("Difficulty invalida", 400)
    if not 1 <= module_number <= MODULES_PER_DIFFICULTY:
        raise TrainingServiceError("Modulo invalido", 400)

    context = get_user_exercise_context(user_id)
    module_progress = get_module_progress(
        user_id,
        context["career_id"],
        context["specialty_id"],
        difficulty,
        module_number,
    )
    if not module_progress:
        raise TrainingServiceError("Modulo no encontrado", 404)
    if module_progress.get("status") == "locked":
        raise TrainingServiceError("Modulo bloqueado", 403)

    exercises = _available_exercises(user_id, difficulty)
    if not exercises:
        raise TrainingServiceError("No hay ejercicios publicados para este modulo", 404)

    session = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "career": context["career_id"],
        "specialty": context["specialty_id"],
        "difficulty": difficulty,
        "module": module_number,
        "target_correct_answers": module_progress["target_correct_answers"],
        "correct_answers": 0,
        "incorrect_answers": 0,
        "total_attempts": 0,
        "seen_exercise_ids": set(),
        "last_exercise_id": None,
        "awaiting_answer": False,
        "completed": False,
    }
    _sessions[session["id"]] = session

    exercise = _pick_random_exercise(session)
    return {
        "session": _session_response(session),
        "exercise": exercise,
    }


def get_next_exercise(user_id: str, session_id: str) -> dict[str, Any]:
    session = _get_session_for_user(session_id, user_id)
    if session["completed"] or session["correct_answers"] >= session["target_correct_answers"]:
        session["completed"] = True
        return {
            "completed": True,
            "progress": {
                "correct_answers": session["correct_answers"],
                "target_correct_answers": session["target_correct_answers"],
            },
            "summary": _summary(session),
        }

    exercise = _pick_random_exercise(session)
    if not exercise:
        raise TrainingServiceError("No hay ejercicios publicados para este modulo", 404)

    return {
        "completed": False,
        "progress": {
            "correct_answers": session["correct_answers"],
            "target_correct_answers": session["target_correct_answers"],
        },
        "exercise": exercise,
    }


def answer_training_exercise(
    user_id: str,
    session_id: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    session = _get_session_for_user(session_id, user_id)
    if session["completed"]:
        return {
            "correct": False,
            "progress": {
                "correct_answers": session["correct_answers"],
                "target_correct_answers": session["target_correct_answers"],
            },
            "completed": True,
            "summary": _summary(session),
        }

    exercise_id = body.get("exercise_id")
    if not exercise_id:
        raise TrainingServiceError("exercise_id es requerido", 400)
    if not session.get("awaiting_answer"):
        raise TrainingServiceError("La pregunta actual ya fue respondida", 409)
    if exercise_id != session.get("last_exercise_id"):
        raise TrainingServiceError("El ejercicio no corresponde a la pregunta actual", 409)

    result = check_exercise_answer(
        user_id,
        exercise_id,
        body,
        expected_difficulty=session["difficulty"],
    )
    if not result:
        raise TrainingServiceError("Ejercicio no encontrado", 404)

    session["awaiting_answer"] = False
    session["total_attempts"] += 1
    base_xp = 0
    xp_earned = 0
    total_xp = add_user_xp(user_id, 0)
    xp_multiplier = get_xp_multiplier(user_id)

    if result["correct"]:
        session["correct_answers"] += 1
        base_xp += XP_PER_CORRECT_ANSWER
        previous_total_xp = total_xp
        total_xp = add_user_xp(user_id, XP_PER_CORRECT_ANSWER)
        xp_earned += total_xp - previous_total_xp
    else:
        session["incorrect_answers"] += 1

    completed = session["correct_answers"] >= session["target_correct_answers"]
    session["completed"] = completed

    if completed and result["correct"]:
        base_xp += 50
        module_result = complete_module(
            user_id,
            session["career"],
            session["specialty"],
            session["difficulty"],
            session["module"],
            session["correct_answers"],
            session["total_attempts"],
        )
        xp_earned += module_result["xp_earned"]
        total_xp = module_result["total_xp"]

    response = {
        "correct": result["correct"],
        "base_xp": base_xp,
        "xp_multiplier": xp_multiplier,
        "xp_earned": xp_earned,
        "total_xp": total_xp,
        "progress": {
            "correct_answers": session["correct_answers"],
            "target_correct_answers": session["target_correct_answers"],
        },
        "explanation": result.get("explanation"),
        "completed": completed,
    }

    if completed:
        response["summary"] = _summary(session)

    return response


def reset_training_sessions() -> None:
    _sessions.clear()
