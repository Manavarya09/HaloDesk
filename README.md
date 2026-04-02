# HaloDesk

HaloDesk is a local-first desktop assistant for research, email, documents, scheduling, and memory. It combines a browser UI, a Python backend, a local Ollama model, tool orchestration, privacy redaction, and persistent memory in one workspace.

It is built around a planner-executor-evaluator loop:

1. Redact sensitive user input when privacy mode is enabled.
2. Break the request into actionable steps.
3. Call the right tools for email, files, memory, calendar, or web research.
4. Evaluate the outcome and retry when needed.

## Features

- Local LLM execution through Ollama
- Web research through Linkup when fresh information is needed
- Email listing, reading, and draft generation
- Document listing, reading, and summarization
- Calendar lookup plus `.ics` event and reminder creation
- Persistent memory with SQLite and FAISS
- File attachments in the web UI
- AI View panel to inspect the redacted model input
- Optional Presidio-based privacy layer with regex fallback

## Tech Stack

- Python backend with Flask
- Ollama for local model serving
- Linkup for web research
- Sentence Transformers for embeddings
- FAISS for semantic retrieval
- SQLite for session and task history
- Plain HTML, CSS, and JavaScript frontend

## Repository Layout

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
└── server.py     # Flask API server
```

## Requirements

Minimum:

- Python 3.10 or newer
- `pip`
- Ollama installed locally
- Internet access for Linkup requests
- A Linkup API key

Recommended:

- 8 GB+ RAM for `llama3.1:8b`
- A virtual environment

## Full Installation Guide

### 1. Clone the repository

```bash
git clone https://github.com/Manavarya09/HaloDesk.git
cd HaloDesk
```

### 2. Create and activate a virtual environment

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Windows Command Prompt:

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Install Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Main packages installed from `requirements.txt` include:

- `ollama`
- `linkup-sdk`
- `flask`
- `flask-cors`
- `sentence-transformers`
- `faiss-cpu`
- `PyMuPDF`
- `python-docx`

### 4. Install and start Ollama

Install Ollama from `https://ollama.com`.

After installation, start the Ollama service if it is not already running:

```bash
ollama serve
```

In a second terminal, pull the default model used by this project:

```bash
ollama pull llama3.1:8b
```

The default model is configured in [config/defaults.yaml](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/config/defaults.yaml).

### 5. Set your Linkup API key

HaloDesk uses Linkup for web research. Set `LINKUP_API_KEY` before starting the server.

macOS or Linux:

```bash
export LINKUP_API_KEY="your-key-here"
```

Windows PowerShell:

```powershell
$env:LINKUP_API_KEY="your-key-here"
```

Windows Command Prompt:

```cmd
set LINKUP_API_KEY=your-key-here
```

Optional email password, if you later configure IMAP:

macOS or Linux:

```bash
export AGENT_EMAIL_PASSWORD="your-email-password"
```

Windows PowerShell:

```powershell
$env:AGENT_EMAIL_PASSWORD="your-email-password"
```

### 6. Optional: enable stronger privacy detection

HaloDesk works without these packages, but if you want NLP-based PII redaction instead of regex-only fallback, install:

```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_sm
```

### 7. Start the web server

```bash
python server.py
```

You should then be able to open:

```text
http://localhost:5000
```

### 8. Verify the installation

Open the built-in health check:

```text
http://localhost:5000/api/health
```

The app checks:

- Python availability
- Ollama connectivity
- Whether the configured Ollama model exists
- Linkup API key presence
- Installed Python packages
- Privacy engine availability
- Demo data presence

## Running the CLI

You can also use the assistant from the terminal:

```bash
python main.py
```

Single prompt mode:

```bash
python main.py --once "List my upcoming calendar events"
```

Useful CLI commands:

- `/tools`
- `/memory`
- `/tasks`
- `/quit`

## Default Configuration

The main defaults live in [config/defaults.yaml](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/config/defaults.yaml).

Current defaults:

- Model: `llama3.1:8b`
- Max retries: `2`
- Max plan steps: `10`
- Conversation buffer size: `20`
- SQLite path: `data/agent.db`
- FAISS path: `data/faiss.index`
- Embedding model: `all-MiniLM-L6-v2`
- Calendar directory: `data/calendars`

## How the App Works

### Privacy Layer

Input is optionally redacted before the model sees it. Person names and structured PII can be replaced with placeholders like `<PERSON_1>` while keeping task-relevant details such as dates, locations, and companies when possible.

### Planning

The planner breaks a request into steps instead of trying to solve everything in one pass.

### Execution

The executor calls tools for:

- Web research
- Email
- Documents
- Calendar
- Memory

### Evaluation

Each step is checked before the final response is returned.

## Local API Endpoints

- `GET /api/health` checks runtime readiness
- `GET /api/session` returns current session metadata
- `POST /api/chat` sends a message with optional file attachments
- `POST /api/upload` uploads files
- `GET /api/tasks` returns recent task history
- `GET /api/memory` returns semantic memory matches
- `GET /api/privacy` reports the active redaction engine
- `POST /api/privacy` toggles privacy mode

## Generated Files

HaloDesk can create:

- `.eml` email drafts
- `.ics` calendar events
- `.ics` reminders

These files are downloadable from the chat UI.

## Demo Data

The repository includes starter data so the app is usable immediately:

- Sample email content in `data/emails/`
- Demo calendar events in `data/calendars/`

On first run, additional local runtime files may be created in `data/`.

## Troubleshooting

### `Ollama` is not reachable

Make sure Ollama is installed and running:

```bash
ollama serve
```

Then confirm the model exists:

```bash
ollama list
```

### The model is missing

Pull the configured model:

```bash
ollama pull llama3.1:8b
```

### `LINKUP_API_KEY` is missing

Set the environment variable in the same shell session where you start `server.py`.

### Privacy engine shows regex instead of NLP

Install:

```bash
pip install presidio-analyzer presidio-anonymizer spacy
python -m spacy download en_core_web_sm
```

### Port 5000 is already in use

Stop the process using port `5000`, or modify the port in [server.py](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/server.py).

### FAISS or transformer downloads are slow on first run

That is expected. The embedding model may need to download the first time semantic memory is used.

## Notes and Constraints

- Calendar creation is intentionally blocked unless the request includes a specific date and time.
- Generated files restore real names before output.
- Privacy mode can be toggled from the UI.
- If Presidio is unavailable, the app falls back to regex-based redaction.

## Development Notes

If you modify the frontend, the main UI lives in [frontend/index.html](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/frontend/index.html).

If you modify backend orchestration, start with:

- [agent/loop.py](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/agent/loop.py)
- [agent/planner.py](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/agent/planner.py)
- [agent/executor.py](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/agent/executor.py)
- [agent/evaluator.py](/Users/manavaryasingh/Downloads/HackwithDC-Team-6-main/agent/evaluator.py)
