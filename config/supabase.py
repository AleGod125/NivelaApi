import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


supabase_auth: Client = create_client(
    _required_env("SUPABASE_URL"),
    _required_env("SUPABASE_KEY"),
)

# Backwards-compatible name for code that validates Supabase Auth tokens.
supabase = supabase_auth


@lru_cache(maxsize=1)
def get_supabase_admin_client() -> Client:
    return create_client(
        _required_env("SUPABASE_URL"),
        _required_env("SUPABASE_SERVICE_ROLE_KEY"),
    )
