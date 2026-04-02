# Demo Scenarios

Four demo workflows that showcase the agent's key capabilities. Each demonstrates multiple evaluation criteria working together.

---

## Demo 1: Research + Draft Email (Linkup + Email + Privacy)

**What it shows**: Web research via Linkup, email drafting, privacy redaction, generated file download.

**Prompt**:
```
Research Microsoft's latest earnings and draft an email to karthik my analyst about the key takeaways
```

**Expected flow**:
1. Privacy redacts "karthik" → `<PERSON_1>` (visible in AI View tab)
2. Planner creates steps: research via Linkup → draft email
3. Linkup searches "Microsoft latest earnings Q2 2026"
4. LLM drafts a professional email with real data from Linkup
5. `draft_reply` tool saves .eml with real name "karthik" restored
6. Response shows the email in chat + "Open in Mail App" button
7. Clicking the button opens Outlook/Gmail with To, Subject, Body pre-filled

**Criteria demonstrated**: Linkup integration, privacy, multi-step autonomy, usability.

---

## Demo 2: Document Upload + Summarize + Email (Attachments + Documents + Email)

**What it shows**: File attachment handling, document parsing, summarization, email drafting.

**Prompt** (with a PDF/DOCX attached via drag-and-drop):
```
Summarize this document and draft an email that I can send to my manager
```

**Expected flow**:
1. PDF/DOCX is parsed locally (never sent externally)
2. Privacy redacts "manager" references if needed
3. LLM summarizes the document content
4. Drafts a professional email with the summary
5. Both summary and email shown in chat
6. "Open in Mail App" + ".eml" download buttons appear

**Criteria demonstrated**: Multi-domain (documents + email), generality, local-first processing.

---

## Demo 3: Email + Schedule Meeting (Email + Calendar + Scheduling Gate)

**What it shows**: Multi-step workflow, scheduling intelligence, the scheduling gate, calendar integration.

**Prompt**:
```
Draft me an email to karthik my analyst about Microsoft's latest earnings and schedule a meeting with him and add it to my calendar. Also include my phone number: 1234567890
```

**Expected flow**:
1. Privacy: "karthik" → `<PERSON_1>`, "1234567890" → `<PHONE_1>` (visible in AI View)
2. Email is drafted with Linkup research data
3. **Scheduling Gate activates** — no specific time in the message
4. Agent checks calendar, identifies free times
5. Agent asks: "When works for you? These times are free: [list]"
6. No .ics file generated yet — waiting for confirmation

**Follow-up prompt**:
```
Let's schedule a meeting on 11th Feb at 10:00
```

**Expected flow**:
1. Time detected → scheduling gate opens
2. `create_event` runs → .ics file created
3. "Meeting with karthik (.ics)" download button appears
4. Event confirmed with date, time, title

**Criteria demonstrated**: Autonomous planning, scheduling intelligence, context continuity, privacy, calendar management.

---

## Demo 4: Privacy Showcase (AI View Side-by-Side)

**What it shows**: The privacy system in action — what the user types vs. what the AI sees.

**Prompt**:
```
Send an email to priya at priya.sharma@company.com about the Acme Corp partnership. Also CC raj at raj@company.com. My phone is 555-123-4567.
```

**Expected flow** (check AI View tab):

| What you typed | What AI received |
|---|---|
| priya | `<PERSON_1>` |
| priya.sharma@company.com | `<EMAIL_1>` |
| raj | `<PERSON_2>` |
| raj@company.com | `<EMAIL_2>` |
| 555-123-4567 | `<PHONE_1>` |
| Acme Corp | Acme Corp ✅ (kept) |
| partnership | partnership ✅ (kept) |

**Then toggle Privacy OFF** and send the same prompt — AI View shows the full text unredacted.

**Criteria demonstrated**: Privacy-first design, PII detection, context-aware redaction.

---

## Quick Test Prompts

For rapid evaluation, these single-line prompts each test a specific capability:

| # | Prompt | Tests |
|---|--------|-------|
| 1 | `List my recent emails` | Email tools, no unnecessary Linkup |
| 2 | `Research the latest AI funding news` | Linkup search |
| 3 | `Create a meeting for tomorrow at 3pm called Project Sync` | Calendar with time → direct creation |
| 4 | `Schedule a meeting with raj` | Calendar without time → should ask |
| 5 | `Remember that our Q1 deadline is March 31st` | Memory store |
| 6 | `What do you remember?` | Memory recall |
| 7 | `Hello` | Conversational → no tools |
| 8 | Attach a PDF + `Summarize this` | File upload + document parsing |

---

## What to Point Out to Evaluators

1. **AI View tab** — Shows exactly what the LLM received after privacy redaction
2. **Generated Files section** — Download buttons that actually work (mailto opens mail app)
3. **Scheduling Gate** — The agent physically cannot create events without a confirmed time
4. **Integrity Check** — If the LLM lies about scheduling, the system catches and corrects it
5. **Local-first** — Ollama runs locally, FAISS and SQLite are local files, Linkup is the only API call
6. **Interactive Architecture Diagram** — Open `docs/architecture_diagram.html`
