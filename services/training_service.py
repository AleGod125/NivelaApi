import random
import uuid
from typing import Any

from services.exercise_service import (
    ExerciseServiceError,
    check_exercise_answer,
    get_difficulty_label,
    get_user_exercise_context,
    list_published_exercises_for_difficulty,
)


SUPPORTED_DIFFICULTIES = [1, 3, 5]
MODULES_PER_DIFFICULTY = 10
MODULE_TARGETS = [10, 10, 12, 12, 14, 14, 16, 16, 18, 20]
MIN_EXERCISES_FOR_NORMAL_TARGET = 10

_sessions: dict[str, dict[str, Any]] = {}


class TrainingServiceError(Exception):
    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _normal_target_for_module(module_number: int) -> int:
    if 1 <= module_number <= len(MODULE_TARGETS):
        return MODULE_TARGETS[module_number - 1]
    return MODULE_TARGETS[-1]


def _target_for_module(module_number: int, available_exercises: int) -> int:
    if available_exercises <= 0:
        return 0
    if available_exercises < MIN_EXERCISES_FOR_NORMAL_TARGET:
        return available_exercises
    return _normal_target_for_module(module_number)


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

    return _public_exercise(exercise)


def build_learning_map(user_id: str) -> dict[str, Any]:
    context = get_user_exercise_context(user_id)
    levels = []

    for difficulty in SUPPORTED_DIFFICULTIES:
        exercises = _available_exercises(user_id, difficulty)
        available_count = len(exercises)
        modules = []

        for module_number in range(1, MODULES_PER_DIFFICULTY + 1):
            modules.append(
                {
                    "module": module_number,
                    "target_correct_answers": _target_for_module(module_number, available_count),
                    "status": (
                        "available"
                        if difficulty == SUPPORTED_DIFFICULTIES[0] and module_number == 1
                        else "locked"
                    ),
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
        "levels": levels,
    }


def start_training_session(user_id: str, difficulty: int, module_number: int) -> dict[str, Any]:
    if difficulty not in SUPPORTED_DIFFICULTIES:
        raise TrainingServiceError("Difficulty invalida", 400)
    if not 1 <= module_number <= MODULES_PER_DIFFICULTY:
        raise TrainingServiceError("Modulo invalido", 400)

    exercises = _available_exercises(user_id, difficulty)
    if not exercises:
        raise TrainingServiceError("No hay ejercicios publicados para este modulo", 404)

    session = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "difficulty": difficulty,
        "module": module_number,
        "target_correct_answers": _target_for_module(module_number, len(exercises)),
        "correct_answers": 0,
        "incorrect_answers": 0,
        "total_attempts": 0,
        "seen_exercise_ids": set(),
        "last_exercise_id": None,
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

    session["total_attempts"] += 1
    if result["correct"]:
        session["correct_answers"] += 1
    else:
        session["incorrect_answers"] += 1

    completed = session["correct_answers"] >= session["target_correct_answers"]
    session["completed"] = completed

    response = {
        "correct": result["correct"],
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
