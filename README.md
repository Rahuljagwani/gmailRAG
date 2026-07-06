# Grove: AI-Drafted Benefits Email Replies (Gmail Add-on)

Grove is a Gmail sidebar add-on for benefits account managers. Open an employee's email and it
drafts a reply using only the company's plan documents, shows which document and section each
fact came from, and warns you when the documents don't actually answer the question. You can
edit the draft and insert it into a reply without leaving Gmail.

**Setup:** step-by-step instructions are in `TECHNICAL_DOCUMENT.md`, see
[Backend setup](TECHNICAL_DOCUMENT.md#1-backend) and
[Gmail Add-on install](TECHNICAL_DOCUMENT.md#5-install-the-gmail-add-on).

## How the retrieval/answer logic works

The 8 plan PDFs are split into small, section-sized pieces and stored in a searchable index.
When an email arrives, Grove searches that index for the few pieces most relevant to the
question and hands only those to Claude, with strict instructions: answer only from these
pieces, cite the document and section behind every claim, and if the pieces don't contain the
answer, say so rather than guess.

## Design choices & why

- **Real retrieval, not stuffing every PDF into the prompt:** the system finds the relevant
  document(s) per question, which keeps answers grounded and citations honest.
- **A small backend service behind the add-on:** keeps API keys off Google's servers and lets
  the whole answer engine be tested before touching Gmail.
- **Each piece remembers its "effective date":** plans get restated year to year, so Grove
  quotes the most recent figure and flags the older one.
- **Kept deliberately simple:** plain semantic search already got all 5 emails right, so no
  extra machinery was added without evidence it was needed.

## What was most challenging

Trusting the numbers. The key answers (FSA limits, orthodontia maximums) live inside PDF
tables, so I had to confirm the tables survived text extraction, and I found the dental plan
states its orthodontia maximum at two different effective dates. A naive system would
confidently quote the outdated value; handling that conflict correctly was the crux.

## How I checked accuracy

I turned the 5 sample emails into a small test that runs the full pipeline and records each
answer, its citations, and what was retrieved. I checked the right document was retrieved, the
exact figures appeared, and the "no clear answer" flag fired only when it should. All 5 pass,
including the conflict trap and the genuinely unanswerable parts (e.g. "the same plan my
manager has").

## What I'd do differently with more time

Adopt techniques from Anthropic's Contextual Retrieval:

- **Contextual embeddings:** prepend a short LLM-written summary of each piece's place in its
  document before indexing, so pieces aren't stripped of context.
- **Hybrid search (BM25 + semantic):** add keyword matching to nail exact strings like dollar
  amounts and plan codes, then fuse the rankings.
- **Reranking:** retrieve a wider net, then rerank to keep only the best few pieces.
- These stack: Anthropic reports ~49% fewer retrieval misses, ~67% with reranking added.

Plus: only draft on genuine benefits questions, and auto-verify each quote appears in its cited source.

Each citation already names the document, section, page, and an exact quote, so the source is
easy to find; with more time the citations could also link straight to the plan PDF (e.g. the
files in Google Drive) to open the document in one click.
