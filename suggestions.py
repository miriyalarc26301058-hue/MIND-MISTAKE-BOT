"""
The suggestions list.

Every suggestion is derived from stored evidence, never invented, and every one
carries the evidence line that produced it. That is what makes the list feel
earned rather than generic, and it is the easiest thing to defend in a demo:
point at a suggestion, then point at the mistakes that caused it.

Rules, in priority order:
  1. A topic that keeps coming back across several tests  -> practise it now
  2. One kind of error dominating (e.g. calculation)       -> change a habit
  3. A weak topic that was practised but never retested    -> retest it
  4. A topic with many mistakes and no practice yet        -> generate practice
  5. Accuracy sliding over the last three tests            -> slow down
  6. A topic gone quiet for several tests                  -> keep going
  7. Blank answers piling up                               -> exam technique
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .analysis import (
    accuracy_trend,
    clean_streaks,
    topic_counts,
    topic_spread,
    type_counts,
    weak_topics,
)
from .models import Mistake, PracticeSet, RetestResult, Suggestion, TestRecord


def build_suggestions(
    mistakes: List[Mistake],
    tests: List[TestRecord],
    practice: Optional[List[PracticeSet]] = None,
    retests: Optional[List[RetestResult]] = None,
    limit: int = 8,
) -> List[Suggestion]:
    practice = practice or []
    retests = retests or []
    out: List[Suggestion] = []

    if not tests:
        return [
            Suggestion(
                title="Add your first test",
                detail="Enter a test you have already written, with your answers and the "
                "correct ones. Everything else in the app is built from that.",
                action="practise",
                priority=1,
                evidence="No tests stored yet.",
            )
        ]

    counts = topic_counts(mistakes)
    spread = topic_spread(mistakes)
    types = type_counts(mistakes)
    practised = {p.topic for p in practice}
    retested = {r.topic for r in retests}
    total_mistakes = len(mistakes)

    # 1. recurring topics ---------------------------------------------------
    for topic, test_count in sorted(spread.items(), key=lambda kv: kv[1], reverse=True):
        if test_count >= 2 and counts.get(topic, 0) >= 2:
            out.append(
                Suggestion(
                    title=f"Fix {topic} before the next test",
                    detail=f"{topic} has gone wrong in {test_count} different tests. "
                    "A topic that repeats is not bad luck, it is a gap.",
                    action="practise",
                    topic=topic,
                    priority=1,
                    evidence=f"{counts[topic]} mistakes across {test_count} tests.",
                )
            )
            break

    # 2. dominant error type ------------------------------------------------
    if types and total_mistakes >= 3:
        top_type, n = next(iter(types.items()))
        share = round(100 * n / total_mistakes)
        if share >= 35:
            out.append(
                Suggestion(
                    title=_habit_title(top_type),
                    detail=_habit_detail(top_type),
                    action="habit",
                    priority=1 if share >= 50 else 2,
                    evidence=f"{share}% of your mistakes are {top_type.lower()} ones.",
                )
            )

    # 3. practised but never retested --------------------------------------
    for topic in practised - retested:
        out.append(
            Suggestion(
                title=f"Retest {topic}",
                detail="You practised this but never proved it stuck. A retest with fresh "
                "questions is the only way to know.",
                action="retest",
                topic=topic,
                priority=1,
                evidence=f"Practice completed on {topic}, no retest recorded.",
            )
        )
        break

    # 4. weak topic with no practice yet -----------------------------------
    for topic, n in weak_topics(mistakes):
        if topic not in practised:
            out.append(
                Suggestion(
                    title=f"Generate practice for {topic}",
                    detail="The mistakes are stored but nothing has been done about them "
                    "yet. Ten targeted questions is a short evening.",
                    action="practise",
                    topic=topic,
                    priority=2,
                    evidence=f"{n} mistakes in {topic}, no practice set yet.",
                )
            )
            break

    # 5. accuracy sliding ---------------------------------------------------
    trend = accuracy_trend(tests)
    if len(trend) >= 3:
        recent = [score for _, score in trend[-3:]]
        if recent[-1] < recent[0] - 5:
            out.append(
                Suggestion(
                    title="Your accuracy is sliding",
                    detail="Three tests, each a little worse. Before adding new topics, "
                    "clear the mistakes already on your list.",
                    action="revise",
                    priority=1,
                    evidence=f"{recent[0]}% then {recent[1]}% then {recent[2]}%.",
                )
            )

    # 6. something going right ---------------------------------------------
    for topic, run in clean_streaks(mistakes, tests):
        if run >= 2:
            out.append(
                Suggestion(
                    title=f"{topic} has gone quiet",
                    detail=f"No {topic} mistakes for {run} tests running. Keep it on a "
                    "light review rather than full practice.",
                    action="keep-going",
                    topic=topic,
                    priority=3,
                    evidence=f"{run} clean tests in a row.",
                )
            )
            break

    # 7. blank answers ------------------------------------------------------
    blanks = sum(1 for m in mistakes if not m.student_answer.strip())
    if blanks >= 2:
        out.append(
            Suggestion(
                title="Stop leaving questions blank",
                detail="A blank answer scores nothing even when you know the first step. "
                "Write the setup line, then move on and come back.",
                action="habit",
                priority=2,
                evidence=f"{blanks} questions left unanswered.",
            )
        )

    # 8. nothing wrong at all ----------------------------------------------
    if not out:
        out.append(
            Suggestion(
                title="Raise the difficulty",
                detail="Nothing is repeating and accuracy is holding. Take a harder test "
                "so the app has something to work with.",
                action="keep-going",
                priority=3,
                evidence="No recurring weakness detected.",
            )
        )

    out.sort(key=lambda s: (s.priority, s.title))
    return out[:limit]


def suggestions_as_rows(suggestions: List[Suggestion]) -> List[Dict[str, str]]:
    """Flatten for a table or for st.dataframe."""
    labels = {1: "Do first", 2: "Next", 3: "When you can"}
    return [
        {
            "Priority": labels.get(s.priority, "Next"),
            "Suggestion": s.title,
            "Why": s.evidence,
            "Topic": s.topic or "-",
            "Action": s.action,
        }
        for s in suggestions
    ]


def _habit_title(mistake_type: str) -> str:
    return {
        "Calculation": "Slow down on the middle steps",
        "Conceptual": "Go back to the worked examples",
        "Formula": "Write the formula before substituting",
        "Misread": "Read the question twice before starting",
        "Logical": "Check that each line follows from the last",
        "Careless": "Leave two minutes to check the paper",
    }.get(mistake_type, f"Work on {mistake_type.lower()} mistakes")


def _habit_detail(mistake_type: str) -> str:
    return {
        "Calculation": "The method is holding and the arithmetic is not. Work the middle "
        "lines out fully instead of in your head.",
        "Conceptual": "These are not slips. Reread the theory for the topics on your weak "
        "list before doing any more questions.",
        "Formula": "Most of these come from recalling a formula under pressure. Write it "
        "down first, then put numbers in.",
        "Misread": "You are answering a question next to the one asked. Underline what is "
        "being asked before the first line of working.",
        "Logical": "The steps are individually fine but the chain breaks. Say each step "
        "out loud as 'because of the line above'.",
        "Careless": "You know this material. Reserve the last two minutes of every test "
        "for checking signs, units and unfinished lines.",
    }.get(mistake_type, "Target this error type in your next practice set.")
