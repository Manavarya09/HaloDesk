# Linkup Integration — Main Track

## Overview

Linkup is the agent's **only required external API**, providing real-time web knowledge through agentic search. It enables the agent to go beyond the local LLM's training data cutoff by researching entities, fact-checking claims, and gathering current information.

The integration is designed around two principles:
1. **Privacy**: Only sanitized, non-PII queries are ever sent. No email content, document text, or personal data leaves the machine.
2. **Intelligence**: The agent decides when to search — not on every prompt, only when external knowledge is genuinely needed.

## API Details

| Parameter | Value |
|-----------|-------|
| Endpoint | `POST https://api.linkup.so/v1/search` |
| Auth | `Authorization: Bearer <LINKUP_API_KEY>` |
| Key params | `q` (query), `depth` (standard/deep), `outputType` (searchResults/sourcedAnswer) |

## When the Agent Calls Linkup

The decision is made at multiple levels:

### 1. Prompt-Level Rules (System Prompt)

```
✅ USE web_research for:
  - User says "research", "look up", "search", "fact-check", "verify"
  - Current/recent information needed (news, earnings, events)
  - Unfamiliar company/product requiring background
  - Meeting prep with external parties

❌ DO NOT use for:
  - Email management (use email tools)
  - Document reading (use document tools)
  - Calendar management (use calendar tools)
  - Memory recall (use memory tools)
  - General conversation
```

### 2. Plan-Level Rules (Planner)

The planner is instructed to not include `web_research` steps unless the user explicitly needs external information. Local tasks use only local tools.

### 3. Result: Focused, Minimal API Usage

```
"List my emails"                    → NO Linkup call (local only)
"Research Acme Corp latest news"    → Linkup call
"Draft email to karthik"            → NO Linkup call
"Verify stats in this report"       → Linkup call
"Schedule a meeting"                → NO Linkup call
```

## Query Formulation

Following Linkup's prompting best practices:

| Principle | Bad Query | Good Query |
|-----------|-----------|------------|
| Be specific | "tell me about Acme" | "Acme Corp Series B funding 2025" |
| One intent per query | "Acme pricing, hiring, roadmap" | Split into 3 calls |
| Include context | "Microsoft news" | "Microsoft Q2 2026 earnings results" |
| No PII | "karthik's company funding" | "Acme Corp recent funding" |

For complex research, the agent chains 2-3 focused calls:
1. Company overview → 2. Recent news → 3. Key people

## Result Synthesis

Linkup results are formatted as text blocks injected into the LLM context:

```
[1] Acme Corp Closes $50M Series B
    Acme Corp announced today a $50M Series B led by...
    https://example.com/article

[2] Acme Corp - Company Profile
    Founded in 2020, Acme Corp specializes in...
    https://crunchbase.com/acme
```

The LLM uses these grounded sources to draft informed responses, fact-check claims, or provide research summaries — without hallucinating.

## Privacy Safeguards

| Layer | Protection |
|-------|-----------|
| Privacy module | PII redacted before LLM sees input — names become `<PERSON_1>` |
| System prompt | Explicitly prohibits PII in web search queries |
| Tool description | States "NEVER include personal/sensitive data in the query" |
| Query content | Only task-derived entities: company names, topics, public information |

**What is sent to Linkup**: `"Acme Corp company overview recent funding"`
**What is NEVER sent**: Full email bodies, document content, personal names, phone numbers

## Configuration

```yaml
# config/defaults.yaml
linkup:
  base_url: "https://api.linkup.so/v1/search"
  default_depth: "deep"
  default_output_type: "searchResults"
  rate_limit_per_second: 10
```

```bash
export LINKUP_API_KEY="your-key-here"
```

## Implementation

Single module: `tools/linkup_client.py`

- `LinkupSearchTool` extends `BaseTool`
- Rate limiting: token-bucket at 10 req/s
- Default: `depth=deep` for thorough research, `standard` for quick lookups
- `outputType=searchResults` for LLM grounding, `sourcedAnswer` for concise cited answers
- Error handling: HTTP errors, timeouts, rate limits — all reported gracefully

## Example Use Cases

### 1. Informed Email Reply
```
User: "Draft a reply to the investor inquiry from Acme Corp"
Agent: Research Acme Corp → Read email → Draft reply with research context
Linkup query: "Acme Corp company overview recent funding key personnel"
```

### 2. Fact-Checking
```
User: "Verify the statistics in this market report"
Agent: Read document → Identify claims → Fact-check via Linkup
Linkup query: "global AI market size 2025 authoritative sources"
```

### 3. Meeting Prep
```
User: "Prepare me for tomorrow's meeting with XYZ team"
Agent: Check calendar → Research attendees → Gather company news
Linkup queries: "XYZ company recent news" → "XYZ leadership team"
```
