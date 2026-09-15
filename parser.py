"""
Resume parsing: pull raw text out of PDF / DOCX / TXT files,
then lift out name / email / phone / skills with regex + a skill dictionary.
"""
import re
import os
import pdfplumber
import docx

# A reasonably broad tech-skill vocabulary. Matching is case-insensitive and
# word-boundary aware so "R" doesn't match inside "R&D" etc.
SKILL_VOCAB = [
    # Languages
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "C", "Go", "Golang",
    "Rust", "Kotlin", "Swift", "PHP", "Ruby", "Scala", "R", "MATLAB", "Dart",
    # Web / Backend
    "React", "Angular", "Vue", "Node.js", "Node", "Express", "Django", "Flask",
    "FastAPI", "Spring", "Spring Boot", "REST API", "REST", "GraphQL", "HTML",
    "CSS", "Tailwind", "Bootstrap", "Next.js", "jQuery",
    # Data / ML
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "TensorFlow",
    "PyTorch", "Keras", "Scikit-learn", "Pandas", "NumPy", "OpenCV",
    "Data Analysis", "Data Science", "Statistics",
    # Databases
    "SQL", "MySQL", "PostgreSQL", "MongoDB", "Redis", "SQLite", "Oracle",
    "Firebase", "Cassandra", "DynamoDB",
    # DevOps / Cloud
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Jenkins", "CI/CD", "Git",
    "GitHub", "GitLab", "Linux", "Terraform", "Ansible", "Nginx",
    # Mobile
    "Android", "iOS", "Jetpack Compose", "React Native", "Flutter",
    # Other
    "Agile", "Scrum", "Microservices", "System Design", "OOP", "DSA",
    "Data Structures", "Algorithms", "Testing", "JUnit", "Selenium",
    "Kafka", "RabbitMQ", "GraphDB", "Tableau", "Power BI", "Excel",
]

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}(?:[-.\s]?\d{2,4})?"
)
MIN_PHONE_DIGITS = 10


def extract_text(filepath: str) -> str:
    """Return plain text content of a resume file (pdf/docx/txt)."""
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    try:
        if ext == ".pdf":
            with pdfplumber.open(filepath) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        elif ext in (".docx", ".doc"):
            d = docx.Document(filepath)
            text = "\n".join(p.text for p in d.paragraphs)
        elif ext == ".txt":
            with open(filepath, "r", errors="ignore") as f:
                text = f.read()
    except Exception as e:
        text = ""
    return text.strip()


def guess_name(text: str, fallback: str) -> str:
    """Very light heuristic: first non-empty line that looks like a name
    (short, no @ or digits, mostly alphabetic words)."""
    for line in text.splitlines()[:8]:
        line = line.strip()
        if not line or len(line) > 45:
            continue
        if "@" in line or any(ch.isdigit() for ch in line):
            continue
        words = line.split()
        if 1 <= len(words) <= 4 and all(w.replace(".", "").isalpha() for w in words):
            return line.title()
    return fallback


def extract_contact(text: str, fallback_name: str) -> dict:
    email_m = EMAIL_RE.search(text)
    phone = "Not found"
    for m in PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) >= MIN_PHONE_DIGITS:
            phone = m.group(0).strip()
            break
    return {
        "name": guess_name(text, fallback_name),
        "email": email_m.group(0) if email_m else "Not found",
        "phone": phone,
    }


def extract_skills(text: str) -> list:
    found = []
    lower = text.lower()
    for skill in SKILL_VOCAB:
        pattern = r"(?<![a-zA-Z0-9])" + re.escape(skill.lower()) + r"(?![a-zA-Z0-9])"
        if re.search(pattern, lower):
            found.append(skill)
    return sorted(set(found))
