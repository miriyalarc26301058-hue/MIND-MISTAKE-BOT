"""
Pattern detection.

Nothing here calls an API or a database - it takes the stored mistakes, tests
and retests and works out what keeps going wrong. Pure functions, so they can
be tested on their own (see tests_backend.py).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .models import Mistake, RetestResult, TestRecord

WEAK_TOPIC_THRESHOLD = 2  # a topic becomes "weak" from this many mistakes up


# --------------------------------------------------------------------------- #
# counting
# --------------------------------------------------------------------------- #
def topic_counts(mistakes: List[Mistake]) -> Dict[str, int]:
    return dict(Counter(m.topic or "Unsorted" for m in mistakes).most_common())


def type_counts(mistakes: List[Mistake]) -> Dict[str, int]:
    return dict(Counter(m.mistake_type for m in mistakes).most_common())


def subject_counts(mistakes: List[Mistake]) -> Dict[str, int]:
    return dict(Counter(m.subject or "General" for m in mistakes).most_common())


def weak_topics(
    mistakes: List[Mistake], threshold: int = WEAK_TOPIC_THRESHOLD
) -> List[Tuple[str, int]]:
    """Topics with enough mistakes to be worth practising, worst first."""
    return [(t, n) for t, n in topic_counts(mistakes).items() if n >= threshold]


def topic_spread(mistakes: List[Mistake]) -> Dict[str, int]:
    """How many *different tests* each topic went wrong in."""
    spread: Dict[str, set] = defaultdict(set)
    for m in mistakes:
        spread[m.topic or "Unsorted"].add(m.test_id)
    return {topic: len(tests) for topic, tests in spread.items()}


# --------------------------------------------------------------------------- #
# the headline insight
# --------------------------------------------------------------------------- #
def recurring_pattern(mistakes: List[Mistake], tests: List[TestRecord]) -> str:
    """One sentence naming the thing that keeps happening."""
    if not mistakes:
        return "No mistakes stored yet. Add a test to start building the picture."

    types = type_counts(mistakes)
    top_type, type_n = next(iter(types.items()))
    tests_with_type = len({m.test_id for m in mistakes if m.mistake_type == top_type})

    spread = topic_spread(mistakes)
    top_topic, topic_tests = max(spread.items(), key=lambda kv: kv[1])
    topic_n = topic_counts(mistakes).get(top_topic, 0)

    share = round(100 * type_n / len(mistakes))

    if tests_with_type >= 3:
        return (
            f"{top_type.lower()} mistakes have shown up in {tests_with_type} separate "
            f"tests and account for {share}% of everything you have got wrong."
        )
    if topic_tests >= 2:
        return (
            f"{top_topic} has cost you {topic_n} marks across {topic_tests} tests - "
            f"it is the topic that keeps coming back."
        )
    return (
        f"So far your mistakes are mostly {top_type.lower()} ones, "
        f"{type_n} of {len(mistakes)}."
    )


# --------------------------------------------------------------------------- #
# trends
# --------------------------------------------------------------------------- #
def accuracy_trend(tests: List[TestRecord]) -> List[Tuple[str, float]]:
    ordered = sorted(tests, key=lambda t: (t.taken_on, t.created_at))
    return [(t.name or t.taken_on, t.score) for t in ordered]


def overall_accuracy(tests: List[TestRecord]) -> float:
    total = sum(t.total for t in tests)
    correct = sum(t.correct_count for t in tests)
    return round(100 * correct / total, 1) if total else 0.0


def topic_accuracy(tests: List[TestRecord], topic: str) -> float:
    """Accuracy on questions tagged with one topic, across every test."""
    asked = [q for t in tests for q in t.questions if (q.topic or "").lower() == topic.lower()]
    if not asked:
        return 0.0
    correct = sum(1 for q in asked if q.is_correct)
    return round(100 * correct / len(asked), 1)


def heatmap(mistakes: List[Mistake], days: int = 7) -> Dict[str, Dict[str, int]]:
    """
    Mistakes per subject per day for the last `days` days.
    Returns {subject: {"2026-09-14": 3, ...}} ready to drop into a table.
    """
    today = date.today()
    window = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    grid: Dict[str, Dict[str, int]] = {}
    for m in mistakes:
        if m.taken_on in window:
            subject = m.subject or "General"
            grid.setdefault(subject, {d: 0 for d in window})
            grid[subject][m.taken_on] += 1
    return grid


# --------------------------------------------------------------------------- #
# streaks and scores
# --------------------------------------------------------------------------- #
def clean_streaks(
    mistakes: List[Mistake], tests: List[TestRecord]
) -> List[Tuple[str, int]]:
    """
    For each topic the student has got wrong before: how many tests in a row,
    counting back from the most recent, did NOT repeat that mistake.
    """
    ordered = sorted(tests, key=lambda t: (t.taken_on, t.created_at))
    by_test: Dict[str, set] = defaultdict(set)
    for m in mistakes:
        by_test[m.test_id].add(m.topic or "Unsorted")

    streaks = []
    for topic in topic_counts(mistakes):
        run = 0
        for test in reversed(ordered):
            if topic in by_test.get(test.id, set()):
                break
            run += 1
        streaks.append((topic, run))
    return sorted(streaks, key=lambda kv: kv[1], reverse=True)


def improvement_score(
    mistakes: List[Mistake],
    tests: List[TestRecord],
    retests: List[RetestResult],
) -> Dict[str, Any]:
    """
    A 0-100 learning score. Marks say how a test went; this says whether the
    student is actually fixing things. Three parts:

        50%  retest gains      - did practice move the needle
        30%  repetition        - are old mistakes staying fixed
        20%  accuracy trend    - is the overall score climbing
    """
    if not tests:
        return {"score": 0, "parts": {}, "note": "Add a test to start scoring."}

    # 1. retest gains
    if retests:
        gains = [r.improvement for r in retests]
        avg_gain = sum(gains) / len(gains)
        retest_part = _clamp(50 * (avg_gain / 30.0))  # +30 points counts as full marks
    else:
        retest_part = 0.0

    # 2. repetition: share of weak topics that did not come back in the last test
    ordered = sorted(tests, key=lambda t: (t.taken_on, t.created_at))
    latest = ordered[-1]
    earlier_topics = {
        m.topic for m in mistakes if m.test_id != latest.id
    }
    latest_topics = {m.topic for m in mistakes if m.test_id == latest.id}
    if earlier_topics:
        repeated = len(earlier_topics & latest_topics)
        repetition_part = 30 * (1 - repeated / len(earlier_topics))
    else:
        repetition_part = 30.0 if not latest_topics else 15.0

    # 3. accuracy trend across the last three tests
    recent = [t.score for t in ordered[-3:]]
    if len(recent) >= 2:
        delta = recent[-1] - recent[0]
        trend_part = _clamp(10 + 10 * (delta / 20.0), lo=0, hi=20)
    else:
        trend_part = 10.0

    total = round(retest_part + repetition_part + trend_part)
    return {
        "score": int(_clamp(total, lo=0, hi=100)),
        "parts": {
            "Retest gains": round(retest_part, 1),
            "Mistakes not repeated": round(repetition_part, 1),
            "Accuracy trend": round(trend_part, 1),
        },
        "note": _score_note(total),
    }


def _score_note(score: float) -> str:
    if score >= 75:
        return "Old mistakes are staying fixed. Keep the loop running."
    if score >= 50:
        return "Progress is real but uneven - one topic is still coming back."
    if score > 0:
        return "Practice is happening; the retests have not caught up yet."
    return "Not enough history yet. Take one test and one retest."


def _clamp(value: float, lo: float = 0.0, hi: float = 50.0) -> float:
    return max(lo, min(hi, value))


def days_since(iso_date: str) -> Optional[int]:
    try:
        then = datetime.fromisoformat(iso_date).date()
    except (TypeError, ValueError):
        return None
    return (date.today() - then).days
