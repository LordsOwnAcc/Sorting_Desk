"""
Ranking engine: combines TF-IDF cosine similarity (overall content match
between resume and job description) with explicit required-skill coverage
into one 0-100 match score per candidate.
"""
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def content_similarity(job_text: str, resume_texts: list) -> list:
    """Return cosine similarity (0-1) of each resume against the job text."""
    if not resume_texts:
        return []
    corpus = [job_text] + resume_texts
    try:
        vec = TfidfVectorizer(stop_words="english", max_features=5000)
        matrix = vec.fit_transform(corpus)
        sims = cosine_similarity(matrix[0:1], matrix[1:]).flatten()
    except ValueError:
        # Empty vocabulary (e.g. all resumes failed to parse)
        sims = [0.0] * len(resume_texts)
    return [float(s) for s in sims]


def skill_coverage(required_skills: list, candidate_skills: list) -> dict:
    if not required_skills:
        return {"matched": [], "missing": [], "pct": None}
    req_lower = {s.lower(): s for s in required_skills}
    cand_lower = {s.lower() for s in candidate_skills}
    matched = [orig for low, orig in req_lower.items() if low in cand_lower]
    missing = [orig for low, orig in req_lower.items() if low not in cand_lower]
    pct = len(matched) / len(required_skills) * 100
    return {"matched": matched, "missing": missing, "pct": pct}


def score_single(job_text: str, required_skills: list, resume_text: str, skills: list) -> dict:
    """Score one resume against one job. Returns similarity/skill_match/score."""
    sims = content_similarity(job_text, [resume_text])
    sim_pct = round(sims[0] * 100, 1) if sims else 0.0
    coverage = skill_coverage(required_skills, skills)
    if coverage["pct"] is None:
        final = sim_pct
    else:
        final = 0.55 * sim_pct + 0.45 * coverage["pct"]
    return {
        "similarity": sim_pct,
        "skill_match_pct": round(coverage["pct"], 1) if coverage["pct"] is not None else None,
        "matched_skills": coverage["matched"],
        "missing_skills": coverage["missing"],
        "score": round(final, 1),
    }


def compute_scores(job_text: str, required_skills: list, candidates: list) -> list:
    """
    candidates: list of dicts each with 'resume_text' and 'skills'.
    Mutates & returns the list, adding 'similarity', 'skill_match', 'score'.
    Weighting: if required skills were given, 55% content similarity + 45%
    skill coverage. Otherwise, 100% content similarity.
    """
    sims = content_similarity(job_text, [c["resume_text"] for c in candidates])
    for cand, sim in zip(candidates, sims):
        coverage = skill_coverage(required_skills, cand["skills"])
        cand["matched_skills"] = coverage["matched"]
        cand["missing_skills"] = coverage["missing"]
        sim_pct = sim * 100
        if coverage["pct"] is None:
            final = sim_pct
        else:
            final = 0.55 * sim_pct + 0.45 * coverage["pct"]
        cand["similarity"] = round(sim_pct, 1)
        cand["skill_match_pct"] = round(coverage["pct"], 1) if coverage["pct"] is not None else None
        cand["score"] = round(final, 1)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    for i, c in enumerate(candidates, start=1):
        c["rank"] = i
    return candidates
