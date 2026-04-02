# System Architecture

> **Interactive diagram**: Open `docs/architecture_diagram.html` in a browser for an animated, clickable version of this architecture.

## Overview

The Desktop Intelligence Agent follows a **Planner → Executor → Evaluator** loop with a privacy-first design. User input passes through a PII redaction layer before the LLM ever sees it, tool calls are executed with hard guardrails (scheduling gate, integrity checks), and generated files have real names restored before delivery.

## Data Flow

```
User Input (natural language + optional file attachments)
    │
    ▼
┌─────────────────────────────────┐
│  Privacy Layer (PII Redaction)  │  "email to karthik" → "email to <PERSON_1>"
│  Presidio NLP / Regex fallback  │  Keeps: company names, dates, locations, roles
└──────────────┬──────────────────┘
               │
               ▼
┌───────────────────────────────────────────────────────────────────┐
│  Agent Core                                                       │
│                                                                   │
│  ┌──────────┐    ┌──────────┐   ┌──────────┐    ┌──────────────┐  │
│  │ Planner  │──▶│ Executor │──▶│Evaluator │──▶│  Synthesis   │  │
│  │          │    │          │   │          │    │+ Integrity   │  │
│  │ Goal →   │    │ Tool     │   │ Success? │    │  Check       │  │
│  │ Steps    │    │ Calling  │   │ Retry?   │    │              │  │
│  └──────────┘    └────┬─────┘   └──────────┘    └──────────────┘  │
│                       │                                           │
│          ┌────────────┼────────────────────────┐                  │
│          │   Scheduling Gate                   │                  │
│          │   Blocks create_event if no         │                  │
│          │   specific time in user message     │                  │
│          └────────────┬────────────────────────┘                  │
└───────────────────────┼───────────────────────────────────────────┘
                        │
           ┌────────────┼────────────────┐
           ▼            ▼                ▼
    ┌────────────┐ ┌──────────┐  ┌────────────┐
    │  Linkup    │ │  Local   │  │  Memory    │
    │  (web      │ │  Tools   │  │  Store/    │
    │  search)   │ │  Email   │  │  Recall    │
    │            │ │  Docs    │  │            │
    │  Only API  │ │  Calendar│  │  SQLite +  │
    │  call      │ │          │  │  FAISS     │
    └────────────┘ └──────────┘  └────────────┘
```

## Components

### Privacy Layer (`tools/privacy.py`)

The first thing that processes user input. Uses 4 detection patterns (case-insensitive):

| Pattern | Example | Result |
|---------|---------|--------|
| keyword + name | "email to karthik" | karthik → `<PERSON_1>` |
| name + role | "karthik my cfo" | karthik → `<PERSON_1>` |
| name + "who is" + role | "karthik who is my cfo" | karthik → `<PERSON_1>` |
| structured PII | "1234567890" | → `<PHONE_1>` |

What stays visible: company names, dates, locations, roles, topics.

Cumulative session entity map means `<PERSON_1>` from message 1 is still restorable in message 5's response.

### Planner (`agent/planner.py`)

Takes the (redacted) user input + context from long-term memory and asks the LLM to produce a JSON array of steps. Hard rules:
- No `web_research` unless user explicitly needs external info
- Scheduling without a time → plan must include "check calendar" + "ask user"
- Maximum 10 steps

### Executor (`agent/executor.py`)

For each step, sends the LLM the conversation + tool definitions. Key features:
- **Multi-round tool calling**: Up to 5 rounds per step
- **Scheduling Gate**: Code-level block on `create_event`/`create_reminder` unless `_has_specific_time()` detects a date/time in the user's message. This cannot be bypassed by LLM prompt manipulation.
- **PII Restore in write-tools**: When calling `draft_reply`, `create_event`, or `create_reminder`, all string arguments are passed through `restore()` so generated files contain real names, not placeholders.

### Evaluator (`agent/evaluator.py`)

Checks each step's result:
- Fast path: `[ERROR]` in output → failure → retry
- Short clean output → success
- Ambiguous → ask LLM for structured evaluation
- Max 2 retries per step

### Synthesis + Integrity Check (`agent/loop.py`)

After all steps complete:
1. LLM synthesizes step results into a final response
2. **Integrity check**: If response claims "meeting scheduled" but no `.ics` exists → strips the false claim, appends real free times from calendar
3. PII restored from cumulative session map
4. Generated files deduplicated by type (only 1 email, 1 calendar per run)

## Tool Registry

12 tools across 5 domains, registered at startup:

| Domain | Tools | File |
|--------|-------|------|
| Web Research | `web_research` | `tools/linkup_client.py` |
| Email | `list_emails`, `read_email`, `draft_reply` | `tools/email_adapter.py` |
| Documents | `read_document`, `list_documents`, `summarize_document` | `tools/document_adapter.py` |
| Calendar | `list_events`, `create_event`, `create_reminder` | `tools/calendar_adapter.py` |
| Memory | `memory_store`, `memory_recall` | `tools/memory_tools.py` |

Each tool implements `BaseTool` with `name`, `description`, `parameters` (JSON schema), and `run()`. The registry auto-generates Ollama tool definitions.

## Memory System

- **Short-term**: In-memory conversation buffer (last 20 messages)
- **Long-term (SQLite)**: Conversation history, task logs, user preferences, stored facts
- **Semantic (FAISS)**: Embedding-based similarity search using sentence-transformers (all-MiniLM-L6-v2, 384 dims)

## Generated Files

Tools that create files populate `ToolResult.generated_files`:
```python
generated_files=[{"type": "mailto", "path": "data/drafts/draft_xxx.eml", "label": "Subject", "to": "...", "subject": "...", "body": "..."}]
```

These bubble up through Executor → AgentLoop → Server → Frontend, where they render as download buttons. Email drafts open in the user's mail app via `mailto:` link.
