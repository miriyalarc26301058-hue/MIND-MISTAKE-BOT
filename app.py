"""
MistakeMind - Streamlit frontend.

Run with:  streamlit run app.py

This file only draws screens. Every calculation, AI call and database write
lives in backend/, so the UI can be replaced without touching the logic.
"""

from __future__ import annotations

from datetime import date
from typing import List

import pandas as pd
import streamlit as st

from backend.config import get_settings
from backend.firebase_client import AuthError, get_auth
from backend.models import MISTAKE_TYPE_HELP, Question
from backend.seed import seed_demo
from backend.service import MistakeMindService
from backend.suggestions import suggestions_as_rows

PAGES = [
    "Dashboard",
    "Add a test",
    "Mistake analysis",
    "Patterns",
    "Suggestions",
    "Practice",
    "Retest",
    "History",
]

PRIORITY_LABEL = {1: "Do first", 2: "Next", 3: "When you can"}
ACTION_ICON = {
    "practise": "📝",
    "revise": "📖",
    "retest": "🔁",
    "habit": "🧭",
    "keep-going": "✅",
}

st.set_page_config(page_title="MistakeMind", page_icon="✦", layout="wide")


# --------------------------------------------------------------------------- #
# setup
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner=False)
def get_service() -> MistakeMindService:
    return MistakeMindService()


def goto(page: str) -> None:
    """Queue a page change; applied at the top of the next run."""
    st.session_state["pending_nav"] = page
    st.rerun()


def current_student():
    return st.session_state.get("student")


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #
def auth_screen(settings) -> None:
    st.title("✦ MistakeMind")
    st.caption(
        "Find out why the answer was wrong, not just that it was. "
        f"({settings.describe()})"
    )

    auth = get_auth(settings)
    sign_in, sign_up, demo = st.tabs(["Sign in", "Create account", "Try the demo"])

    with sign_in:
        with st.form("sign_in"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            if st.form_submit_button("Sign in", type="primary"):
                try:
                    st.session_state["student"] = auth.sign_in(email, password)
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))

    with sign_up:
        with st.form("sign_up"):
            name = st.text_input("Your name")
            email = st.text_input("Email", key="su_email")
            password = st.text_input(
                "Password", type="password", key="su_pw", help="At least 6 characters"
            )
            if st.form_submit_button("Create account", type="primary"):
                try:
                    st.session_state["student"] = auth.sign_up(email, password, name)
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))

    with demo:
        st.write(
            "Opens a sample student with four tests already analysed - enough "
            "history for the patterns and suggestions to mean something."
        )
        if st.button("Open demo student", type="primary"):
            st.session_state["student"] = {
                "id": "demo_student",
                "name": "Demo student",
                "email": "demo@mistakemind.app",
            }
            st.session_state["seed_demo_on_load"] = True
            st.rerun()


# --------------------------------------------------------------------------- #
# pages
# --------------------------------------------------------------------------- #
def page_dashboard(service: MistakeMindService, student) -> None:
    snap = service.snapshot(student["id"])
    st.subheader(f"Good to see you, {student['name'].split()[0]}")

    if not snap["tests"]:
        st.info("No tests yet. Add one to start the loop.")
        if st.button("Add a test", type="primary"):
            goto("Add a test")
        return

    st.caption(snap["pattern"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Accuracy", f"{snap['accuracy']}%")
    c2.metric("Mistakes stored", len(snap["mistakes"]))
    c3.metric("Weak topics", len(snap["weak_topics"]))
    c4.metric("Improvement score", f"{snap['improvement']['score']}/100")

    left, right = st.columns([3, 2])

    with left:
        st.markdown("**Accuracy over time**")
        trend = pd.DataFrame(snap["trend"], columns=["Test", "Score"]).set_index("Test")
        st.line_chart(trend, height=240)

        latest = snap["tests"][-1]
        st.markdown(
            f"**Most recent:** {latest.name} - {latest.score}% "
            f"({latest.total - latest.correct_count} mistakes, {latest.taken_on})"
        )
        a, b = st.columns(2)
        if a.button("Analyse this test", type="primary"):
            st.session_state["selected_test"] = latest.id
            goto("Mistake analysis")
        if b.button("See what to do next"):
            goto("Suggestions")

    with right:
        st.markdown("**Weak topics**")
        if snap["weak_topics"]:
            st.dataframe(
                pd.DataFrame(snap["weak_topics"], columns=["Topic", "Mistakes"]),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("Nothing is repeating yet.")

        st.markdown("**What the score is made of**")
        for part, value in snap["improvement"]["parts"].items():
            st.caption(f"{part}: {value}")
        st.caption(snap["improvement"]["note"])


def page_add_test(service: MistakeMindService, student) -> None:
    st.subheader("Add a test")
    st.caption(
        "Enter the questions with your answer and the correct one. "
        "Anything you got wrong goes to the AI for analysis."
    )

    col1, col2, col3 = st.columns(3)
    name = col1.text_input("Test name", value="Mathematics Test 04")
    subject = col2.text_input("Subject", value="Mathematics")
    taken_on = col3.date_input("Date", value=date.today())

    retest_topic = st.text_input(
        "Is this a retest? Topic being retested (leave blank if not)", value=""
    )

    blank = pd.DataFrame(
        [{"Question": "", "Your answer": "", "Correct answer": "", "Topic": ""}] * 5
    )
    edited = st.data_editor(
        blank,
        num_rows="dynamic",
        use_container_width=True,
        key="test_rows",
        column_config={
            "Question": st.column_config.TextColumn(width="large"),
            "Topic": st.column_config.TextColumn(help="Optional - the AI fills it in"),
        },
    )

    if st.button("Save and analyse", type="primary"):
        questions: List[Question] = []
        for i, row in edited.iterrows():
            text = str(row["Question"]).strip()
            correct = str(row["Correct answer"]).strip()
            if not text or not correct:
                continue
            questions.append(
                Question(
                    number=len(questions) + 1,
                    text=text,
                    student_answer=str(row["Your answer"]).strip(),
                    correct_answer=correct,
                    topic=str(row["Topic"]).strip(),
                )
            )

        if not questions:
            st.warning("Add at least one question with a correct answer.")
            return

        test = service.submit_test(
            student_id=student["id"],
            name=name or "Untitled test",
            subject=subject,
            questions=questions,
            taken_on=taken_on.isoformat(),
            is_retest_of=retest_topic or None,
        )
        with st.spinner("Reading your answers…"):
            mistakes = service.analyse_test(test)

        st.success(
            f"Saved {test.name}: {test.score}% "
            f"({len(mistakes)} mistake{'s' if len(mistakes) != 1 else ''} analysed)."
        )
        st.session_state["selected_test"] = test.id
        if mistakes and st.button("Open the analysis"):
            goto("Mistake analysis")


def page_analysis(service: MistakeMindService, student) -> None:
    st.subheader("Mistake analysis")
    tests = service.store.list_tests(student["id"])
    mistakes = service.store.list_mistakes(student["id"])

    if not tests:
        st.info("No tests stored yet.")
        return

    labels = {t.id: f"{t.name} ({t.taken_on}) - {t.score}%" for t in tests}
    default = st.session_state.get("selected_test", tests[-1].id)
    ids = list(labels)
    chosen = st.selectbox(
        "Test",
        ids,
        index=ids.index(default) if default in ids else len(ids) - 1,
        format_func=lambda i: labels[i],
    )
    st.session_state["selected_test"] = chosen

    test_mistakes = [m for m in mistakes if m.test_id == chosen]
    test = next(t for t in tests if t.id == chosen)

    a, b, c = st.columns(3)
    a.metric("Score", f"{test.score}%")
    b.metric("Correct", f"{test.correct_count}/{test.total}")
    c.metric("Mistakes", len(test_mistakes))

    if not test_mistakes:
        st.success("Nothing wrong on this one.")
        return

    for m in test_mistakes:
        with st.expander(f"{m.question}  -  {m.mistake_type}", expanded=False):
            left, right = st.columns(2)
            left.error(f"**Your answer**\n\n{m.student_answer or '(left blank)'}")
            right.success(f"**Correct answer**\n\n{m.correct_answer}")
            st.write(m.reason)
            st.caption(
                f"Type: {m.mistake_type} · Topic: {m.topic} · "
                f"Confidence: {m.confidence} · Analysed by: {m.source}"
            )
            if m.recommendation:
                st.info(f"Next step: {m.recommendation}")

            k1, k2 = st.columns(2)
            if k1.button("Explain this more simply", key=f"why_{m.id}"):
                with st.spinner("Rewriting it plainly…"):
                    st.write(service.explain_simply(m))
            if k2.button(f"Practise {m.topic}", key=f"prac_{m.id}"):
                st.session_state["practice_topic"] = m.topic
                goto("Practice")


def page_patterns(service: MistakeMindService, student) -> None:
    st.subheader("Patterns")
    snap = service.snapshot(student["id"])
    if not snap["mistakes"]:
        st.info("Nothing to compare yet - add a couple of tests first.")
        return

    st.info(snap["pattern"])

    left, right = st.columns(2)
    with left:
        st.markdown("**Mistakes by topic**")
        st.bar_chart(
            pd.DataFrame(
                sorted(snap["topic_counts"].items(), key=lambda kv: -kv[1]),
                columns=["Topic", "Mistakes"],
            ).set_index("Topic"),
            height=280,
        )
    with right:
        st.markdown("**Mistakes by kind**")
        st.bar_chart(
            pd.DataFrame(
                sorted(snap["type_counts"].items(), key=lambda kv: -kv[1]),
                columns=["Kind", "Mistakes"],
            ).set_index("Kind"),
            height=280,
        )

    st.markdown("**Where the trouble sits, day by day**")
    if snap["heatmap"]:
        heat = pd.DataFrame(snap["heatmap"]).T.fillna(0).astype(int)
        try:  # shaded heatmap when matplotlib is installed
            st.dataframe(
                heat.style.background_gradient(cmap="Reds", axis=None),
                use_container_width=True,
            )
        except ImportError:
            st.dataframe(heat, use_container_width=True)
    else:
        st.caption("No mistakes recorded in the last seven days.")

    st.markdown("**Topics that have gone quiet**")
    streaks = [(t, n) for t, n in snap["streaks"] if n > 0]
    if streaks:
        st.dataframe(
            pd.DataFrame(streaks, columns=["Topic", "Clean tests in a row"]),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("Every weak topic has come back in your latest test.")

    with st.expander("What the six kinds of mistake mean"):
        for kind, meaning in MISTAKE_TYPE_HELP.items():
            st.markdown(f"**{kind}** - {meaning}")


def page_suggestions(service: MistakeMindService, student) -> None:
    st.subheader("What to do next")
    st.caption("Each line comes from your own stored mistakes, with the evidence attached.")

    suggestions = service.suggestions(student["id"])

    for i, s in enumerate(suggestions):
        with st.container(border=True):
            head, tail = st.columns([5, 1])
            head.markdown(
                f"{ACTION_ICON.get(s.action, '•')} **{s.title}**  \n{s.detail}"
            )
            head.caption(f"Why: {s.evidence}")
            tail.markdown(f"`{PRIORITY_LABEL.get(s.priority, 'Next')}`")
            if s.topic and s.action in {"practise", "revise"}:
                if tail.button("Practise", key=f"sg_prac_{i}"):
                    st.session_state["practice_topic"] = s.topic
                    goto("Practice")
            elif s.topic and s.action == "retest":
                if tail.button("Retest", key=f"sg_re_{i}"):
                    st.session_state["retest_topic"] = s.topic
                    goto("Retest")

    st.divider()
    st.markdown("**Today's study plan**")
    minutes = st.slider("Time available (minutes)", 20, 120, 60, step=10)
    if st.button("Build the plan"):
        with st.spinner("Allocating your time…"):
            plan = service.study_plan(student["id"], minutes)
        st.dataframe(
            pd.DataFrame(plan).rename(
                columns={"activity": "Activity", "minutes": "Minutes"}
            ),
            hide_index=True,
            use_container_width=True,
        )

    with st.expander("The list as a table"):
        st.dataframe(
            pd.DataFrame(suggestions_as_rows(suggestions)),
            hide_index=True,
            use_container_width=True,
        )


def page_practice(service: MistakeMindService, student) -> None:
    st.subheader("Practice")
    snap = service.snapshot(student["id"])
    topics = [t for t, _ in snap["weak_topics"]] or list(snap["topic_counts"])

    if not topics:
        st.info("Add a test first - practice is built from your mistakes.")
        return

    preset = st.session_state.get("practice_topic")
    c1, c2, c3 = st.columns(3)
    topic = c1.selectbox(
        "Topic", topics, index=topics.index(preset) if preset in topics else 0
    )
    difficulty = c2.selectbox("Level", ["Beginner", "Intermediate", "Advanced"])
    count = c3.number_input("Questions", 3, 15, 5)

    focus = sorted(
        {m.mistake_type for m in snap["mistakes"] if m.topic == topic}
    )
    if focus:
        st.caption(f"Targeting your {', '.join(f.lower() for f in focus)} mistakes in {topic}.")

    if st.button("Generate practice", type="primary"):
        with st.spinner("Writing questions for your weak spots…"):
            practice = service.create_practice(
                student["id"], topic, count=int(count), difficulty=difficulty
            )
        st.session_state["active_practice"] = practice.id
        st.success(f"{len(practice.questions)} questions ready.")

    sets = service.store.list_practice(student["id"])
    active_id = st.session_state.get("active_practice")
    active = next((p for p in sets if p.id == active_id), sets[-1] if sets else None)

    if active:
        st.markdown(f"**{active.topic}** · {active.difficulty} · {len(active.questions)} questions")
        for i, q in enumerate(active.questions, start=1):
            with st.expander(f"Q{i}. {q.get('question', '')}"):
                if q.get("hint"):
                    st.caption(f"Hint: {q['hint']}")
                if q.get("answer"):
                    st.write(f"Answer: {q['answer']}")
        c1, c2 = st.columns(2)
        score = c1.number_input("How many did you get right?", 0, len(active.questions), 0)
        if c2.button("Mark practice complete"):
            pct = round(100 * score / max(len(active.questions), 1), 1)
            service.complete_practice(active, pct)
            st.success(f"Logged at {pct}%. Now prove it with a retest.")
            st.session_state["retest_topic"] = active.topic


def page_retest(service: MistakeMindService, student) -> None:
    st.subheader("Retest")
    st.caption("Same concept, different questions. This is where improvement gets proved.")

    snap = service.snapshot(student["id"])
    topics = list(snap["topic_counts"])
    if not topics:
        st.info("No topics to retest yet.")
        return

    preset = st.session_state.get("retest_topic")
    topic = st.selectbox(
        "Topic", topics, index=topics.index(preset) if preset in topics else 0
    )

    from backend.analysis import topic_accuracy

    before_default = topic_accuracy(snap["tests"], topic)
    c1, c2 = st.columns(2)
    before = c1.number_input(
        "Accuracy before practice (%)", 0.0, 100.0, float(before_default), step=1.0
    )
    after = c2.number_input("Retest accuracy (%)", 0.0, 100.0, 0.0, step=1.0)

    if st.button("Record retest", type="primary"):
        result = service.record_retest(student["id"], topic, before, after)
        if result.improvement >= 0:
            st.success(f"{topic}: {before}% → {after}% (+{result.improvement} points)")
        else:
            st.warning(
                f"{topic}: {before}% → {after}% ({result.improvement} points). "
                "Worth another practice round before moving on."
            )

    history = service.store.list_retests(student["id"])
    if history:
        st.markdown("**Retest history**")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Topic": r.topic,
                        "Before": r.before_accuracy,
                        "After": r.after_accuracy,
                        "Improvement": r.improvement,
                        "Recorded": r.created_at[:10],
                    }
                    for r in history
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )


def page_history(service: MistakeMindService, student) -> None:
    st.subheader("Mistake history")
    mistakes = service.store.list_mistakes(student["id"])
    if not mistakes:
        st.info("Nothing stored yet.")
        return

    frame = pd.DataFrame(
        [
            {
                "Date": m.taken_on,
                "Test": m.test_name,
                "Subject": m.subject,
                "Topic": m.topic,
                "Kind": m.mistake_type,
                "Question": m.question,
                "Your answer": m.student_answer,
                "Correct": m.correct_answer,
                "Reason": m.reason,
            }
            for m in mistakes
        ]
    )

    f1, f2 = st.columns(2)
    subject = f1.selectbox("Subject", ["All"] + sorted(frame["Subject"].unique()))
    kind = f2.selectbox("Kind", ["All"] + sorted(frame["Kind"].unique()))
    view = frame
    if subject != "All":
        view = view[view["Subject"] == subject]
    if kind != "All":
        view = view[view["Kind"] == kind]

    st.dataframe(view, hide_index=True, use_container_width=True)
    st.download_button(
        "Download as CSV",
        view.to_csv(index=False).encode("utf-8"),
        file_name="mistake_history.csv",
        mime="text/csv",
    )


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    settings = get_settings()

    if "pending_nav" in st.session_state:
        st.session_state["nav"] = st.session_state.pop("pending_nav")

    if not current_student():
        auth_screen(settings)
        return

    service = get_service()
    student = current_student()
    service.ensure_student(student["id"], student["name"], student["email"])

    if st.session_state.pop("seed_demo_on_load", False):
        with st.spinner("Building the demo history…"):
            seed_demo(service, student["id"])

    with st.sidebar:
        st.markdown("## ✦ MistakeMind")
        st.caption(f"{student['name']} · {student['email']}")
        st.radio("Go to", PAGES, key="nav", label_visibility="collapsed")
        st.divider()
        st.caption(settings.describe())
        if not settings.use_gemini:
            st.caption("Set GEMINI_API_KEY for AI-written analysis.")
        if st.button("Reload demo data"):
            seed_demo(service, student["id"])
            st.success("Demo history rebuilt.")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()

    page = st.session_state.get("nav", PAGES[0])
    st.title(page)

    {
        "Dashboard": page_dashboard,
        "Add a test": page_add_test,
        "Mistake analysis": page_analysis,
        "Patterns": page_patterns,
        "Suggestions": page_suggestions,
        "Practice": page_practice,
        "Retest": page_retest,
        "History": page_history,
    }[page](service, student)


if __name__ == "__main__":
    main()
