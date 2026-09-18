"""
Storage layer.

Every read and write in the app goes through a Store, so the UI never touches
Firestore directly. Two implementations:

    FirestoreStore  -> students/{sid}/{tests|mistakes|practice|retests}
    LocalStore      -> data/local_store.json (same shape, no network)

Swapping between them is a config change, nothing else.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .config import LOCAL_DB_PATH, Settings
from .models import (
    Mistake,
    PracticeSet,
    RetestResult,
    Student,
    TestRecord,
)

COLLECTIONS = ("tests", "mistakes", "practice", "retests")


class Store:
    """Interface every storage backend implements."""

    # students -------------------------------------------------------------
    def save_student(self, student: Student) -> None: ...
    def get_student(self, student_id: str) -> Optional[Student]: ...

    # tests ----------------------------------------------------------------
    def save_test(self, test: TestRecord) -> None: ...
    def list_tests(self, student_id: str) -> List[TestRecord]: ...

    # mistakes -------------------------------------------------------------
    def save_mistake(self, mistake: Mistake) -> None: ...
    def list_mistakes(self, student_id: str) -> List[Mistake]: ...

    # practice -------------------------------------------------------------
    def save_practice(self, practice: PracticeSet) -> None: ...
    def list_practice(self, student_id: str) -> List[PracticeSet]: ...

    # retests --------------------------------------------------------------
    def save_retest(self, retest: RetestResult) -> None: ...
    def list_retests(self, student_id: str) -> List[RetestResult]: ...

    # housekeeping ---------------------------------------------------------
    def clear_student(self, student_id: str) -> None: ...


class FirestoreStore(Store):
    def __init__(self, client):
        self.db = client

    def _doc(self, student_id: str):
        return self.db.collection("students").document(student_id)

    def _col(self, student_id: str, name: str):
        return self._doc(student_id).collection(name)

    def save_student(self, student: Student) -> None:
        self._doc(student.id).set(student.to_dict(), merge=True)

    def get_student(self, student_id: str) -> Optional[Student]:
        snap = self._doc(student_id).get()
        return Student.from_dict(snap.to_dict()) if snap.exists else None

    def save_test(self, test: TestRecord) -> None:
        self._col(test.student_id, "tests").document(test.id).set(test.to_dict())

    def list_tests(self, student_id: str) -> List[TestRecord]:
        docs = self._col(student_id, "tests").stream()
        tests = [TestRecord.from_dict(d.to_dict()) for d in docs]
        return sorted(tests, key=lambda t: (t.taken_on, t.created_at))

    def save_mistake(self, mistake: Mistake) -> None:
        self._col(mistake.student_id, "mistakes").document(mistake.id).set(
            mistake.to_dict()
        )

    def list_mistakes(self, student_id: str) -> List[Mistake]:
        docs = self._col(student_id, "mistakes").stream()
        items = [Mistake.from_dict(d.to_dict()) for d in docs]
        return sorted(items, key=lambda m: (m.taken_on, m.created_at))

    def save_practice(self, practice: PracticeSet) -> None:
        self._col(practice.student_id, "practice").document(practice.id).set(
            practice.to_dict()
        )

    def list_practice(self, student_id: str) -> List[PracticeSet]:
        docs = self._col(student_id, "practice").stream()
        items = [PracticeSet.from_dict(d.to_dict()) for d in docs]
        return sorted(items, key=lambda p: p.created_at)

    def save_retest(self, retest: RetestResult) -> None:
        self._col(retest.student_id, "retests").document(retest.id).set(
            retest.to_dict()
        )

    def list_retests(self, student_id: str) -> List[RetestResult]:
        docs = self._col(student_id, "retests").stream()
        items = [RetestResult.from_dict(d.to_dict()) for d in docs]
        return sorted(items, key=lambda r: r.created_at)

    def clear_student(self, student_id: str) -> None:
        for name in COLLECTIONS:
            for doc in self._col(student_id, name).stream():
                doc.reference.delete()


class LocalStore(Store):
    """JSON-file version of the same API. Good enough for a demo and tests."""

    def __init__(self, path=LOCAL_DB_PATH):
        self.path = str(path)

    # file helpers ---------------------------------------------------------
    def _read(self) -> Dict[str, Any]:
        if not os.path.exists(self.path):
            return {}
        with open(self.path, "r", encoding="utf-8") as fh:
            try:
                return json.load(fh)
            except json.JSONDecodeError:
                return {}

    def _write(self, blob: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, indent=2)

    def _bucket(self, blob: Dict[str, Any], student_id: str, name: str) -> List[Dict]:
        return (
            blob.setdefault("students", {})
            .setdefault(student_id, {})
            .setdefault(name, [])
        )

    def _upsert(self, student_id: str, name: str, record: Dict[str, Any]) -> None:
        blob = self._read()
        bucket = self._bucket(blob, student_id, name)
        for i, existing in enumerate(bucket):
            if existing.get("id") == record.get("id"):
                bucket[i] = record
                break
        else:
            bucket.append(record)
        self._write(blob)

    # students -------------------------------------------------------------
    def save_student(self, student: Student) -> None:
        blob = self._read()
        blob.setdefault("students", {}).setdefault(student.id, {})[
            "profile"
        ] = student.to_dict()
        self._write(blob)

    def get_student(self, student_id: str) -> Optional[Student]:
        record = (
            self._read().get("students", {}).get(student_id, {}).get("profile")
        )
        return Student.from_dict(record) if record else None

    # tests ----------------------------------------------------------------
    def save_test(self, test: TestRecord) -> None:
        self._upsert(test.student_id, "tests", test.to_dict())

    def list_tests(self, student_id: str) -> List[TestRecord]:
        raw = self._read().get("students", {}).get(student_id, {}).get("tests", [])
        tests = [TestRecord.from_dict(r) for r in raw]
        return sorted(tests, key=lambda t: (t.taken_on, t.created_at))

    # mistakes -------------------------------------------------------------
    def save_mistake(self, mistake: Mistake) -> None:
        self._upsert(mistake.student_id, "mistakes", mistake.to_dict())

    def list_mistakes(self, student_id: str) -> List[Mistake]:
        raw = self._read().get("students", {}).get(student_id, {}).get("mistakes", [])
        items = [Mistake.from_dict(r) for r in raw]
        return sorted(items, key=lambda m: (m.taken_on, m.created_at))

    # practice -------------------------------------------------------------
    def save_practice(self, practice: PracticeSet) -> None:
        self._upsert(practice.student_id, "practice", practice.to_dict())

    def list_practice(self, student_id: str) -> List[PracticeSet]:
        raw = self._read().get("students", {}).get(student_id, {}).get("practice", [])
        items = [PracticeSet.from_dict(r) for r in raw]
        return sorted(items, key=lambda p: p.created_at)

    # retests --------------------------------------------------------------
    def save_retest(self, retest: RetestResult) -> None:
        self._upsert(retest.student_id, "retests", retest.to_dict())

    def list_retests(self, student_id: str) -> List[RetestResult]:
        raw = self._read().get("students", {}).get(student_id, {}).get("retests", [])
        items = [RetestResult.from_dict(r) for r in raw]
        return sorted(items, key=lambda r: r.created_at)

    def clear_student(self, student_id: str) -> None:
        blob = self._read()
        student = blob.get("students", {}).get(student_id)
        if student:
            for name in COLLECTIONS:
                student[name] = []
            self._write(blob)


def get_store(settings: Settings) -> Store:
    """Pick the storage backend that the current configuration allows."""
    if settings.use_firebase:
        try:
            from .firebase_client import init_firebase

            return FirestoreStore(init_firebase(settings))
        except Exception as exc:  # noqa: BLE001 - fall back rather than crash
            print(f"[MistakeMind] Firebase unavailable ({exc}); using local store.")
    return LocalStore()
