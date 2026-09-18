"""
Service layer - the only thing app.py talks to.

It owns the flow the whole project is built around:

    save a test -> analyse every wrong answer -> store the mistakes
                -> detect patterns -> generate practice -> record a retest
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from . import analysis
from .ai import MistakeAnalyzer
from .config import Settings, get_settings
from .models import (
    Mistake,
    PracticeSet,
    Question,
    RetestResult,
    Student,
    Suggestion,
    TestRecord,
    new_id,
)
from .store import Store, get_store
from .suggestions import build_suggestions


class MistakeMindService:
    def __init__(self, settings: Optional[Settings] = None, store: Optional[Store] = None):
        self.settings = settings or get_settings()
        self.store = store or get_store(self.settings)
        self.ai = MistakeAnalyzer(self.settings)

    # ------------------------------------------------------------------ #
    # students
    # ------------------------------------------------------------------ #
    def ensure_student(self, student_id: str, name: str, email: str) -> Student:
        student = self.store.get_student(student_id)
        if student is None:
            student = Student(id=student_id, name=name, email=email)
            self.store.save_student(student)
        return student

    # ------------------------------------------------------------------ #
    # the main flow
    # ------------------------------------------------------------------ #
    def submit_test(
        self,
        student_id: str,
        name: str,
        subject: str,
        questions: List[Question],
        taken_on: Optional[str] = None,
        is_retest_of: Optional[str] = None,
    ) -> TestRecord:
        test = TestRecord(
            id=new_id("test"),
            student_id=student_id,
            name=name,
            subject=subject,
            taken_on=taken_on or date.today().isoformat(),
            questions=questions,
            is_retest_of=is_retest_of,
        )
        self.store.save_test(test)
        return test

    def analyse_test(self, test: TestRecord) -> List[Mistake]:
        """Send every wrong answer to the AI layer and store what comes back."""
        found: List[Mistake] = []
        for question in test.wrong_questions():
            verdict = self.ai.analyze_mistake(
                question=question.text,
                student_answer=question.student_answer,
                correct_answer=question.correct_answer,
                subject=test.subject,
                topic_hint=question.topic,
                working=question.working,
            )
            mistake = Mistake(
                id=new_id("mis"),
                student_id=test.student_id,
                test_id=test.id,
                test_name=test.name,
                subject=test.subject,
                question=question.text,
                student_answer=question.student_answer,
                correct_answer=question.correct_answer,
                topic=verdict["topic"],
                mistake_type=verdict["mistake_type"],
                reason=verdict["reason"],
                recommendation=verdict["recommendation"],
                confidence=verdict["confidence"],
                taken_on=test.taken_on,
                source=verdict.get("source", "gemini"),
            )
            self.store.save_mistake(mistake)
            found.append(mistake)
        return found

    def create_practice(
        self, student_id: str, topic: str, count: int = 5, difficulty: str = "Beginner"
    ) -> PracticeSet:
        mistakes = [
            m for m in self.store.list_mistakes(student_id) if m.topic == topic
        ]
        focus = list(dict.fromkeys(m.mistake_type for m in mistakes)) or ["Conceptual"]
        subject = mistakes[0].subject if mistakes else ""
        questions = self.ai.practice_questions(
            topic=topic,
            mistake_types=focus,
            difficulty=difficulty,
            count=count,
            subject=subject,
        )
        practice = PracticeSet(
            id=new_id("prac"),
            student_id=student_id,
            topic=topic,
            difficulty=difficulty,
            focus=focus,
            questions=questions,
        )
        self.store.save_practice(practice)
        return practice

    def complete_practice(self, practice: PracticeSet, score: Optional[float] = None) -> None:
        practice.completed = True
        practice.score = score
        self.store.save_practice(practice)

    def record_retest(
        self, student_id: str, topic: str, before: float, after: float, test_id=None
    ) -> RetestResult:
        retest = RetestResult(
            id=new_id("ret"),
            student_id=student_id,
            topic=topic,
            before_accuracy=before,
            after_accuracy=after,
            test_id=test_id,
        )
        self.store.save_retest(retest)
        return retest

    # ------------------------------------------------------------------ #
    # reads for the UI
    # ------------------------------------------------------------------ #
    def snapshot(self, student_id: str) -> Dict[str, Any]:
        """Everything the dashboard needs, in one call."""
        tests = self.store.list_tests(student_id)
        mistakes = self.store.list_mistakes(student_id)
        practice = self.store.list_practice(student_id)
        retests = self.store.list_retests(student_id)
        return {
            "tests": tests,
            "mistakes": mistakes,
            "practice": practice,
            "retests": retests,
            "accuracy": analysis.overall_accuracy(tests),
            "weak_topics": analysis.weak_topics(mistakes),
            "topic_counts": analysis.topic_counts(mistakes),
            "type_counts": analysis.type_counts(mistakes),
            "pattern": analysis.recurring_pattern(mistakes, tests),
            "improvement": analysis.improvement_score(mistakes, tests, retests),
            "heatmap": analysis.heatmap(mistakes),
            "streaks": analysis.clean_streaks(mistakes, tests),
            "trend": analysis.accuracy_trend(tests),
        }

    def suggestions(self, student_id: str) -> List[Suggestion]:
        return build_suggestions(
            self.store.list_mistakes(student_id),
            self.store.list_tests(student_id),
            self.store.list_practice(student_id),
            self.store.list_retests(student_id),
        )

    def study_plan(self, student_id: str, minutes: int = 60) -> List[Dict[str, Any]]:
        mistakes = self.store.list_mistakes(student_id)
        topics = [t for t, _ in analysis.weak_topics(mistakes)]
        return self.ai.study_plan(topics, minutes)

    def explain_simply(self, mistake: Mistake) -> str:
        return self.ai.plain_explanation(mistake)
