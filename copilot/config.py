"""Settings from `.env` (see `.env.example`)."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str
    model: str
    fallback_model: str
    db_path: Path


@lru_cache
def get_settings() -> Settings:
    """Load `.env` once. A relative DB_PATH is relative to the repo root."""
    load_dotenv(ROOT / ".env")
    db_path = Path(os.getenv("DB_PATH") or "data/copilot.db")
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
        model=os.getenv("MODEL", "google/gemma-4-26b-a4b-it:free"),
        fallback_model=os.getenv("FALLBACK_MODEL", "google/gemma-4-31b-it:free"),
        db_path=db_path if db_path.is_absolute() else ROOT / db_path,
    )
