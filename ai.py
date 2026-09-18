"""
The AI layer: the part that understands the problem.

MistakeAnalyzer does four jobs:

    analyze_mistake()  -> why this answer is wrong, what kind of mistake it is
    plain_explanation() -> the same thing again, in simpler language
    practice_questions() -> new questions aimed at one weakness
    study_plan()       -> how to spend the next study session

Each one asks Gemini for strict JSON and validates what comes back. If there is
no API key, or the call fails, a rule-based fallback produces a usable answer so
the app never dead-ends in front of an examiner.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from .config import Settings
from .models import MISTAKE_TYPES

_JSON_FENCE = re.compile(r"```(?:json)?|```", re.IGNORECASE)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")

ANALYSIS_SYSTEM_PROMPT = """You are an experienced examiner marking a student's work.
You are given one question, the student's answer, and the correct answer.
Explain WHY the student went wrong, in one or two sentences, addressed to the student.
Be concrete about the step that failed. Never scold, never pad.

Reply with ONLY a JSON object, no markdown fences and no commentary:
{
  "mistake_type": one of ["Conceptual","Calculation","Formula","Misread","Logical","Careless"],
  "topic": short topic name, 1-4 words,
  "reason": 1-2 sentences explaining the actual error,
  "recommendation": one short next step for the student,
  "confidence": "High" | "Medium" | "Low"
}"""


class MistakeAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._model = None
        self.last_source = "offline"

    # ------------------------------------------------------------------ #
    # model plumbing
    # ------------------------------------------------------------------ #
    @property
    def available(self) -> bool:
        return self.settings.use_gemini

    def _get_model(self):
        if self._model is None:
            import google.generativeai as genai

            genai.configure(api_key=self.settings.gemini_api_key)
            self._model = genai.GenerativeModel(self.settings.gemini_model)
        return self._model

    def _ask_json(self, prompt: str) -> Optional[Any]:
        """Send a prompt, expect JSON back, return None if anything goes wrong."""
        if not self.available:
            return None
        try:
            response = self._get_model().generate_content(prompt)
            return _parse_json(response.text)
        except Exception as exc:  # noqa: BLE001 - the fallback handles it
            print(f"[MistakeMind] Gemini call failed: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # 1. understand one mistake
    # ------------------------------------------------------------------ #
    def analyze_mistake(
        self,
        question: str,
        student_answer: str,
        correct_answer: str,
        subject: str = "",
        topic_hint: str = "",
        working: str = "",
    ) -> Dict[str, str]:
        prompt = (
            f"{ANALYSIS_SYSTEM_PROMPT}\n\n"
            f"Subject: {subject or 'General'}\n"
            f"Topic hint: {topic_hint or 'unknown'}\n"
            f"Question: {question}\n"
            f"Student's answer: {student_answer}\n"
            f"Correct answer: {correct_answer}\n"
            f"Student's working: {working or 'not provided'}\n"
        )
        data = self._ask_json(prompt)
        if isinstance(data, dict):
            result = _clean_analysis(data, topic_hint)
            result["source"] = "gemini"
            self.last_source = "gemini"
            return result

        result = heuristic_analysis(
            question, student_answer, correct_answer, subject, topic_hint
        )
        self.last_source = "offline"
        return result

    # ------------------------------------------------------------------ #
    # 2. say it again, more simply
    # ------------------------------------------------------------------ #
    def plain_explanation(self, mistake) -> str:
        prompt = (
            "Explain to a student, in three short sentences and simple language, "
            "why this answer was wrong and how to avoid it next time. "
            "No headings, no bullet points, no JSON.\n\n"
            f"Question: {mistake.question}\n"
            f"Their answer: {mistake.student_answer}\n"
            f"Correct answer: {mistake.correct_answer}\n"
            f"Examiner's note: {mistake.reason}\n"
        )
        if self.available:
            try:
                return self._get_model().generate_content(prompt).text.strip()
            except Exception as exc:  # noqa: BLE001
                print(f"[MistakeMind] Gemini call failed: {exc}")
        return (
            f"On this question the correct answer was {mistake.correct_answer}, "
            f"and you wrote {mistake.student_answer}. {mistake.reason} "
            f"{mistake.recommendation}"
        )

    # ------------------------------------------------------------------ #
    # 3. generate practice for one weakness
    # ------------------------------------------------------------------ #
    def practice_questions(
        self,
        topic: str,
        mistake_types: List[str],
        difficulty: str = "Beginner",
        count: int = 5,
        subject: str = "",
    ) -> List[Dict[str, str]]:
        focus = ", ".join(mistake_types) or "mixed errors"
        prompt = (
            f"Write {count} practice questions on '{topic}'"
            f"{' in ' + subject if subject else ''} at {difficulty} level.\n"
            f"The student keeps making these kinds of mistakes: {focus}. "
            "Target exactly those. Keep numbers small enough to work by hand.\n"
            "Reply with ONLY a JSON array, no fences:\n"
            '[{"question": "...", "answer": "...", "hint": "..."}]'
        )
        data = self._ask_json(prompt)
        if isinstance(data, list) and data:
            cleaned = []
            for item in data[:count]:
                if isinstance(item, dict) and item.get("question"):
                    cleaned.append(
                        {
                            "question": str(item.get("question", "")).strip(),
                            "answer": str(item.get("answer", "")).strip(),
                            "hint": str(item.get("hint", "")).strip(),
                        }
                    )
            if cleaned:
                return cleaned
        return _fallback_practice(topic, mistake_types, count)

    # ------------------------------------------------------------------ #
    # 4. a study plan for today
    # ------------------------------------------------------------------ #
    def study_plan(
        self, weak_topics: List[str], minutes: int = 60
    ) -> List[Dict[str, Any]]:
        if weak_topics and self.available:
            prompt = (
                f"A student has {minutes} minutes to study today. Their weakest "
                f"topics, worst first, are: {', '.join(weak_topics)}. "
                "Build a plan that ends with a short retest.\n"
                "Reply with ONLY a JSON array, no fences:\n"
                '[{"activity": "...", "minutes": 20}]'
            )
            data = self._ask_json(prompt)
            if isinstance(data, list) and data:
                plan = []
                for item in data:
                    if isinstance(item, dict) and item.get("activity"):
                        try:
                            mins = int(item.get("minutes", 10))
                        except (TypeError, ValueError):
                            mins = 10
                        plan.append(
                            {"activity": str(item["activity"]), "minutes": mins}
                        )
                if plan:
                    return plan
        return _fallback_plan(weak_topics, minutes)


# --------------------------------------------------------------------------- #
# Offline fallbacks
# --------------------------------------------------------------------------- #
def heuristic_analysis(
    question: str,
    student_answer: str,
    correct_answer: str,
    subject: str = "",
    topic_hint: str = "",
) -> Dict[str, str]:
    """
    A small rule-based examiner, used when Gemini is not available.

    It compares the two answers numerically where it can, which is enough to
    separate a blank answer, a sign slip, a near miss and a wholly wrong answer.
    """
    student = (student_answer or "").strip()
    correct = (correct_answer or "").strip()
    topic = topic_hint or _guess_topic(question, subject)

    if not student:
        return _analysis(
            "Careless",
            topic,
            "This one was left blank, so no marks could be given even if you knew the method.",
            "Always write the step you are sure of - partial working can still earn marks.",
            "High",
        )

    s_nums = [float(n) for n in _NUMBER.findall(student)]
    c_nums = [float(n) for n in _NUMBER.findall(correct)]

    if s_nums and c_nums:
        s, c = s_nums[-1], c_nums[-1]
        if abs(s + c) < 1e-9 and abs(c) > 1e-9:
            return _analysis(
                "Calculation",
                topic,
                "Your answer is the correct value with the wrong sign, so a minus was "
                "dropped or moved across the equals sign without changing.",
                "Redo this question writing each sign change on its own line.",
                "High",
            )
        if abs(c) > 1e-9 and abs(s - c) / max(abs(c), 1e-9) <= 0.25:
            return _analysis(
                "Calculation",
                topic,
                "You landed close to the correct value, which usually means the method "
                "was right and one arithmetic step slipped.",
                "Rework the middle steps slowly and check each one before moving on.",
                "Medium",
            )
        if abs(c) > 1e-9 and (
            abs(s - 2 * c) < 1e-9 or abs(2 * s - c) < 1e-9
        ):
            equation_work = "solve" in (question or "").lower() or "equation" in topic.lower()
            if equation_work:
                return _analysis(
                    "Calculation",
                    topic,
                    "Your answer is exactly double or half the correct value, which "
                    "usually means a term was added instead of subtracted, or a "
                    "coefficient was not divided through.",
                    "Redo it writing each rearrangement on its own line.",
                    "High",
                )
            return _analysis(
                "Formula",
                topic,
                "Your answer is out by a factor of two, which normally points at a "
                "constant in the formula being dropped or doubled.",
                "Write the formula out before substituting any numbers.",
                "Medium",
            )
        return _analysis(
            "Conceptual",
            topic,
            "The answer is far from the correct value, so the approach itself is likely "
            "off rather than the arithmetic.",
            f"Revise the worked examples for {topic} before attempting more questions.",
            "Medium",
        )

    if student.lower() in correct.lower() or correct.lower() in student.lower():
        return _analysis(
            "Misread",
            topic,
            "Your answer overlaps the correct one but does not match it, which usually "
            "means part of the question was answered and part was missed.",
            "Underline what the question is asking for before you start writing.",
            "Medium",
        )

    return _analysis(
        "Conceptual",
        topic,
        "The answer given does not follow from the question, so the underlying idea "
        "needs another pass.",
        f"Go back over the basics of {topic}, then try two easy questions on it.",
        "Low",
    )


def _analysis(
    mistake_type: str, topic: str, reason: str, recommendation: str, confidence: str
) -> Dict[str, str]:
    return {
        "mistake_type": mistake_type,
        "topic": topic,
        "reason": reason,
        "recommendation": recommendation,
        "confidence": confidence,
        "source": "offline",
    }


def _fallback_practice(
    topic: str, mistake_types: List[str], count: int
) -> List[Dict[str, str]]:
    focus = mistake_types[0] if mistake_types else "accuracy"
    return [
        {
            "question": f"{topic} practice {i + 1}: work this one out step by step, "
            f"writing every line (focus: {focus.lower()} errors).",
            "answer": "",
            "hint": "Check each step against the one above before moving on.",
        }
        for i in range(count)
    ]


def _fallback_plan(weak_topics: List[str], minutes: int) -> List[Dict[str, Any]]:
    topics = weak_topics[:3] or ["Revision"]
    retest = max(10, int(minutes * 0.25))
    remaining = minutes - retest
    share = max(5, remaining // len(topics))
    plan = [{"activity": f"{t} practice", "minutes": share} for t in topics]
    plan.append({"activity": "Retest on your weakest topic", "minutes": retest})
    return plan


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _parse_json(text: str) -> Optional[Any]:
    """Strip markdown fences and parse the first JSON object or array found."""
    if not text:
        return None
    cleaned = _JSON_FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _clean_analysis(data: Dict[str, Any], topic_hint: str) -> Dict[str, str]:
    """Force whatever the model returned into the shape the database expects."""
    mistake_type = str(data.get("mistake_type", "")).strip().title()
    if mistake_type not in MISTAKE_TYPES:
        mistake_type = "Conceptual"
    confidence = str(data.get("confidence", "Medium")).strip().title()
    if confidence not in {"High", "Medium", "Low"}:
        confidence = "Medium"
    return {
        "mistake_type": mistake_type,
        "topic": str(data.get("topic") or topic_hint or "Unsorted").strip()[:60],
        "reason": str(data.get("reason", "")).strip(),
        "recommendation": str(data.get("recommendation", "")).strip(),
        "confidence": confidence,
    }


def _guess_topic(question: str, subject: str) -> str:
    """Very rough topic tagging for the offline mode."""
    q = (question or "").lower()
    table = [
        (("integrate", "integral", "∫"), "Integration"),
        (("differentiate", "derivative", "dy/dx"), "Differentiation"),
        (("probability", "dice", "coin", "cards"), "Probability"),
        (("matrix", "determinant"), "Matrices"),
        (("x^2", "x²", "quadratic", "roots"), "Quadratic equations"),
        (("solve", "equation", "="), "Linear equations"),
        (("force", "velocity", "acceleration"), "Mechanics"),
        (("loop", "list", "function", "python", "output"), "Programming basics"),
    ]
    for needles, topic in table:
        if any(n in q for n in needles):
            return topic
    return subject or "Unsorted"
