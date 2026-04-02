# HaloDesk

HaloDesk is a local-first desktop assistant for email, documents, scheduling, memory, and live web research. It runs a planner-executor-evaluator loop on top of a local LLM, keeps a searchable memory store, and can redact personal data before model calls.

## What HaloDesk Does

- Handles natural-language requests across email, files, calendar, memory, and research.
- Uses Ollama for local model execution.
- Uses Linkup only when fresh web context is needed.
- Stores recent work in SQLite and semantic memory in FAISS.
- Produces downloadable `.eml` and `.ics` files for drafts, events, and reminders.
- Supports a browser UI with file attachments and an AI View panel for redaction inspection.

## Core Workflow

HaloDesk processes requests in four stages:

1. Privacy layer redacts names and structured PII before the model sees the input.
2. Planner breaks the request into executable steps.
3. Executor calls the right tools and enforces scheduling guardrails.
4. Evaluator checks whether each step succeeded and retries when needed.

## Included Tooling

- Web research through Linkup
- Inbox listing and email reading
- Email draft generation
- Document listing, reading, and summarization
- Calendar lookup
- Event and reminder creation
- Memory write and memory recall

## Run Locally

### Requirements

- Python 3.10+
- Ollama running locally
- A Linkup API key

### Setup

```bash
pip install -r requirements.txt
ollama pull llama3.1:8b
export LINKUP_API_KEY="your-key-here"
python server.py
```

Open `http://localhost:5000`.

### Optional Privacy Upgrade

```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_sm
```

If those packages are missing, HaloDesk falls back to regex-based redaction.

## Project Layout

```text
.
├── agent/        # Planning, execution, evaluation, prompts
├── config/       # Default configuration
├── data/         # Demo inputs, generated files, runtime storage
├── docs/         # Architecture and demo notes
├── frontend/     # Browser UI
├── memory/       # SQLite and FAISS layers
├── tools/        # Tool adapters and privacy logic
├── main.py       # CLI entry point
└── server.py     # Flask server
```

## Local Endpoints

- `GET /api/health` checks runtime readiness
- `POST /api/chat` sends a message with optional attachments
- `GET /api/tasks` returns recent task history
- `GET /api/memory` returns recent semantic memory matches
- `GET /api/privacy` reports the active redaction engine

## Notes

- Calendar writes are blocked unless the request includes a specific date and time.
- Generated drafts and events restore real names before file output.
- Demo calendar and mailbox data are seeded so the app is usable on first launch.
