import os

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


supabase: Client = create_client(
    _required_env("SUPABASE_URL"),
    _required_env("SUPABASE_KEY"),
)
