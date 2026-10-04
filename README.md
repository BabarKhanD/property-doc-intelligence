# AI Property Document Intelligence

A small portfolio demo showing how AI can help property managers understand and search leases,
rental agreements and maintenance documents. Upload a PDF, see the extracted key terms, ask a
question in plain English, and get an answer **with the source document and page number**.

> All sample documents, names and figures are fictional. Nothing here is a real client, result or statistic.

## How it works

**Problem → Document processing → Retrieval → AI answer → Source citation**

1. **Problem.** Key lease terms (end date, rent, deposit, who maintains what) are buried in PDFs. Staff lose time opening files and scrolling.
2. **Document processing.** On upload, `pypdf` extracts the text of every page. Repeating headers/footers are removed, each page is split into small clause-sized chunks, and everything is stored in SQLite with its page number. Pattern matching also pulls out key fields (tenant, property, unit, lease start/end, monthly rent, security deposit), remembering the page each came from.
3. **Retrieval.** A question is matched against the chunks with TF-IDF similarity (scikit-learn). If a unit or property is named ("Unit 302"), the search is limited to the matching documents.
4. **AI answer.** Three layers, all free and local:
   - *Structured fields*: questions like "when does the lease expire?" or "what is the rent?" are answered directly from the extracted fields.
   - *Local LLM (optional)*: if [Ollama](https://ollama.com) is running, the top passages are sent to a local model with the instruction to answer only from them (or say it was not found).
   - *Built-in fallback*: with no LLM installed, the best-matching sentence from the retrieved passages is returned. The demo works fully without any model.
5. **Source citation.** Every answer shows the document name and page (the link opens the PDF at that page) plus the supporting text. If nothing relevant is found, the app says so instead of guessing.

## Run it on Windows

Requires Python 3.10+ (check with `python --version`). In PowerShell or Command Prompt:

```bat
cd property-doc-intelligence
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**. The three sample documents and a few example questions load automatically on first run.

PowerShell blocks activation? Run `Set-ExecutionPolicy -Scope Process RemoteSigned` first, or use Command Prompt.

### Optional: use a local LLM (free)

1. Install Ollama from https://ollama.com
2. Run `ollama pull llama3.2` (or another small model)
3. Restart `python app.py`. The badge at the top right changes to "Local LLM (...)".

Set a specific model with `set OLLAMA_MODEL=llama3.2` before starting the app.

## 60–90 second demo script

1. Open the dashboard and point out the Documents table.
2. Click **Unit 302 — Lease Agreement**. The Extracted Information card fills in (tenant, unit, dates, rent, deposit, each with its page).
3. Ask: *When does the lease for Unit 302 expire?* → answer + **Source: Unit 302 — Lease Agreement — Page 3**.
4. Ask: *What is the monthly rent for Unit 302?* → answer + source on Page 2.
5. Optional: ask something unrelated (*What is the capital of France?*) to show the "not found" behaviour, or upload your own PDF.

## Project layout

```
app.py                 Flask app and API routes
processing.py          Extraction, chunking, field detection, retrieval, answering, SQLite
generate_samples.py    Recreates the fictional sample PDFs (optional)
sample_docs/           3 fictional PDFs: Unit 302 lease, Unit 105 rental agreement, maintenance agreement
templates/, static/    Dashboard UI (HTML, CSS, JavaScript)
data/                  Created on first run: app.db (SQLite) and uploads/
```

## Notes and limits

- Field extraction is pattern-based. It works well on labelled or conventional phrasing (as in the samples); unusual layouts may leave fields as "Not found".
- Scanned PDFs (images without text) are flagged "No text found". OCR is not included.
- The fallback answer is lexical (keyword-based); an optional local LLM gives more natural answers for open-ended questions.
- To reset the demo, stop the app and delete the `data` folder. It is rebuilt on the next start.
