from typing import Any

from postgrest.exceptions import APIError
from supabase import Client

from config.supabase import supabase


PROFILE_FIELDS = "id, username, full_name, avatar_url, created_at, updated_at"


class UserServiceError(Exception):
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


def get_profiles(client: Client | None = None) -> list[dict[str, Any]]:
    db = client or supabase
    response = (
        db.table("profiles")
        .select(PROFILE_FIELDS)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def get_profile_by_id(user_id: str, client: Client | None = None) -> dict[str, Any] | None:
    db = client or supabase
    response = (
        db.table("profiles")
        .select(PROFILE_FIELDS)
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return _first_row(response)


def create_profile_if_missing(
    profile: dict[str, Any],
    client: Client | None = None,
) -> tuple[dict[str, Any], bool]:
    db = client or supabase
    existing_profile = get_profile_by_id(profile["id"], db)
    if existing_profile:
        return existing_profile, False

    payload = {
        "id": profile["id"],
        "username": profile.get("username"),
        "full_name": profile.get("full_name"),
        "avatar_url": profile.get("avatar_url"),
    }

    try:
        response = (
            supabase.table("profiles")
            .insert(payload)
            .select(PROFILE_FIELDS)
            .execute()
        )

        created_profile = _first_row(response)

        if not created_profile:
            raise UserServiceError("No se pudo crear el perfil")

        return created_profile, True

    except APIError as exc:
        print("SUPABASE API ERROR:", repr(exc))
        print("SUPABASE API ERROR MESSAGE:", str(exc))

        existing_profile = get_profile_by_id(profile["id"])

        if existing_profile:
            return existing_profile, False

        message = str(exc)

        if "duplicate" in message.lower() or "unique" in message.lower():
            raise UserServiceError(
                "El username ya esta en uso o el perfil genera un conflicto",
                409,
            ) from exc

        raise UserServiceError(
            "Error al crear el perfil",
            500
        ) from exc