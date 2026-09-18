"""
Configuration for MistakeMind.

Everything is read from environment variables (or a .env file) so that no key
is ever written into the source. If a key is missing the app still runs:
 - no GEMINI_API_KEY  -> the offline rule-based analyser is used
 - no Firebase creds  -> data is stored in data/local_store.json

That fallback is what lets you demo the project on a laptop with no network.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:  # optional, only needed if you keep secrets in a .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOCAL_DB_PATH = DATA_DIR / "local_store.json"


@dataclass
class Settings:
    gemini_api_key: Optional[str]
    gemini_model: str
    firebase_credentials: Optional[str]  # path to serviceAccountKey.json
    firebase_project_id: Optional[str]
    firebase_web_api_key: Optional[str]  # needed for email/password sign-in
    force_local: bool

    @property
    def use_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def use_firebase(self) -> bool:
        if self.force_local:
            return False
        if not self.firebase_credentials:
            return False
        return Path(self.firebase_credentials).exists()

    def describe(self) -> str:
        ai = "Gemini API" if self.use_gemini else "offline rule-based analyser"
        db = "Firebase (Firestore)" if self.use_firebase else "local JSON store"
        return f"AI: {ai}  |  Database: {db}"


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
        firebase_credentials=os.getenv("FIREBASE_CREDENTIALS") or None,
        firebase_project_id=os.getenv("FIREBASE_PROJECT_ID") or None,
        firebase_web_api_key=os.getenv("FIREBASE_WEB_API_KEY") or None,
        force_local=_flag("MISTAKEMIND_LOCAL"),
    )
