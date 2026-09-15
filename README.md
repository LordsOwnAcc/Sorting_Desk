# The Sorting Desk — Intelligent Resume Screening & Ranking

A single-service web app: paste a job description, drop in a pile of resumes,
get them read, scored, and ranked in seconds. Built to run in one command —
no separate frontend build, no external API keys.

## How it works

1. **Intake** — paste a job title, description, and (optionally) a comma-separated
   list of required skills.
2. **Upload** — drag in resumes (PDF, DOCX, or TXT). Upload as many as you want at once.
3. **Screen** — the backend:
   - extracts text from every resume (`pdfplumber` for PDF, `python-docx` for DOCX)
   - pulls out name / email / phone with regex
   - detects skills against a ~90-term tech skill dictionary
   - scores each resume with TF-IDF cosine similarity against the job description
     (content match), blended with required-skill coverage, into one 0–100 score
   - ranks candidates highest to lowest
4. **Results** — a sortable, searchable, ranked list of candidates as "dossiers,"
   each showing the match score, matched vs. missing required skills, contact
   info, and a link to the original resume file.
5. **Past roles** — every job you open and every batch of resumes you screen is
   saved to a local SQLite database, so you can come back to it.

## Run it

```bash
cd resume-screener
pip install -r requirements.txt
python app.py
```

Then open **http://127.0.0.1:5000** in your browser. That's it — Flask serves
both the API and the frontend from the same process.

Requires Python 3.9+. No internet connection or API key needed at runtime —
everything (parsing, scoring, ranking) runs locally.

## Project structure

```
resume-screener/
├── app.py            Flask routes: jobs, upload/screen, candidate list, resume download
├── parser.py          Text extraction + name/email/phone/skill extraction
├── ranker.py           TF-IDF similarity + skill coverage → final score
├── requirements.txt
├── templates/
│   └── index.html    Single-page frontend shell
├── static/
│   ├── style.css      "Sorting Desk" visual design
│   └── script.js       All frontend logic (fetch calls, rendering, drag-drop)
├── uploads/            Uploaded resumes, stored per job (created at runtime)
└── instance/
    └── screener.db     SQLite database (created at runtime)
```

## Notes for the demo

- The scoring is fully explainable: every candidate card shows *why* they
  ranked where they did — content-match % and which required skills were
  found vs. missing. That's worth pointing out live; it's not a black box.
- Try one very strong resume and one clearly mismatched resume (e.g. a
  frontend resume against a backend JD) side by side — the ranking gap
  makes the demo land immediately.
- The "Past roles" tab is a nice second beat: open a role, screen a batch,
  switch tabs, come back — shows persistence without extra explanation.
- If you want to extend this afterward: swapping TF-IDF for a sentence-embedding
  model (e.g. `sentence-transformers`) would improve semantic matching at the
  cost of a heavier dependency — worth mentioning as a "next step" if asked
  about scaling this up.

## Known limitations (worth knowing, not worth hiding)

- Name extraction is a heuristic (first short, non-email, non-numeric line) —
  works for most standard resume layouts but can be wrong on heavily designed
  templates.
- Skill detection is dictionary-based, not a full NLP entity extractor — it
  will miss skills outside the built-in vocabulary (easy to extend: add
  terms to `SKILL_VOCAB` in `parser.py`).
- SQLite + local file storage is intentionally simple for a one-machine demo;
  a real deployment would move to Postgres + object storage (S3-style) and
  add auth.
