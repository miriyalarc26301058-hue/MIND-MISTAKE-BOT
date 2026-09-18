"""
Backend smoke test - no Streamlit, no Firebase, no Gemini needed.

    python tests_backend.py

It seeds the demo student into a throwaway JSON store and checks that the
analysis, pattern detection and suggestions all produce something sensible.
Useful before a demo, and useful as the "we tested it" slide.
"""

from __future__ import annotations

import os
import tempfile

from backend.analysis import (
    clean_streaks,
    improvement_score,
    recurring_pattern,
    topic_counts,
    type_counts,
    weak_topics,
)
from backend.config import get_settings
from backend.models import MISTAKE_TYPES
from backend.seed import seed_demo
from backend.service import MistakeMindService
from backend.store import LocalStore

STUDENT = "test_student"


def main() -> None:
    tmp = os.path.join(tempfile.mkdtemp(), "store.json")
    settings = get_settings()
    settings.force_local = True
    service = MistakeMindService(settings=settings, store=LocalStore(tmp))

    found = seed_demo(service, STUDENT)
    snap = service.snapshot(STUDENT)

    assert found > 0, "seeding produced no mistakes"
    assert len(snap["tests"]) == 4, snap["tests"]
    assert snap["mistakes"], "no mistakes stored"
    for m in snap["mistakes"]:
        assert m.mistake_type in MISTAKE_TYPES, m.mistake_type
        assert m.reason, "every mistake needs a reason"

    print(f"tests stored        : {len(snap['tests'])}")
    print(f"mistakes analysed   : {len(snap['mistakes'])}")
    print(f"overall accuracy    : {snap['accuracy']}%")
    print(f"weak topics         : {weak_topics(snap['mistakes'])}")
    print(f"by topic            : {topic_counts(snap['mistakes'])}")
    print(f"by kind             : {type_counts(snap['mistakes'])}")
    print(f"pattern             : {recurring_pattern(snap['mistakes'], snap['tests'])}")
    print(f"clean streaks       : {clean_streaks(snap['mistakes'], snap['tests'])[:3]}")

    score = improvement_score(snap["mistakes"], snap["tests"], snap["retests"])
    assert 0 <= score["score"] <= 100, score
    print(f"improvement score   : {score['score']}/100 {score['parts']}")

    suggestions = service.suggestions(STUDENT)
    assert suggestions, "suggestions list came back empty"
    print("\nsuggestions:")
    for s in suggestions:
        print(f"  [{s.priority}] {s.title}\n        why: {s.evidence}")

    plan = service.study_plan(STUDENT, 60)
    assert sum(p["minutes"] for p in plan) > 0
    print(f"\nstudy plan          : {plan}")

    print("\nAll backend checks passed.")


if __name__ == "__main__":
    main()
