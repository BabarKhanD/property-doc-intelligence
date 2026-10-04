"""Document processing, field extraction, retrieval and answering.

Pipeline:  PDF -> page text -> chunks (SQLite) -> structured fields -> TF-IDF retrieval
           -> answer (structured field, local LLM via Ollama, or extractive fallback)
           -> source document + page.
"""
import json
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from pypdf import PdfReader
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
SAMPLE_DIR = BASE_DIR / "sample_docs"
DB_PATH = DATA_DIR / "app.db"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MIN_SCORE = 0.10
NOT_FOUND_TEXT = "I couldn't find that information in the uploaded documents."

# ----------------------------------------------------------------------------- database

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    doc_type TEXT,
    path TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    pages INTEGER DEFAULT 0,
    status TEXT DEFAULT 'Processed',
    fields TEXT DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    found INTEGER NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    engine TEXT,
    asked_at TEXT NOT NULL
);
"""


def connect():
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
    conn.close()


# ----------------------------------------------------------------------------- text extraction

FOOTER = re.compile(r"^.*\bPage\s+\d+\s+of\s+\d+\b.*$", re.I | re.M)


def strip_repeated_edges(raw_pages):
    """Drop header/footer lines that repeat at the top/bottom edge of several pages."""
    def edge_idx(n):
        return set(range(min(2, n))) | set(range(max(0, n - 2), n))

    def norm(line):
        return re.sub(r"\d+", "#", line.strip().lower())

    pages = [[l for l in (p or "").splitlines() if l.strip()] for p in raw_pages]
    counts = {}
    for lines in pages:
        for key in {norm(lines[i]) for i in edge_idx(len(lines))}:
            counts[key] = counts.get(key, 0) + 1
    drop = {k for k, c in counts.items() if c >= 2} if len(pages) >= 2 else set()
    out = []
    for lines in pages:
        edges = edge_idx(len(lines))
        out.append("\n".join(l for i, l in enumerate(lines) if not (i in edges and norm(l) in drop)))
    return out


def clean_page(text):
    """Remove footers and tidy whitespace, but keep line breaks (needed for label fields)."""
    text = FOOTER.sub("", text or "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def flatten(text):
    return re.sub(r"\s+", " ", text).strip()


HEADINGISH = re.compile(r"(?:(?:\d+\.\d+|\d+\.|[A-D]\.)\s+[A-Za-z][\w/&'\- ]{0,50}\.?\s*)+")


def split_sentences(text):
    """Split into sentences / numbered clauses; short fragments and bare headings merge forward."""
    pattern = r'(?:(?<=[.!?])\s+(?=[A-Z0-9“"(])|\s+(?=\d{1,2}\.\d{1,2}\s+[A-Z]))'
    parts = [p.strip() for p in re.split(pattern, text) if p.strip()]
    merged, buf = [], ""
    for part in parts:
        buf = (buf + " " + part).strip()
        if len(buf) >= 40 and not (len(buf) <= 120 and HEADINGISH.fullmatch(buf)):
            merged.append(buf)
            buf = ""
    if buf:
        if merged:
            merged[-1] += " " + buf
        else:
            merged.append(buf)
    return merged


def make_chunks(page_text, max_chars=450):
    chunks, cur = [], ""
    for sent in split_sentences(flatten(page_text)):
        if cur and len(cur) + len(sent) + 1 > max_chars:
            chunks.append(cur)
            cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        chunks.append(cur)
    return chunks


# ----------------------------------------------------------------------------- classification & fields

def classify(first_page, name):
    head = (first_page[:300] + " " + name).lower()
    body = (first_page[:1500] + " " + name).lower()
    for text in (head, body):
        if "maintenance" in text:
            return "Maintenance Document"
        if re.search(r"\blease\b", text):
            return "Lease Agreement"
        if "rental" in text or "tenancy" in text:
            return "Rental Agreement"
    return "Other Document"


MONTHS = (r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
          r"Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?")
DATE = rf"({MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})"
MONEY = r"(\$\s?\d[\d,]*(?:\.\d{2})?)"
F = re.I | re.M

LINE_PATTERNS = [
    ("tenant", re.compile(r"^[ \t]*(?:Tenant|Resident|Lessee)(?:\(s\))?(?:[ \t]+Name)?[ \t]*:[ \t]*([^\n]+)$", F)),
    ("property", re.compile(r"^[ \t]*Property(?:[ \t]+Name)?[ \t]*:[ \t]*([^\n]+)$", F)),
    ("vendor", re.compile(r"^[ \t]*(?:Contractor|Vendor|Service[ \t]+Provider)[ \t]*:[ \t]*([^\n]+)$", F)),
]

UNIT_RE = re.compile(r"\bUnit\s*(?:No\.?|Number|#)?\s*[:#\-]?\s*([A-Za-z]?\d{1,4}[A-Za-z]?)\b", re.I)
TENANT_PROSE = re.compile(
    r"\band\s+([A-Z][\w'’\-]+(?:\s+[A-Z][\w'’\-.]*){1,3})\s*\(\s*[\"“”]?(?i:Tenant|Resident|Lessee)")
RANGE_RE = re.compile(
    rf"(?:term|period)\b[^.]{{0,80}}?{DATE}\s*(?:through|to|until|and ending on|–|-|—)\s*{DATE}", re.I)

FLAT_PATTERNS = [
    ("lease_start", re.compile(rf"(?:Lease\s+|Service\s+)?(?:Start|Commencement|Beginning)\s+Date\s*(?:is|:|-)?\s*{DATE}", re.I)),
    ("lease_start", re.compile(rf"commenc\w*\s+on\s+{DATE}", re.I)),
    ("lease_end", re.compile(rf"(?:End|Expiration|Termination)\s+Date\s*(?:is|:|-)?\s*{DATE}", re.I)),
    ("lease_end", re.compile(rf"(?:expires?|ends?|terminates?)\s+on\s+{DATE}", re.I)),
    ("monthly_rent", re.compile(rf"(?:Monthly\s+Rent|Rent\s+per\s+Month|Base\s+Rent)(?:(?!\bdeposit\b)[^$]){{0,80}}?{MONEY}", re.I)),
    ("monthly_rent", re.compile(rf"{MONEY}\s*(?:per|a|each|/)\s*month", re.I)),
    ("security_deposit", re.compile(rf"Security\s+Deposit(?:(?!\brent\b)[^$]){{0,80}}?{MONEY}", re.I)),
    ("monthly_fee", re.compile(rf"Monthly\s+(?:Service\s+)?Fee(?:(?!\bdeposit\b)[^$]){{0,100}}?{MONEY}", re.I)),
    ("emergency", re.compile(r"emergency[^.]{0,120}?within\s+(\d+(?:\.\d+)?\s*(?:minutes?|hours?))", re.I)),
]


def clean_value(val):
    val = re.sub(r"\s*\(.*$", "", val or "")
    val = val.strip(" \t.,;:_-")
    return val if re.search(r"[A-Za-z0-9]", val) else ""


def fmt_money(val):
    val = re.sub(r"\s+", "", val)
    return re.sub(r"\.00$", "", val)


def extract_fields(pages):
    """Return {key: {"value": str, "page": int}} using label/phrase patterns (first match wins)."""
    found = {}

    def put(key, val, page):
        val = (val or "").strip(" \t.,;:")
        if val and key not in found:
            found[key] = {"value": val, "page": page}

    for i, lined in enumerate(pages, 1):
        flat = flatten(lined)
        for key, pat in LINE_PATTERNS:
            m = pat.search(lined)
            if m:
                put(key, clean_value(m.group(1)), i)
        m = UNIT_RE.search(flat)
        if m:
            put("unit", m.group(1), i)
        m = TENANT_PROSE.search(flat)
        if m:
            put("tenant", clean_value(m.group(1)), i)
        for key, pat in FLAT_PATTERNS:
            m = pat.search(flat)
            if m:
                val = m.group(1)
                if key in ("monthly_rent", "security_deposit", "monthly_fee"):
                    val = fmt_money(val)
                put(key, val, i)
        m = RANGE_RE.search(flat)
        if m:
            put("lease_start", m.group(1), i)
            put("lease_end", m.group(2), i)
    return found


LEASE_FIELDS = [("tenant", "Tenant"), ("property", "Property"), ("unit", "Unit"),
                ("lease_start", "Lease start"), ("lease_end", "Lease end"),
                ("monthly_rent", "Monthly rent"), ("security_deposit", "Security deposit")]
MAINT_FIELDS = [("property", "Property"), ("vendor", "Contractor"),
                ("lease_start", "Service start"), ("lease_end", "Service end"),
                ("monthly_fee", "Monthly service fee"), ("emergency", "Emergency response")]
ALL_LABELS = dict(LEASE_FIELDS + MAINT_FIELDS)


def display_fields(doc_type, fields):
    if doc_type in ("Lease Agreement", "Rental Agreement"):
        spec = LEASE_FIELDS
    elif doc_type == "Maintenance Document":
        spec = MAINT_FIELDS
    else:
        spec = [(k, ALL_LABELS.get(k, k)) for k in fields]
    out = []
    for key, label in spec:
        f = fields.get(key)
        out.append({"label": label, "value": f["value"] if f else None, "page": f["page"] if f else None})
    return out


# ----------------------------------------------------------------------------- ingestion

def ingest_pdf(conn, path, name, uploaded_at=None):
    """Extract, chunk and index a PDF. Returns the new document id."""
    uploaded_at = uploaded_at or datetime.now().isoformat(timespec="seconds")
    rel = str(Path(path).resolve().relative_to(BASE_DIR))

    def insert(doc_type, pages, status, fields):
        cur = conn.execute(
            "INSERT INTO documents (name, doc_type, path, uploaded_at, pages, status, fields) VALUES (?,?,?,?,?,?,?)",
            (name, doc_type, rel, uploaded_at, pages, status, json.dumps(fields)))
        return cur.lastrowid

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            reader.decrypt("")
        raw_pages = strip_repeated_edges([p.extract_text() or "" for p in reader.pages])
    except Exception:
        return insert("Unknown", 0, "Failed", {})

    pages = [clean_page(t) for t in raw_pages]
    if not any(p.strip() for p in pages):
        return insert("Unknown", len(pages), "No text found", {})

    doc_type = classify(pages[0], name)
    doc_id = insert(doc_type, len(pages), "Processed", extract_fields(pages))
    for page_no, text in enumerate(pages, 1):
        for chunk in make_chunks(text):
            conn.execute("INSERT INTO chunks (doc_id, page, text) VALUES (?,?,?)", (doc_id, page_no, chunk))
    return doc_id


def doc_to_dict(row):
    d = dict(row)
    d["fields"] = json.loads(d.get("fields") or "{}")
    return d


def list_documents(conn):
    rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC, id DESC").fetchall()
    return [doc_to_dict(r) for r in rows]


def get_document(conn, doc_id):
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return doc_to_dict(row) if row else None


# ----------------------------------------------------------------------------- retrieval

def stem(word):
    """Very light stemmer so 'expires/expire/expiration' or 'terminate/termination' match."""
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("s") and not word.endswith("ss") and len(word) > 3:
        word = word[:-1]
    for suf in ("ing", "ed"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            word = word[: -len(suf)]
            break
    for suf in ("ation", "ate", "at", "e"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            word = word[: -len(suf)]
            break
    return word


def tokenize(text):
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in ENGLISH_STOP_WORDS]


UNIT_Q = re.compile(r"(?:\b(?:unit|apt\.?|apartment|suite)|#)\s*#?\s*([A-Za-z]?\d{1,4}[A-Za-z]?)\b", re.I)


def retrieve(question, rows, k=3):
    texts = [r["text"] for r in rows]
    vec = TfidfVectorizer(tokenizer=tokenize, lowercase=False, token_pattern=None, sublinear_tf=True)
    try:
        matrix = vec.fit_transform(texts)
    except ValueError:
        return [], vec
    q = vec.transform([question])
    if q.nnz == 0:
        return [], vec
    sims = cosine_similarity(q, matrix).ravel()
    order = sims.argsort()[::-1][:k]
    return [(rows[i], float(sims[i])) for i in order if sims[i] > 0], vec


def strip_clause(s):
    s = re.sub(r"^\s*\d+\.\s+[A-Z][A-Za-z ,&/']{2,60}?\s+(?=\d+\.\d+\s)", "", s)
    s = re.sub(r"^\s*(?:\d+\.\d+|[A-C]\.|\d+\.)\s+(?:[A-Z][\w/&'\-]*(?:\s+[A-Za-z/&'\-]+){0,3}[.:]\s+)?", "", s)
    return s.strip()


def extractive_answer(question, hits, vec):
    """Pick the single best-matching sentence across the top chunks. Returns (text, chunk_row)."""
    cands = [(sent, row) for row, _ in hits for sent in split_sentences(row["text"])]
    if not cands:
        return hits[0][0]["text"], hits[0][0]
    sims = cosine_similarity(vec.transform([question]), vec.transform([c[0] for c in cands])).ravel()
    best = int(sims.argmax())
    text, row = cands[best]
    if len(text) < 35 and best + 1 < len(cands) and cands[best + 1][1] is row:
        text += " " + cands[best + 1][0]
    return strip_clause(text), row


# ----------------------------------------------------------------------------- local LLM (optional)

_llm_cache = {"t": 0.0, "model": None}


def ollama_model():
    """Return the name of a local Ollama model if the server is running, else None."""
    now = time.time()
    if now - _llm_cache["t"] < 20:
        return _llm_cache["model"]
    model = None
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=0.7)
        names = [m["name"] for m in r.json().get("models", []) if "embed" not in m["name"]]
        want = os.environ.get("OLLAMA_MODEL")
        if want:
            model = next((n for n in names if n == want or n.startswith(want)), None)
        elif names:
            model = names[0]
    except Exception:
        model = None
    _llm_cache.update(t=now, model=model)
    return model


def llm_answer(question, hits, model):
    """Ask the local model using only the retrieved passages. Returns (text, index) or None on error."""
    passages = "\n".join(f"[{i}] ({r['name']}, page {r['page']}) {r['text']}" for i, (r, _) in enumerate(hits, 1))
    prompt = (
        "You answer questions about property documents. Use ONLY the numbered passages below. "
        "If the answer is not in the passages, reply exactly NOT_FOUND. Otherwise answer in one or two "
        "short sentences, then add a final line 'SOURCE: <passage number>'.\n\n"
        f"Passages:\n{passages}\n\nQuestion: {question}\nAnswer:")
    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", timeout=120, json={
            "model": model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0, "num_predict": 160}})
        out = r.json().get("response", "").strip()
    except Exception:
        return None
    if not out:
        return None
    if "NOT_FOUND" in out.upper():
        return "NOT_FOUND", 0
    m = re.search(r"SOURCE:\s*\[?(\d+)", out, re.I)
    idx = int(m.group(1)) - 1 if m and 0 < int(m.group(1)) <= len(hits) else 0
    text = re.sub(r"\n?\s*SOURCE:.*$", "", out, flags=re.I | re.S).strip()
    return text, idx


# ----------------------------------------------------------------------------- question answering

NOUN = {"Lease Agreement": "lease", "Rental Agreement": "rental agreement",
        "Maintenance Document": "maintenance agreement"}

INTENTS = [
    ("lease_end", re.compile(r"\b(expir\w*|ends?|ending|end date)\b", re.I),
     re.compile(r"\b(notice|renew\w*|early|penalt\w*|what happens|extend\w*)\b", re.I)),
    ("lease_start", re.compile(r"\b(start\w*|begin\w*|commenc\w*|move[- ]in)\b", re.I),
     re.compile(r"\b(notice|renew\w*|early)\b", re.I)),
    ("monthly_rent", re.compile(r"\brent\b", re.I),
     re.compile(r"\b(due|late|fee|increase|raise|deadline|when|pay\w*|grace|include\w*|waiv\w*|deposit)\b", re.I)),
    ("security_deposit", re.compile(r"\bdeposit\b", re.I),
     re.compile(r"\b(return\w*|refund\w*|within|days|pets?|when|deduct\w*|how long)\b", re.I)),
    ("tenant", re.compile(r"\b(tenant|resident|lessee|renter)\b", re.I),
     re.compile(r"responsib|repair|maint|clean|liable|handle|\bpays?\b", re.I)),
]


def detect_intent(question):
    for key, include, exclude in INTENTS:
        if include.search(question) and not exclude.search(question):
            if key == "tenant" and not re.search(r"\bwho\b|\bname\b", question, re.I):
                continue
            return key
    return None


def target_of(doc):
    f = doc["fields"]
    if "unit" in f:
        return f"Unit {f['unit']['value']}"
    if "property" in f:
        return f["property"]["value"]
    return f"“{doc['name']}”"


def sentence_for(intent, doc):
    v = doc["fields"][intent]["value"]
    t = target_of(doc)
    noun = NOUN.get(doc["doc_type"], "document")
    return {
        "lease_end": f"The {noun} for {t} expires on {v}.",
        "lease_start": f"The {noun} for {t} starts on {v}.",
        "monthly_rent": f"The monthly rent for {t} is {v}.",
        "security_deposit": f"The security deposit for {t} is {v}.",
        "tenant": f"The tenant of {t} is {v}.",
    }[intent]


def snippet_for(conn, doc_id, page, value, size=240):
    rows = conn.execute("SELECT text FROM chunks WHERE doc_id=? AND page=?", (doc_id, page)).fetchall()
    texts = [r["text"] for r in rows]
    text = next((t for t in texts if value.lower() in t.lower()), texts[0] if texts else "")
    if len(text) <= size:
        return text
    i = max(text.lower().find(value.lower()), 0)
    start, end = max(0, i - size // 2), min(len(text), i + size // 2)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def candidate_docs(conn, question):
    docs = [d for d in list_documents(conn) if d["status"] == "Processed"]
    m = UNIT_Q.search(question)
    unit = m.group(1) if m else None
    if unit:
        docs = [d for d in docs if "unit" in d["fields"] and d["fields"]["unit"]["value"].lower() == unit.lower()]
    else:
        q = question.lower()
        named = [d for d in docs if "property" in d["fields"] and d["fields"]["property"]["value"].lower() in q]
        docs = named or docs
        if re.search(r"\b(contractor|vendor|maintenance (?:agreement|contract)|service (?:agreement|contract|fee))\b",
                     question, re.I):
            maint = [d for d in docs if d["doc_type"] == "Maintenance Document"]
            docs = maint or docs
    return docs


def answer_from_fields(conn, question, docs):
    intent = detect_intent(question)
    if not intent:
        return None
    matches = [d for d in docs if intent in d["fields"]]
    if not matches:
        return None
    sources = []
    for d in matches:
        f = d["fields"][intent]
        sources.append({"doc_id": d["id"], "doc_name": d["name"], "page": f["page"],
                        "snippet": snippet_for(conn, d["id"], f["page"], f["value"])})
    return {"answer": "\n".join(sentence_for(intent, d) for d in matches), "found": True,
            "sources": sources, "engine": "Structured field extraction"}


def answer_from_retrieval(conn, question, docs, use_llm=True):
    ids = [d["id"] for d in docs]
    rows = conn.execute(
        "SELECT c.id, c.doc_id, c.page, c.text, d.name FROM chunks c JOIN documents d ON d.id=c.doc_id "
        f"WHERE c.doc_id IN ({','.join('?' * len(ids))})", ids).fetchall()
    query = UNIT_Q.sub(" ", question)
    hits, vec = retrieve(query, rows)
    if not hits or hits[0][1] < MIN_SCORE:
        return None

    model = ollama_model() if use_llm else None
    if model:
        out = llm_answer(question, hits, model)
        if out:
            text, idx = out
            if text == "NOT_FOUND":
                return None
            row = hits[idx][0]
            return {"answer": text, "found": True, "engine": f"Local LLM ({model})",
                    "sources": [{"doc_id": row["doc_id"], "doc_name": row["name"], "page": row["page"],
                                 "snippet": row["text"][:240]}]}

    text, row = extractive_answer(query, hits, vec)
    return {"answer": text, "found": True,
            "engine": "Built-in retrieval (no LLM)",
            "sources": [{"doc_id": row["doc_id"], "doc_name": row["name"], "page": row["page"],
                         "snippet": row["text"][:240]}]}


def ask(conn, question, use_llm=True, asked_at=None):
    question = question.strip()
    docs = candidate_docs(conn, question)
    result = None
    if docs:
        result = answer_from_fields(conn, question, docs) or answer_from_retrieval(conn, question, docs, use_llm)
    if not result:
        result = {"answer": NOT_FOUND_TEXT, "found": False, "sources": [], "engine": "No match in documents"}
    asked_at = asked_at or datetime.now().isoformat(timespec="seconds")
    with conn:
        cur = conn.execute(
            "INSERT INTO questions (question, answer, found, sources, engine, asked_at) VALUES (?,?,?,?,?,?)",
            (question, result["answer"], int(result["found"]), json.dumps(result["sources"]), result["engine"], asked_at))
    result.update(id=cur.lastrowid, question=question, asked_at=asked_at)
    return result


def recent_questions(conn, limit=5):
    rows = conn.execute("SELECT * FROM questions ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"])
        d["found"] = bool(d["found"])
        out.append(d)
    return out


# ----------------------------------------------------------------------------- sample data

SAMPLES = [  # (file, display name, days ago uploaded)
    ("Maple_Ridge_Maintenance_Service_Agreement.pdf", "Maple Ridge — Maintenance Service Agreement", 6),
    ("Unit_105_Rental_Agreement.pdf", "Unit 105 — Rental Agreement", 3),
    ("Unit_302_Lease_Agreement.pdf", "Unit 302 — Lease Agreement", 1),
]
SEED_QUESTIONS = [  # (question, minutes ago)
    ("Who is the tenant in Unit 105?", 190),
    ("What is the security deposit for Unit 105?", 150),
    ("How quickly must the contractor respond to emergency requests?", 95),
]


def seed_samples(conn):
    """Load the fictional sample documents (and a few example questions) on first run."""
    if conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]:
        return
    now = datetime.now()
    with conn:
        for fname, name, days in SAMPLES:
            path = SAMPLE_DIR / fname
            if path.exists():
                ingest_pdf(conn, path, name, (now - timedelta(days=days, hours=2)).isoformat(timespec="seconds"))
    for q, minutes in SEED_QUESTIONS:
        ask(conn, q, use_llm=False, asked_at=(now - timedelta(minutes=minutes)).isoformat(timespec="seconds"))
