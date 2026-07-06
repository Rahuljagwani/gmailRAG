# Grove: Technical Documentation

Detailed technical reference for the Grove benefits reply assistant.

- **Live backend:** `https://email-rag-backend-ihyc.onrender.com` (`/health`, `POST /answer`)
- **Captured answers for all 5 sample emails:** [`outputs/`](outputs/)

---

## How it works (plain language)

1. **Ingest (offline, one-time).** Each of the 8 plan PDFs is parsed into text with a
   table-aware parser (`pdfplumber`), split into **section-sized chunks** (~1,395 total), and
   every chunk keeps metadata: which document, which section, page range, and the most recent
   *effective date* mentioned (see `backend/ingest/`).
2. **Index.** Chunks are upserted into a **Pinecone** vector index that embeds the text
   server-side (integrated embedding, `llama-text-embed-v2`), so there's no separate
   embedding key to manage. See `backend/ingest/build_index.py`.
3. **Retrieve.** For a question, Pinecone returns the most relevant chunks (dense semantic
   search, top 15 then top 5 sent to the model). See `backend/rag/retrieve.py`.
4. **Generate.** Claude (`claude-haiku-4-5`, swappable to Sonnet) answers **using only those chunks**, via a
   forced tool call that returns structured JSON: the drafted reply, a citation for every
   claim (document · section · page · quote), and a `has_clear_answer` flag. If the same
   figure appears under different effective dates, it uses the most recent and notes the older
   one. See `backend/rag/generate.py`.
5. **Serve.** A FastAPI endpoint (`POST /answer`) wraps this behind a shared-secret header.
   See `backend/app.py`.
6. **Gmail Add-on.** When you open an email, Grove sends it to the backend and renders the
   grounded draft, citation chips, and a ⚠ banner when unsupported. You can edit the draft
   and click **Insert into reply** to create a Gmail reply draft. See `addon/`.

```
Gmail Add-on ──HTTPS + X-API-Key──▶ FastAPI /answer ──▶ Pinecone (retrieve) ──▶ Claude (grounded JSON)
   (reads open email)                                                              │
   renders draft + citations ◀───────────────────────────────────────────────────┘
```

---

## Design choices & why

- **Separate FastAPI backend** (not calling APIs from Apps Script): keeps all keys
  server-side, and lets the whole RAG be tested from a CLI/eval before any Gmail wiring.
- **Pinecone with integrated embedding**: a persistent index that survives restarts and
  accepts live upserts of new plan-year docs, and drops the external embedding dependency
  entirely (text in, Pinecone embeds). Chosen for operational fit, not "scale".
- **Grounded generation with a strict contract**: structured JSON via a forced tool call
  (Claude 4.x doesn't support prefill), a citation for every claim, and an explicit
  `has_clear_answer=false` when the docs don't support an answer.
- **Effective-date metadata** on every chunk so the answer prefers the *current* value when a
  benefit is restated across plan years (this defuses the orthodontia $1,500-vs-$2,000 trap).
- **Retrieval "upgrade ladder"**: start with dense-only retrieval; only climb to reranking or
  hybrid search *if* evaluation shows misses. Evaluation showed dense-only was sufficient, so
  we stayed there (simpler by evidence, not assumption).

---

## What was most challenging

- **Trusting the numbers.** The whole task lives or dies on exact figures that sit inside
  tables (FSA limit, orthodontia in/out-of-network maximums). The hardest part was *verifying*
  those tables survived extraction before trusting any answer, and discovering that the dental
  document restates the ortho maximum at **multiple effective dates**: a naive system would
  confidently return the stale $1,500. The fix (effective-date metadata + a prompt rule to
  prefer the newest) is the piece I'm most glad we built.
- **A subtle structured-output bug.** One answer came back flagged "no clear answer" with zero
  citations *despite* a correct grounded draft. The cause wasn't the prompt: the long answer
  was exhausting the token budget and truncating the JSON before the flag/citations were
  emitted. Fixed by reordering the schema so control fields serialize first and raising the
  token limit. It was a good reminder to test against real data, not one happy path.

---

## How accuracy was checked

`backend/eval/` contains the 5 sample emails as structured data and a runner that executes
them end-to-end, dumping the answer + citations + retrieval trace to [`outputs/`](outputs/):

```bash
cd backend && python -m eval.run_eval
```

Results (all expectation checks pass):

| # | Question | Outcome |
|---|----------|---------|
| 1 | FSA 2026 limit | $3,300 max / $120 min, cited HCSA p4 |
| 2 | Ortho in/out max | $2,000 / $1,000; older 2017 $1,500 explicitly noted (conflict defused) |
| 3 | Travel to specialist | Answered from the Medical PPO travel provision, with citations |
| 4 | New administrator (CI/HI) | Coverage auto-carries to Securian; cites both docs |
| 5 | LTC enrollment | Enrollment steps cited; "same plan my manager has" flagged as unknowable |

Genuinely unanswerable questions (e.g. "which plan is my manager on?", "company stock price")
correctly return `has_clear_answer=false` with no citations. Two of the emails the brief hints
at as "traps" (#3, #4) turned out to be answerable from the corpus, so answering them (with
citations) is the correct behavior; only the personal-fact sub-part of #5 is truly unknowable.

---

## Setup from scratch

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env          # then fill in the values below
```

`.env` keys:

| Key | What |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` (or `claude-sonnet-4-6`) |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX` | your index name |
| `BACKEND_SHARED_SECRET` | any long random string (shared with the add-on) |

Create the Pinecone index as an **integrated-embedding** index ("Set up by model"): model
`llama-text-embed-v2`, embedded field named `text`, metric cosine.

### 2. Build the index & sanity-check

```bash
python -m ingest.chunk          # PDFs -> data/chunks.jsonl (~1,395 chunks)
python -m ingest.build_index    # upsert to Pinecone (embeds server-side)
python -m ingest.smoke_test     # confirm retrieval returns the right docs
```

### 3. Run / test the RAG locally

```bash
python cli.py "What is the 2026 FSA contribution limit and minimum?"
uvicorn app:app --reload --port 8000     # then curl /health and /answer
```

### 4. Deploy the backend

Deployed on **Render free tier** via the `render.yaml` blueprint (set the 4 secrets in the
dashboard), kept warm 24/7 by a free **UptimeRobot** monitor pinging `/health` every 5 min
(avoids cold starts without any paid plan). Any host that runs `uvicorn app:app` works.

### 5. Install the Gmail Add-on

1. [script.google.com](https://script.google.com) → **New project**; in **Project Settings**
   enable *"Show `appsscript.json` manifest file in editor"*.
2. Paste `addon/Code.gs` and `addon/Backend.gs`, and replace `appsscript.json` with
   `addon/appsscript.json`.
3. **Project Settings → Script Properties**, add `BACKEND_URL` (your backend base URL) and
   `SHARED_SECRET` (matching `BACKEND_SHARED_SECRET`).
4. **Deploy → Test deployments → Install**, authorize the scopes (on a personal Gmail you'll
   click through the "unverified app" screen, which is expected for an unpublished add-on).
5. Open any email in Gmail and click the **Grove** icon in the right sidebar.

---

## Assumptions

- No CRM/HR-record access, so plan-specific personal facts (e.g. "my manager's plan") are
  treated as unknowable and flagged, not guessed.
- The provided plan documents are the single source of truth; nothing external is used.
- Runs against a personal test Gmail with the add-on installed unpublished.

## What I'd do differently with more time

- **Only draft when it's a question worth answering.** Grove currently calls the model on
  every opened email; a cheap pre-check (or a one-click trigger) would save latency/cost on
  non-benefits mail.
- **Climb the retrieval ladder if needed at scale.** With more or messier documents, add
  Pinecone reranking then hybrid (sparse+dense) search; the code is structured so this is a
  change in `retrieve.py` only.
- **Automated citation-faithfulness checks** in the eval (verify each quote actually appears
  in the cited chunk) and a small regression suite over more question variants.
- **Richer add-on UX**: per-citation "view source" links and a tone/length selector.

## Repo layout

Key folders: `backend/ingest` (parse + chunk + index), `backend/rag` (retrieve + generate +
orchestrate), `backend/eval` (5-email evaluation), `addon/` (Apps Script add-on), `outputs/`
(captured answers for the 5 emails).
