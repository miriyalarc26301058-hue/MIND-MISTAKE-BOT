# MistakeMind

An AI system that works out **why** a student got a question wrong, finds the
mistakes that keep repeating, generates practice aimed at them, and retests to
check the practice worked.

```
TEST -> MISTAKE -> REASON -> PATTERN -> PRACTICE -> RETEST -> IMPROVEMENT -> repeat
```

| Layer | Technology |
|---|---|
| Frontend | Streamlit (Python) |
| Backend | Python |
| Database | Firebase (Firestore) |
| Authentication | Firebase Authentication |
| AI model | Gemini API (`gemini-1.5-flash`) |

---

## Run it in two minutes

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the app, pick **Try the demo**, and it builds four tests worth of analysed
history so every screen has something in it. No API key and no Firebase project
are needed for this — the app falls back to an offline analyser and a local JSON
file. That fallback exists so a live demo can never fail on a bad network.

To check the logic without the UI:

```bash
python tests_backend.py
```

---

## Turning on the real services

### Gemini

1. Get a key at <https://aistudio.google.com/app/apikey>
2. `cp .env.example .env` and set `GEMINI_API_KEY`

With the key present, every wrong answer goes to Gemini, which returns the
mistake type, topic, reason and recommendation as JSON. Without it, the
rule-based analyser in `backend/ai.py` does the same job less precisely.

### Firebase

1. Create a project at <https://console.firebase.google.com>
2. Build → Firestore Database → create in production mode
3. Build → Authentication → enable **Email/Password**
4. Project settings → Service accounts → **Generate new private key**, save it as
   `serviceAccountKey.json` in this folder
5. Project settings → General → copy the **Web API Key**
6. Fill `FIREBASE_CREDENTIALS`, `FIREBASE_PROJECT_ID` and `FIREBASE_WEB_API_KEY`
   in `.env`
7. Paste `firestore.rules` into Firestore → Rules and publish

The sidebar always shows which AI and which database are actually in use.

---

## How the code is arranged

```
app.py                   Streamlit UI only - draws screens, holds no logic
backend/
  config.py              env vars, and the decision of which services are live
  models.py              Student, Question, TestRecord, Mistake, PracticeSet,
                         RetestResult, Suggestion  (the Firestore shape)
  firebase_client.py     Firestore init + email/password auth (REST) + local auth
  store.py               FirestoreStore and LocalStore behind one interface
  ai.py                  Gemini prompts, JSON validation, offline fallback
  analysis.py            pattern detection, weak topics, heatmap, streaks,
                         improvement score   (pure functions, no I/O)
  suggestions.py         the suggestions list, each line with its evidence
  service.py             the flow that ties the above together
  seed.py                demo history
tests_backend.py         smoke test for everything except the UI
firestore.rules          a student can only touch their own documents
```

The UI never imports Firestore or Gemini directly. Everything goes through
`MistakeMindService`, so the database or the model can be swapped without
touching a screen.

### Firestore layout

```
students/{studentId}
students/{studentId}/tests/{testId}
students/{studentId}/mistakes/{mistakeId}
students/{studentId}/practice/{practiceId}
students/{studentId}/retests/{retestId}
```

---

## What the AI is asked to do

`backend/ai.py` holds four prompts, each one forced to return strict JSON that
is validated before anything is stored:

| Method | Job |
|---|---|
| `analyze_mistake` | classify one wrong answer: type, topic, reason, next step, confidence |
| `plain_explanation` | say the same thing again in three simple sentences |
| `practice_questions` | write questions aimed at one topic and one kind of error |
| `study_plan` | split the available minutes across the weak topics, ending in a retest |

Mistake types are fixed to six buckets so they can be counted over time:
**Conceptual, Calculation, Formula, Misread, Logical, Careless.**

---

## The suggestions list

`backend/suggestions.py` turns the stored history into a ranked list of what to
do next. Rules, in priority order:

1. a topic going wrong across several tests → practise it now
2. one kind of error dominating → change that habit
3. practised but never retested → retest it
4. weak topic with no practice yet → generate practice
5. accuracy sliding over three tests → clear the backlog before new topics
6. a topic gone quiet for several tests → keep it on light review
7. blank answers piling up → exam technique

Every suggestion carries the evidence that produced it ("3 mistakes across 3
tests"), which is the thing to point at in a demo.

---

## Screens

| Screen | What it does |
|---|---|
| Dashboard | accuracy, mistakes, weak topics, improvement score, accuracy trend |
| Add a test | enter questions and answers; wrong ones are analysed on save |
| Mistake analysis | per-question reason, type, topic, confidence, "explain more simply" |
| Patterns | mistakes by topic and by kind, day-by-day heatmap, clean streaks |
| Suggestions | the ranked list above, plus a study plan for today |
| Practice | generated questions for one weakness, logged when complete |
| Retest | before and after accuracy, improvement recorded |
| History | every mistake, filterable, downloadable as CSV |
