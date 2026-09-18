"""
Demo data.

Four tests over two weeks, with mistakes that deliberately repeat, so the
pattern detection and the suggestions list have something real to chew on
during a demo. Call it from the sidebar button in app.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List

from .models import Question
from .service import MistakeMindService


def _days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


DEMO_TESTS = [
    {
        "name": "Mathematics Test 01",
        "subject": "Mathematics",
        "days_ago": 14,
        "questions": [
            ("Solve 2x + 5 = 15", "10", "5", "Linear equations"),
            ("Find the roots of x^2 - 6x + 8 = 0", "2 and 3", "2 and 4", "Quadratic equations"),
            ("A fair coin is tossed twice. P(exactly one head)?", "0.25", "0.5", "Probability"),
            ("Integrate 3x^2 with respect to x", "", "x^3 + C", "Integration"),
            ("Solve 3x - 6 = 9", "5", "5", "Linear equations"),
            ("Simplify (x^2)(x^3)", "x^5", "x^5", "Indices"),
            ("Differentiate 4x^3", "12x^2", "12x^2", "Differentiation"),
            ("Find the value of 7 factorial", "5040", "5040", "Permutations"),
        ],
    },
    {
        "name": "Mathematics Test 02",
        "subject": "Mathematics",
        "days_ago": 10,
        "questions": [
            ("Find the roots of x^2 - 10x + 16 = 0", "2 and 7", "2 and 8", "Quadratic equations"),
            ("Solve 4x + 8 = 24", "8", "4", "Linear equations"),
            ("P(rolling a number greater than 4 on a die)?", "0.5", "0.333", "Probability"),
            ("Integrate 4x^3 dx", "x^4 + C", "x^4 + C", "Integration"),
            ("Solve 6x = 42", "7", "7", "Linear equations"),
            ("Differentiate 5x^2", "10x", "10x", "Differentiation"),
            ("Simplify (x^4)/(x^2)", "x^2", "x^2", "Indices"),
            ("How many ways can 4 books be arranged?", "24", "24", "Permutations"),
        ],
    },
    {
        "name": "Physics Test 01",
        "subject": "Physics",
        "days_ago": 6,
        "questions": [
            ("A body accelerates from 0 to 20 m/s in 4 s. Find a.", "10", "5", "Mechanics"),
            ("Momentum of a 2 kg body at 5 m/s?", "20", "10", "Mechanics"),
            ("Work done by a 10 N force over 3 m?", "30", "30", "Mechanics"),
            ("Unit of power?", "watt", "watt", "Units"),
            ("Kinetic energy of 2 kg at 3 m/s?", "9", "9", "Mechanics"),
            ("Unit of momentum?", "kg m/s", "kg m/s", "Units"),
            ("Weight of 5 kg on Earth (g = 10)?", "50", "50", "Mechanics"),
        ],
    },
    {
        "name": "Mathematics Test 03",
        "subject": "Mathematics",
        "days_ago": 2,
        "questions": [
            ("Find the roots of x^2 - 12x + 32 = 0", "4 and 9", "4 and 8", "Quadratic equations"),
            ("Two dice are rolled. P(sum of 7)?", "", "0.167", "Probability"),
            ("Integrate 6x^5 dx", "x^6 + C", "x^6 + C", "Integration"),
            ("Solve 5x - 10 = 20", "6", "6", "Linear equations"),
            ("Differentiate 4x^3", "12x^2", "12x^2", "Differentiation"),
            ("Solve 7x + 3 = 24", "3", "3", "Linear equations"),
            ("Simplify (2x)^3", "8x^3", "8x^3", "Indices"),
            ("Integrate 2x dx", "x^2 + C", "x^2 + C", "Integration"),
        ],
    },
]


def seed_demo(service: MistakeMindService, student_id: str) -> int:
    """Wipe and rebuild the demo history. Returns the number of mistakes found."""
    service.store.clear_student(student_id)
    found = 0

    for spec in DEMO_TESTS:
        questions: List[Question] = [
            Question(
                number=i + 1,
                text=text,
                student_answer=given,
                correct_answer=correct,
                topic=topic,
            )
            for i, (text, given, correct, topic) in enumerate(spec["questions"])
        ]
        test = service.submit_test(
            student_id=student_id,
            name=spec["name"],
            subject=spec["subject"],
            questions=questions,
            taken_on=_days_ago(spec["days_ago"]),
        )
        found += len(service.analyse_test(test))

    # one topic that was practised and retested, so the improvement score works
    practice = service.create_practice(student_id, "Quadratic equations", count=5)
    service.complete_practice(practice, score=80.0)
    service.record_retest(student_id, "Quadratic equations", before=52.0, after=81.0)

    return found
