"""
Firebase wiring.

Two separate things live here:

1. Firestore access through the Admin SDK (server side, uses the service
   account JSON you download from the Firebase console).
2. Email/password sign-in. The Admin SDK deliberately cannot check a password,
   so sign-in goes through Firebase's REST endpoint with your Web API key,
   which is the normal pattern for a Python client such as Streamlit.

If Firebase is not configured, LocalAuth takes over and keeps accounts in the
same JSON file as the rest of the local data. Passwords there are stored as a
salted PBKDF2 hash, never in plain text.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from typing import Any, Dict, Optional, Tuple

from .config import LOCAL_DB_PATH, Settings

_FIREBASE_APP = None
_SIGN_UP_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signUp"
_SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"


# --------------------------------------------------------------------------- #
# Firestore
# --------------------------------------------------------------------------- #
def init_firebase(settings: Settings):
    """Initialise firebase_admin once and return the Firestore client."""
    global _FIREBASE_APP
    import firebase_admin
    from firebase_admin import credentials, firestore

    if _FIREBASE_APP is None:
        if firebase_admin._apps:  # already initialised elsewhere in the process
            _FIREBASE_APP = firebase_admin.get_app()
        else:
            cred = credentials.Certificate(settings.firebase_credentials)
            options = {}
            if settings.firebase_project_id:
                options["projectId"] = settings.firebase_project_id
            _FIREBASE_APP = firebase_admin.initialize_app(cred, options or None)
    return firestore.client(_FIREBASE_APP)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class AuthError(Exception):
    pass


class FirebaseAuth:
    """Email/password auth against Firebase Authentication."""

    def __init__(self, settings: Settings):
        if not settings.firebase_web_api_key:
            raise AuthError("FIREBASE_WEB_API_KEY is not set.")
        self.api_key = settings.firebase_web_api_key

    def _post(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        import requests

        response = requests.post(
            url, params={"key": self.api_key}, json=payload, timeout=20
        )
        data = response.json()
        if response.status_code != 200:
            message = data.get("error", {}).get("message", "Sign-in failed.")
            raise AuthError(_friendly(message))
        return data

    def sign_up(self, email: str, password: str, name: str) -> Dict[str, str]:
        data = self._post(
            _SIGN_UP_URL,
            {"email": email, "password": password, "returnSecureToken": True},
        )
        return {"id": data["localId"], "email": email, "name": name or email.split("@")[0]}

    def sign_in(self, email: str, password: str) -> Dict[str, str]:
        data = self._post(
            _SIGN_IN_URL,
            {"email": email, "password": password, "returnSecureToken": True},
        )
        return {
            "id": data["localId"],
            "email": email,
            "name": data.get("displayName") or email.split("@")[0],
        }


class LocalAuth:
    """Offline stand-in for Firebase Authentication."""

    def __init__(self, path=LOCAL_DB_PATH):
        self.path = path

    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as fh:
            try:
                return json.load(fh)
            except json.JSONDecodeError:
                return {}

    def _write(self, blob: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, indent=2)

    def sign_up(self, email: str, password: str, name: str) -> Dict[str, str]:
        blob = self._read()
        users = blob.setdefault("auth_users", {})
        key = email.strip().lower()
        if key in users:
            raise AuthError("An account already exists for that email.")
        salt, digest = _hash_password(password)
        user_id = f"stu_{secrets.token_hex(5)}"
        users[key] = {
            "id": user_id,
            "email": key,
            "name": name or key.split("@")[0],
            "salt": salt,
            "hash": digest,
        }
        self._write(blob)
        return {"id": user_id, "email": key, "name": users[key]["name"]}

    def sign_in(self, email: str, password: str) -> Dict[str, str]:
        users = self._read().get("auth_users", {})
        record = users.get(email.strip().lower())
        if not record:
            raise AuthError("No account found for that email.")
        _, digest = _hash_password(password, record["salt"])
        if not secrets.compare_digest(digest, record["hash"]):
            raise AuthError("That password does not match.")
        return {"id": record["id"], "email": record["email"], "name": record["name"]}


def get_auth(settings: Settings):
    """Return whichever auth backend the current configuration supports."""
    if settings.use_firebase and settings.firebase_web_api_key:
        try:
            return FirebaseAuth(settings)
        except AuthError:
            pass
    return LocalAuth()


def _hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000
    ).hex()
    return salt, digest


def _friendly(code: str) -> str:
    return {
        "EMAIL_EXISTS": "An account already exists for that email.",
        "EMAIL_NOT_FOUND": "No account found for that email.",
        "INVALID_PASSWORD": "That password does not match.",
        "INVALID_LOGIN_CREDENTIALS": "Email or password is not correct.",
        "WEAK_PASSWORD : Password should be at least 6 characters": "Use at least 6 characters.",
    }.get(code, code.replace("_", " ").capitalize())
