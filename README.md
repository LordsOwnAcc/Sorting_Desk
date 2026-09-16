# The Sorting Desk — Intelligent Resume Screening & Ranking

A two-sided job board: recruiters post roles and get applicants ranked
automatically; candidates browse open roles and apply with a resume. Runs as
a single Flask service — no separate frontend build, no external API keys.

## How it works

**Recruiters**
1. Register / sign in as a **Recruiter**.
2. **Post a role** — title, description, and (optionally) required skills.
3. Candidates can now find and apply to it from their own portal. You can
   also **upload resumes directly** on the same page if you already have
   some on hand — they're screened into the same ranked list.
4. Every application is scored with TF-IDF cosine similarity against the job
   description, blended with required-skill coverage, into one 0–100 score,
   and ranked automatically.
5. On the **results** page for a role, **shortlist** or **reject** any
   applicant, filter by status, and open an applicant's **timeline** to see
   every event — applied, viewed, shortlisted/rejected — with timestamps.
6. **Past roles** lists everything you've posted, with applicant and
   shortlist counts.

**Candidates**
1. Register / sign in as a **Candidate**.
2. **Open roles** lists every open posting across all recruiters. Apply
   directly with one resume file.
3. **My applications** shows where each application stands (applied /
   viewed / shortlisted / rejected) and lets you open its timeline.

Under the hood: `pdfplumber` / `python-docx` extract resume text, a ~90-term
skill dictionary tags detected skills, and `scikit-learn`'s TF-IDF + cosine
similarity scores content match. Auth is session-based with hashed
passwords (`werkzeug.security`) — no third-party auth provider needed.

## Run it

```bash
cd resume-screener
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** — it redirects to `/login`. Create one
recruiter account and one candidate account (two different emails) to try
the full flow yourself.

Requires Python 3.9+. Nothing runs over the network at runtime except
Google Fonts for the UI — parsing, scoring, and ranking are all local.

## Project structure

```
resume-screener/
├── app.py              Flask routes: auth, jobs, applications, status, timeline
├── auth.py              Session auth: register/login, password hashing, role decorators
├── parser.py            Resume text extraction + name/email/phone/skill extraction
├── ranker.py             TF-IDF similarity + skill coverage → score (batch and single)
├── requirements.txt
├── .python-version       Pins Python 3.12 (see Deploying to Render below)
├── templates/
│   ├── login.html       Sign in / register (role picker: recruiter or candidate)
│   ├── recruiter.html    Post roles, upload resumes, ranked results, shortlist, timeline
│   └── candidate.html    Browse open roles, apply, track applications, timeline
├── static/
│   ├── style.css         Shared visual design
│   ├── auth.js            Login/register page logic
│   ├── recruiter.js        Recruiter dashboard logic
│   └── candidate.js        Candidate portal logic
├── uploads/              Uploaded resumes, stored per job (created at runtime)
└── instance/
    └── screener.db        SQLite database (created at runtime)
```

## Data model

- **users** — id, email, password hash, name, role (`recruiter`/`candidate`)
- **jobs** — id, recruiter_id, title, description, required_skills, status
- **candidates** (applications) — one row per applicant per job: linked to a
  `user_id` if a candidate applied through the portal, or `NULL` if a
  recruiter uploaded it directly; score, matched/missing skills, current
  `status`
- **application_events** — the timeline: every status change for a given
  application, each with its own timestamp

If you already have an old `instance/screener.db` from before this version,
the app adds the new columns automatically on startup (a small migration
step in `init_db()`), so you don't need to delete it — though a fresh DB is
simplest if you don't need the old data.

## Notes for the demo

- Have two browser windows (or one normal + one incognito) open — one
  logged in as a recruiter, one as a candidate — so you can post a role in
  one window and apply to it live from the other. That's the moment that
  sells the "one platform, two sides" pitch.
- The timeline is the feature worth lingering on: applied → viewed →
  shortlisted, each with a real timestamp, visible to both sides. It's what
  makes this feel like an actual applicant tracking system rather than a
  one-shot scoring script.
- Every score is explainable — content-match % and matched/missing skills
  are shown right on the card, not hidden behind the number.

## Deploying to Render

- The included `.python-version` file pins Python to `3.12` so Render
  doesn't fall back to a very new default version without solid
  `numpy`/`scikit-learn` wheel support yet.
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Set a `SECRET_KEY` environment variable in Render's dashboard to
  something random — the app falls back to a hardcoded dev key otherwise,
  which is fine locally but not once this is public.
- Free-tier disk is ephemeral: uploaded resumes and the SQLite DB reset on
  every redeploy/restart. Fine for a demo, not for long-term storage.

## Known limitations (worth knowing, not worth hiding)

- Name extraction is a heuristic (first short, non-email, non-numeric line)
  — works for most standard resume layouts but can be wrong on heavily
  designed templates.
- Skill detection is dictionary-based, not a full NLP entity extractor — it
  will miss skills outside the built-in vocabulary (easy to extend: add
  terms to `SKILL_VOCAB` in `parser.py`).
- Auth is intentionally minimal for a demo: no email verification, password
  reset, or rate limiting on login attempts.
- SQLite + local file storage is fine for a one-machine demo; a real
  deployment would move to Postgres + object storage and add those auth
  hardening steps.
