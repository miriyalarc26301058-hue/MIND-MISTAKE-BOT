"""
The data model. These classes are what gets written to Firestore, so keeping
them in one place means the database shape is never guessed at in the UI code.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Any, Dict, List, Optional

# The six buckets every mistake is filed under.
MISTAKE_TYPES: List[str] = [
    "Conceptual",
    "Calculation",
    "Formula",
    "Misread",
    "Logical",
    "Careless",
]

MISTAKE_TYPE_HELP: Dict[str, str] = {
    "Conceptual": "The idea underneath is missing, so the answer is built on the wrong footing.",
    "Calculation": "Right method, wrong arithmetic - usually a middle step under time pressure.",
    "Formula": "The wrong formula, or the right one remembered slightly wrong.",
    "Misread": "The question was answered correctly, just not the question that was asked.",
    "Logical": "Each step looks fine alone, but one does not follow from the one above it.",
    "Careless": "Known material lost to speed: a dropped minus, a skipped unit, an unfinished line.",
}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class Student:
    id: str
    name: str
    email: str
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Student":
        return Student(
            id=d["id"],
            name=d.get("name", ""),
            email=d.get("email", ""),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class Question:
    """One question inside a test, with what the student actually wrote."""

    number: int
    text: str
    student_answer: str
    correct_answer: str
    topic: str = ""
    working: str = ""  # optional: the steps the student wrote out

    @property
    def is_correct(self) -> bool:
        return _normalise(self.student_answer) == _normalise(self.correct_answer)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Question":
        return Question(
            number=int(d.get("number", 0)),
            text=d.get("text", ""),
            student_answer=d.get("student_answer", ""),
            correct_answer=d.get("correct_answer", ""),
            topic=d.get("topic", ""),
            working=d.get("working", ""),
        )


@dataclass
class TestRecord:
    id: str
    student_id: str
    name: str
    subject: str
    taken_on: str  # YYYY-MM-DD
    questions: List[Question] = field(default_factory=list)
    is_retest_of: Optional[str] = None  # topic name, when this test is a retest
    created_at: str = field(default_factory=now_iso)

    @property
    def total(self) -> int:
        return len(self.questions)

    @property
    def correct_count(self) -> int:
        return sum(1 for q in self.questions if q.is_correct)

    @property
    def score(self) -> float:
        """Accuracy as a percentage, 0 when the test has no questions."""
        return round(100.0 * self.correct_count / self.total, 1) if self.total else 0.0

    def wrong_questions(self) -> List[Question]:
        return [q for q in self.questions if not q.is_correct]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "student_id": self.student_id,
            "name": self.name,
            "subject": self.subject,
            "taken_on": self.taken_on,
            "questions": [q.to_dict() for q in self.questions],
            "is_retest_of": self.is_retest_of,
            "created_at": self.created_at,
            # stored as well as computed, so reports can be built without
            # re-reading every question document
            "score": self.score,
            "total": self.total,
            "correct_count": self.correct_count,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "TestRecord":
        return TestRecord(
            id=d["id"],
            student_id=d.get("student_id", ""),
            name=d.get("name", ""),
            subject=d.get("subject", ""),
            taken_on=d.get("taken_on", date.today().isoformat()),
            questions=[Question.from_dict(q) for q in d.get("questions", [])],
            is_retest_of=d.get("is_retest_of"),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class Mistake:
    """One wrong answer, after the AI has explained it."""

    id: str
    student_id: str
    test_id: str
    test_name: str
    subject: str
    question: str
    student_answer: str
    correct_answer: str
    topic: str
    mistake_type: str
    reason: str
    recommendation: str
    confidence: str = "Medium"
    taken_on: str = field(default_factory=lambda: date.today().isoformat())
    source: str = "gemini"  # or "offline"
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Mistake":
        return Mistake(
            id=d["id"],
            student_id=d.get("student_id", ""),
            test_id=d.get("test_id", ""),
            test_name=d.get("test_name", ""),
            subject=d.get("subject", ""),
            question=d.get("question", ""),
            student_answer=d.get("student_answer", ""),
            correct_answer=d.get("correct_answer", ""),
            topic=d.get("topic", "Unsorted"),
            mistake_type=d.get("mistake_type", "Conceptual"),
            reason=d.get("reason", ""),
            recommendation=d.get("recommendation", ""),
            confidence=d.get("confidence", "Medium"),
            taken_on=d.get("taken_on", date.today().isoformat()),
            source=d.get("source", "gemini"),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class PracticeSet:
    id: str
    student_id: str
    topic: str
    difficulty: str
    focus: List[str]
    questions: List[Dict[str, Any]]  # {question, answer, hint}
    completed: bool = False
    score: Optional[float] = None
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PracticeSet":
        return PracticeSet(
            id=d["id"],
            student_id=d.get("student_id", ""),
            topic=d.get("topic", ""),
            difficulty=d.get("difficulty", "Beginner"),
            focus=list(d.get("focus", [])),
            questions=list(d.get("questions", [])),
            completed=bool(d.get("completed", False)),
            score=d.get("score"),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class RetestResult:
    id: str
    student_id: str
    topic: str
    before_accuracy: float
    after_accuracy: float
    test_id: Optional[str] = None
    created_at: str = field(default_factory=now_iso)

    @property
    def improvement(self) -> float:
        return round(self.after_accuracy - self.before_accuracy, 1)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["improvement"] = self.improvement
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "RetestResult":
        return RetestResult(
            id=d["id"],
            student_id=d.get("student_id", ""),
            topic=d.get("topic", ""),
            before_accuracy=float(d.get("before_accuracy", 0)),
            after_accuracy=float(d.get("after_accuracy", 0)),
            test_id=d.get("test_id"),
            created_at=d.get("created_at", now_iso()),
        )


@dataclass
class Suggestion:
    """One row in the suggestions list shown to the student."""

    title: str
    detail: str
    action: str  # practise | revise | retest | habit | keep-going
    topic: str = ""
    priority: int = 2  # 1 = do this first, 3 = nice to have
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalise(value: str) -> str:
    """Loose answer matching: ignores case, spaces and a trailing full stop."""
    return "".join(str(value).lower().split()).rstrip(".")
