"""Privacy layer — smart context-aware PII redaction.

REDACTS (personal identifiers the AI doesn't need):
  - Person names  →  <PERSON_1>
  - Email addresses  →  <EMAIL_1>
  - Phone numbers  →  <PHONE_1>
  - SSNs  →  <SSN_1>
  - Credit card numbers  →  <CREDIT_CARD_1>
  - IP addresses  →  <IP_ADDRESS_1>

KEEPS (task-relevant context the AI needs to do its job):
  - Organization / company names  (needed for Linkup search, email context)
  - Locations  (needed for calendar events, meeting context)
  - Dates / times  (needed for scheduling)
  - Topics, subjects, roles  (needed for task understanding)

Example:
  Input:  "draft me an email to karthik my cfo about Acme Corp latest scandal"
  Output: "draft me an email to <PERSON_1> my cfo about Acme Corp latest scandal"

The entity_map stores {<PERSON_1>: "karthik"} so originals can be restored
in the final response the user sees.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Lazy-loaded Presidio engines
# --------------------------------------------------------------------------- #

_analyzer = None
_anonymizer = None
_nlp_active: bool | None = None  # None = not yet attempted


def _load_presidio():
    global _analyzer, _anonymizer, _nlp_active
    if _nlp_active is not None:
        return _analyzer, _anonymizer, _nlp_active
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine)
        _anonymizer = AnonymizerEngine()

        test = _analyzer.analyze(text="John Smith lives in New York", language="en")
        if not any(r.entity_type == "PERSON" for r in test):
            logger.warning("Presidio smoke test failed — falling back to regex.")
            _nlp_active = False
            return None, None, False

        logger.info("✅ Presidio NLP engine loaded successfully.")
        _nlp_active = True
        return _analyzer, _anonymizer, True

    except Exception as exc:
        logger.info("Presidio not available (%s) — using regex fallback.", exc)
        _nlp_active = False
        return None, None, False


# --------------------------------------------------------------------------- #
# What to redact vs keep
# --------------------------------------------------------------------------- #

_REDACT_ENTITY_TYPES = {
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "US_SSN", "CREDIT_CARD", "IP_ADDRESS",
    "EMAIL", "PHONE", "SSN",
}

_PRESIDIO_DETECT = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER",
    "US_SSN", "CREDIT_CARD", "IP_ADDRESS",
    "LOCATION", "DATE_TIME", "NRP",
]


def _presidio_redact(text: str) -> tuple[str, dict[str, str]]:
    analyzer, _, _ = _load_presidio()
    results = analyzer.analyze(text=text, language="en", entities=_PRESIDIO_DETECT)

    entity_map: dict[str, str] = {}
    counter: dict[str, int] = {}
    redacted = text

    for r in sorted(results, key=lambda x: x.start, reverse=True):
        if r.entity_type not in _REDACT_ENTITY_TYPES:
            continue
        original = text[r.start : r.end]
        if len(original.strip()) < 2:
            continue
        etype = r.entity_type
        counter[etype] = counter.get(etype, 0) + 1
        placeholder = f"<{etype}_{counter[etype]}>"
        entity_map[placeholder] = original
        redacted = redacted[: r.start] + placeholder + redacted[r.end :]

    return redacted, entity_map


# --------------------------------------------------------------------------- #
# Regex fallback — comprehensive name detection
# --------------------------------------------------------------------------- #

_REGEX_PATTERNS = {
    "EMAIL":       r"\b[\w.-]+@[\w.-]+\.\w+\b",
    "PHONE":       r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "SSN":         r"\b\d{3}-\d{2}-\d{4}\b",
    "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "IP_ADDRESS":  r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}\b",
}

# ---- Name detection patterns (case-insensitive) ----

# Role/title words that signal the preceding or following word is a person
_ROLE_WORDS = {
    "cfo", "ceo", "cto", "coo", "cpo", "cmo", "vp", "svp", "evp", "avp",
    "president", "director", "manager", "lead", "head", "chief",
    "boss", "supervisor", "colleague", "coworker", "assistant",
    "secretary", "analyst", "engineer", "developer", "designer",
    "accountant", "lawyer", "attorney", "doctor", "professor",
    "advisor", "consultant", "partner", "associate", "intern",
    "friend", "brother", "sister", "mom", "dad", "wife", "husband",
    "uncle", "aunt", "cousin", "neighbor", "roommate",
}

# Words that are NEVER person names
_STOP_WORDS = {
    # Days & months
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    # Common task words & action verbs
    "email", "message", "meeting", "report", "document", "file", "project",
    "team", "department", "company", "group", "schedule", "calendar",
    "draft", "reply", "send", "create", "list", "read", "summarize",
    "research", "search", "find", "check", "verify", "prepare",
    "reminder", "event", "task", "note", "memo", "letter", "invoice",
    "add", "remove", "delete", "update", "edit", "change", "move", "copy",
    "set", "put", "run", "open", "close", "start", "stop", "cancel",
    "save", "load", "show", "hide", "view", "print", "export", "import",
    "share", "forward", "attach", "upload", "download", "sync",
    "book", "reserve", "confirm", "accept", "decline", "approve", "reject",
    "assign", "complete", "finish", "submit", "review", "sign", "mark",
    "write", "compose", "type", "enter", "fill", "format", "clean",
    "sort", "filter", "merge", "split", "combine", "compare", "convert",
    "track", "monitor", "follow", "watch", "log", "record", "count",
    "help", "fix", "resolve", "handle", "process", "manage", "organize",
    "plan", "setup", "configure", "install", "test", "debug", "deploy",
    "look", "see", "try", "use", "take", "give", "tell", "say", "go",
    "needed", "wanted", "asked", "called", "named", "based", "related",
    "included", "attached", "mentioned", "discussed", "scheduled",
    "reach", "reached", "include", "included", "inform", "informed",
    # Common adjectives & modifiers
    "shared", "private", "public", "personal", "important", "urgent",
    "available", "free", "busy", "open", "closed", "pending", "done",
    "old", "good", "bad", "big", "small", "long", "short", "full", "empty",
    "first", "second", "third", "other", "same", "different", "main",
    "whole", "entire", "current", "previous", "original", "final",
    "quick", "fast", "slow", "early", "late", "ready", "sure", "right",
    # Org suffixes
    "corp", "corporation", "inc", "llc", "ltd", "company", "enterprises",
    "technologies", "tech", "labs", "studio", "studios", "solutions",
    "partners", "capital", "ventures", "foundation", "institute",
    "university", "bank", "global", "international",
    # Pronouns & common words
    "me", "my", "him", "her", "his", "them", "their", "the", "a", "an",
    "this", "that", "it", "about", "and", "for", "with", "from", "who",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "he", "she", "we", "they", "us", "our", "its", "you", "your",
    "i", "am", "had", "has", "having", "been",
    # Prepositions & conjunctions (critical: these appear between keywords and names)
    "to", "in", "on", "at", "by", "of", "up", "out", "off", "into",
    "over", "after", "before", "between", "through", "during", "until",
    "or", "but", "so", "yet", "nor", "if", "then", "also", "just",
    "not", "no", "all", "any", "some", "each", "every", "both",
    "please", "can", "could", "would", "should", "will", "shall",
    "do", "does", "did", "get", "got", "let", "make", "know", "need",
    "want", "like", "new", "latest", "recent", "last", "next", "upcoming",
    # Apps & services
    "whatsapp", "slack", "gmail", "outlook", "google", "microsoft",
    "zoom", "teams", "skype", "discord", "telegram",
    # Tools the agent knows
    "linkup", "acme", "inbox", "folder",
}

# Words that signal the NEXT word(s) is a person name
_PRE_NAME_KEYWORDS = [
    "to", "from", "with", "tell", "ask", "email", "message",
    "contact", "call", "notify", "invite", "cc", "bcc",
    "remind", "meet", "ping", "text", "reply to",
    "schedule with", "meeting with", "call with",
]

# Patterns:
# 1. "keyword NAME" — e.g. "email to karthik", "meeting with john smith"
# 2. "NAME my/the ROLE" — e.g. "karthik my cfo", "sarah the manager"
# 3. "NAME who is ROLE" — e.g. "karthik who is my cfo"
# 4. "NAME, my/our ROLE" — e.g. "karthik, my cfo"

# Pattern 1: keyword + name (case-insensitive, 1-3 word name)
_PATTERN_KEYWORD_NAME = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _PRE_NAME_KEYWORDS) + r")"
    r"\s+"
    r"([a-zA-Z][a-zA-Z'-]*(?:\s+[a-zA-Z][a-zA-Z'-]*){0,2})"
    r"(?:\s|$|[,.])",
    re.IGNORECASE,
)

# Pattern 2: name + possessive/article + role
_PATTERN_NAME_ROLE = re.compile(
    r"\b([a-zA-Z][a-zA-Z'-]*(?:\s+[a-zA-Z][a-zA-Z'-]*)?)"
    r"\s+(?:my|our|the|his|her|their|your)\s+"
    r"(" + "|".join(re.escape(r) for r in _ROLE_WORDS) + r")\b",
    re.IGNORECASE,
)

# Pattern 3: name + "who is" + optional "my/our/the" + role
_PATTERN_NAME_WHOIS = re.compile(
    r"\b([a-zA-Z][a-zA-Z'-]*(?:\s+[a-zA-Z][a-zA-Z'-]*)?)"
    r"\s+who\s+is\s+(?:my|our|the|his|her|their|your)?\s*"
    r"(" + "|".join(re.escape(r) for r in _ROLE_WORDS) + r")\b",
    re.IGNORECASE,
)

# Pattern 4: name + comma + possessive + role
_PATTERN_NAME_COMMA_ROLE = re.compile(
    r"\b([a-zA-Z][a-zA-Z'-]*(?:\s+[a-zA-Z][a-zA-Z'-]*)?)"
    r"\s*,\s*(?:my|our|the|his|her|their|your)\s+"
    r"(" + "|".join(re.escape(r) for r in _ROLE_WORDS) + r")\b",
    re.IGNORECASE,
)


def _is_org_name(name: str, text: str) -> bool:
    """Check if a candidate name is actually an organization."""
    name_lower = name.lower()
    words = name_lower.split()
    # If any word in the name is an org suffix → it's an org
    org_suffixes = {"corp", "corporation", "inc", "llc", "ltd", "company",
                    "enterprises", "technologies", "tech", "labs", "studios",
                    "solutions", "partners", "capital", "ventures", "group",
                    "foundation", "institute", "university", "bank"}
    for w in words:
        if w in org_suffixes:
            return True
    # Check if text around the name has org context
    idx = text.lower().find(name_lower)
    if idx >= 0:
        window = text[max(0, idx - 25) : idx + len(name) + 25].lower()
        if any(sig in window for sig in ["company", "firm", "startup", "corporation", "organization"]):
            return True
    return False


def _extract_name_candidates(text: str) -> list[tuple[str, int, int]]:
    """Find all person-name candidates in text. Returns [(name, start, end), ...]."""
    candidates: list[tuple[str, int, int]] = []
    seen_spans: set[tuple[int, int]] = set()

    all_patterns = [
        _PATTERN_NAME_ROLE,       # "karthik my cfo"
        _PATTERN_NAME_WHOIS,      # "karthik who is my cfo"
        _PATTERN_NAME_COMMA_ROLE, # "karthik, my cfo"
        _PATTERN_KEYWORD_NAME,    # "email to karthik"
    ]

    for pattern in all_patterns:
        for match in pattern.finditer(text):
            name = match.group(1).strip()
            # Clean trailing punctuation
            name = name.rstrip(".,;:!?")

            if not name or len(name) < 2:
                continue

            # Strip leading and trailing stop words from the candidate
            name_words = name.split()
            name_words_lower = [w.lower() for w in name_words]

            # Strip leading stop words
            while name_words_lower and name_words_lower[0] in _STOP_WORDS:
                name_words.pop(0)
                name_words_lower.pop(0)

            # Strip trailing stop words
            while name_words_lower and name_words_lower[-1] in _STOP_WORDS:
                name_words.pop()
                name_words_lower.pop()

            # Check remaining words — skip if any are stop words in the middle
            # or if nothing remains
            if not name_words:
                continue

            final_name = " ".join(name_words)

            if not final_name or len(final_name) < 3:
                continue

            # Skip ALL remaining stop words (even single-word names)
            if final_name.lower() in _STOP_WORDS:
                continue

            # Skip if it looks like an org
            if _is_org_name(final_name, text):
                continue

            # Find position in text using WORD BOUNDARIES
            # This prevents matching "he" inside "schedule" or "me" inside "name"
            boundary_pattern = re.compile(r"\b" + re.escape(final_name) + r"\b", re.IGNORECASE)
            match_in_text = boundary_pattern.search(text)
            if not match_in_text:
                continue
            start = match_in_text.start()
            end = match_in_text.end()
            span = (start, end)

            if span not in seen_spans:
                seen_spans.add(span)
                # Get the actual text from the original (preserve user's casing)
                actual_name = text[start:end]
                candidates.append((actual_name, start, end))

    return candidates


def _regex_redact(text: str) -> tuple[str, dict[str, str]]:
    """Regex-based PII redaction — structured patterns + contextual name detection."""
    entity_map: dict[str, str] = {}
    counter: dict[str, int] = {}
    redacted = text

    # 1. Redact structured PII (emails, phones, SSN, credit cards, IPs)
    for label, pattern in _REGEX_PATTERNS.items():
        for match in re.finditer(pattern, redacted):
            original = match.group()
            if original in entity_map.values():
                continue
            counter[label] = counter.get(label, 0) + 1
            placeholder = f"<{label}_{counter[label]}>"
            entity_map[placeholder] = original
            redacted = redacted.replace(original, placeholder, 1)

    # 2. Detect and redact person names
    candidates = _extract_name_candidates(redacted)

    # Sort by position (reverse) so replacements don't shift indices
    candidates.sort(key=lambda c: c[1], reverse=True)

    for name, start, end in candidates:
        # Verify the name still exists at this position (not already redacted)
        current = redacted[start:end]
        if current.lower() != name.lower():
            continue
        # Extra safety: verify word boundaries in the current redacted text
        if start > 0 and redacted[start-1].isalpha():
            continue
        if end < len(redacted) and redacted[end].isalpha():
            continue

        counter["PERSON"] = counter.get("PERSON", 0) + 1
        placeholder = f"<PERSON_{counter['PERSON']}>"
        entity_map[placeholder] = name
        redacted = redacted[:start] + placeholder + redacted[end:]

    return redacted, entity_map


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

@dataclass
class PrivacyResult:
    redacted_text: str
    entity_map: dict[str, str] = field(default_factory=dict)
    engine: str = "none"


def redact(text: str, enabled: bool = True) -> PrivacyResult:
    """
    Redact personal identifiers from text while keeping task-relevant context.

    Redacts: person names, emails, phones, SSNs, credit cards, IPs
    Keeps: company names, locations, dates, roles, topics
    """
    if not enabled or not text.strip():
        return PrivacyResult(redacted_text=text, engine="none")

    # Try Presidio first
    _, _, nlp_ok = _load_presidio()
    if nlp_ok:
        redacted, emap = _presidio_redact(text)
        # Also run regex name patterns on the Presidio output
        # to catch names Presidio missed (e.g. lowercase names)
        extra_redacted, extra_emap = _regex_name_pass(redacted)
        if extra_emap:
            emap.update(extra_emap)
            redacted = extra_redacted
        if emap:
            logger.info("Privacy (presidio+regex): %s", {v: k for k, v in emap.items()})
        return PrivacyResult(redacted_text=redacted, entity_map=emap, engine="presidio")

    # Regex fallback
    redacted, emap = _regex_redact(text)
    if emap:
        logger.info("Privacy (regex): %s", {v: k for k, v in emap.items()})
    return PrivacyResult(redacted_text=redacted, entity_map=emap, engine="regex")


def _regex_name_pass(text: str) -> tuple[str, dict[str, str]]:
    """Run only the name-detection patterns (not structured PII) on already-processed text."""
    entity_map: dict[str, str] = {}
    counter: dict[str, int] = {}
    redacted = text

    # Count existing PERSON placeholders so we don't collide
    existing = len(re.findall(r"<PERSON_\d+>", text))
    counter["PERSON"] = existing

    candidates = _extract_name_candidates(redacted)
    candidates.sort(key=lambda c: c[1], reverse=True)

    for name, start, end in candidates:
        current = redacted[start:end]
        if current.lower() != name.lower():
            continue
        if "<" in name:
            continue
        # Word boundary check
        if start > 0 and redacted[start-1].isalpha():
            continue
        if end < len(redacted) and redacted[end].isalpha():
            continue
        counter["PERSON"] = counter.get("PERSON", 0) + 1
        placeholder = f"<PERSON_{counter['PERSON']}>"
        entity_map[placeholder] = name
        redacted = redacted[:start] + placeholder + redacted[end:]

    return redacted, entity_map


def restore(text: str, entity_map: dict[str, str]) -> str:
    """Replace placeholders back with original values in the agent's response."""
    for placeholder, original in entity_map.items():
        text = text.replace(placeholder, original)
    return text
