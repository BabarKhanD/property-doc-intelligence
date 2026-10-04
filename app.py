"""AI Property Document Intelligence — Flask app."""
import os
import re
import time
from contextlib import closing
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file

import processing as P

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB upload limit


def db():
    return closing(P.connect())


def doc_json(d):
    return {"id": d["id"], "name": d["name"], "doc_type": d["doc_type"], "uploaded_at": d["uploaded_at"],
            "pages": d["pages"], "status": d["status"],
            "fields": P.display_fields(d["doc_type"], d["fields"])}


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    model = P.ollama_model()
    return jsonify({"engine": f"Local LLM ({model})" if model else "Built-in retrieval (no LLM detected)",
                    "llm": bool(model)})


@app.get("/api/documents")
def documents():
    with db() as conn:
        return jsonify([doc_json(d) for d in P.list_documents(conn)])


@app.get("/api/documents/<int:doc_id>")
def document(doc_id):
    with db() as conn:
        d = P.get_document(conn, doc_id)
    if not d:
        abort(404)
    return jsonify(doc_json(d))


@app.get("/files/<int:doc_id>")
def files(doc_id):
    with db() as conn:
        d = P.get_document(conn, doc_id)
    if not d:
        abort(404)
    return send_file(P.BASE_DIR / d["path"], mimetype="application/pdf")


@app.post("/api/upload")
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file received."}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Please upload a PDF file."}), 400
    stem = re.sub(r"[^A-Za-z0-9_.\-]+", "_", Path(f.filename).stem) or "document"
    dest = P.UPLOAD_DIR / f"{int(time.time())}_{stem}.pdf"
    P.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    f.save(dest)
    name = re.sub(r"[_]+", " ", Path(f.filename).stem).strip()
    with db() as conn:
        with conn:
            doc_id = P.ingest_pdf(conn, dest, name)
        d = P.get_document(conn, doc_id)
    return jsonify(doc_json(d)), 201


@app.post("/api/ask")
def ask():
    question = ((request.get_json(silent=True) or {}).get("question") or "").strip()
    if not question:
        return jsonify({"error": "Please enter a question."}), 400
    with db() as conn:
        return jsonify(P.ask(conn, question[:500]))


@app.get("/api/questions")
def questions():
    with db() as conn:
        return jsonify(P.recent_questions(conn, 5))


def startup():
    P.init_db()
    with db() as conn:
        P.seed_samples(conn)


startup()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  AI Property Document Intelligence running at http://127.0.0.1:{port}\n")
    app.run(host="127.0.0.1", port=port, debug=False)
