"""Email tools — read, list, and draft email replies.

MVP uses IMAP (configurable) or falls back to a local mailbox directory for demo/testing.
"""

from __future__ import annotations

import email
import email.policy
import email.utils
import email.mime.text
import email.mime.multipart
import imaplib
import json
import logging
import os
import re
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from tools import BaseTool, ToolResult

logger = logging.getLogger(__name__)

# =========================================================================== #
#  Local demo mailbox (flat directory of .eml files)
# =========================================================================== #

_DEMO_MAILBOX = Path("data/emails")


def _ensure_demo_mailbox():
    _DEMO_MAILBOX.mkdir(parents=True, exist_ok=True)
    sample = _DEMO_MAILBOX / "sample_investor.eml"
    if not sample.exists():
        sample.write_text(
            "From: investor@acmecorp.com\n"
            "To: user@example.com\n"
            "Subject: Partnership Opportunity with Acme Corp\n"
            "Date: Mon, 10 Feb 2026 09:00:00 +0000\n"
            "\n"
            "Hi,\n\n"
            "I'm reaching out from Acme Corp regarding a potential partnership.\n"
            "We recently closed our Series B and are looking to collaborate with\n"
            "innovative teams in your space.\n\n"
            "Could we schedule a call this week?\n\n"
            "Best,\n"
            "Jane Doe\nVP Partnerships, Acme Corp\n"
        )


# =========================================================================== #
#  list_emails
# =========================================================================== #

class ListEmailsTool(BaseTool):
    def __init__(self, cfg: dict):
        self._cfg = cfg

    @property
    def name(self) -> str:
        return "list_emails"

    @property
    def description(self) -> str:
        return "List recent emails in the inbox. Returns subject, sender, date for each."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max emails to return (default 10)."},
            },
            "required": [],
        }

    def run(self, **kwargs) -> ToolResult:
        limit = kwargs.get("limit", 10)
        try:
            # If IMAP is configured, use it; otherwise fall back to local .eml files
            if self._cfg.get("imap_host"):
                return self._list_imap(limit)
            return self._list_local(limit)
        except Exception as exc:
            logger.error("list_emails failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

    def _list_local(self, limit: int) -> ToolResult:
        _ensure_demo_mailbox()
        emails = []
        for p in sorted(_DEMO_MAILBOX.glob("*.eml"))[:limit]:
            msg = email.message_from_string(p.read_text(), policy=email.policy.default)
            emails.append({
                "id": p.stem,
                "from": msg["From"],
                "subject": msg["Subject"],
                "date": msg["Date"],
            })
        return ToolResult(success=True, data=json.dumps(emails, indent=2))

    def _list_imap(self, limit: int) -> ToolResult:
        conn = imaplib.IMAP4_SSL(self._cfg["imap_host"], int(self._cfg.get("imap_port", 993)))
        conn.login(self._cfg["imap_user"], self._cfg.get("password", os.environ.get("AGENT_EMAIL_PASSWORD", "")))
        conn.select("INBOX")
        _, data = conn.search(None, "ALL")
        ids = data[0].split()[-limit:]
        emails = []
        for mid in ids:
            _, msg_data = conn.fetch(mid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1], policy=email.policy.default)
            emails.append({
                "id": mid.decode(),
                "from": msg["From"],
                "subject": msg["Subject"],
                "date": msg["Date"],
            })
        conn.logout()
        return ToolResult(success=True, data=json.dumps(emails, indent=2))


# =========================================================================== #
#  read_email
# =========================================================================== #

class ReadEmailTool(BaseTool):
    def __init__(self, cfg: dict):
        self._cfg = cfg

    @property
    def name(self) -> str:
        return "read_email"

    @property
    def description(self) -> str:
        return "Read the full contents of an email by its ID."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "ID of the email to read."},
            },
            "required": ["email_id"],
        }

    def run(self, **kwargs) -> ToolResult:
        eid = kwargs.get("email_id", "")
        try:
            if self._cfg.get("imap_host"):
                return self._read_imap(eid)
            return self._read_local(eid)
        except Exception as exc:
            logger.error("read_email failed: %s", exc)
            return ToolResult(success=False, error=str(exc))

    def _read_local(self, eid: str) -> ToolResult:
        _ensure_demo_mailbox()
        path = _DEMO_MAILBOX / f"{eid}.eml"
        if not path.exists():
            return ToolResult(success=False, error=f"Email '{eid}' not found.")
        msg = email.message_from_string(path.read_text(), policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain",))
        return ToolResult(success=True, data=json.dumps({
            "from": msg["From"],
            "to": msg["To"],
            "subject": msg["Subject"],
            "date": msg["Date"],
            "body": body.get_content() if body else "",
        }, indent=2))

    def _read_imap(self, eid: str) -> ToolResult:
        conn = imaplib.IMAP4_SSL(self._cfg["imap_host"], int(self._cfg.get("imap_port", 993)))
        conn.login(self._cfg["imap_user"], self._cfg.get("password", os.environ.get("AGENT_EMAIL_PASSWORD", "")))
        conn.select("INBOX")
        _, msg_data = conn.fetch(eid.encode(), "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1], policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain",))
        conn.logout()
        return ToolResult(success=True, data=json.dumps({
            "from": msg["From"],
            "to": msg["To"],
            "subject": msg["Subject"],
            "date": msg["Date"],
            "body": body.get_content() if body else "",
        }, indent=2))


# =========================================================================== #
#  Text → HTML converter for email body
# =========================================================================== #

def _text_to_html(text: str) -> str:
    """Convert plain text email body to well-formatted HTML.

    Handles:
    - Paragraphs (double newlines → <p> blocks)
    - Bullet lists (* or - prefixed lines → <ul><li>)
    - Numbered lists (1. 2. 3. → <ol><li>)
    - Single line breaks within paragraphs → <br>
    - Proper escaping of special HTML characters
    """
    import html as html_mod

    lines = text.split("\n")
    html_parts: list[str] = []
    in_ul = False
    in_ol = False
    paragraph: list[str] = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            html_parts.append("<p>" + "<br>\n".join(paragraph) + "</p>")
            paragraph = []

    def close_lists():
        nonlocal in_ul, in_ol
        if in_ul:
            html_parts.append("</ul>")
            in_ul = False
        if in_ol:
            html_parts.append("</ol>")
            in_ol = False

    for line in lines:
        stripped = line.strip()

        # Empty line → end of paragraph
        if not stripped:
            flush_paragraph()
            close_lists()
            continue

        # Bullet list: * item or - item
        bullet_match = re.match(r"^[\*\-\u2022]\s+(.+)$", stripped)
        if bullet_match:
            flush_paragraph()
            if in_ol:
                html_parts.append("</ol>")
                in_ol = False
            if not in_ul:
                html_parts.append("<ul>")
                in_ul = True
            html_parts.append(f"  <li>{html_mod.escape(bullet_match.group(1))}</li>")
            continue

        # Numbered list: 1. item, 2. item
        num_match = re.match(r"^\d+[\.\)]\s+(.+)$", stripped)
        if num_match:
            flush_paragraph()
            if in_ul:
                html_parts.append("</ul>")
                in_ul = False
            if not in_ol:
                html_parts.append("<ol>")
                in_ol = True
            html_parts.append(f"  <li>{html_mod.escape(num_match.group(1))}</li>")
            continue

        # Regular text line
        close_lists()
        paragraph.append(html_mod.escape(stripped))

    flush_paragraph()
    close_lists()

    body_html = "\n".join(html_parts)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: Calibri, Arial, sans-serif; font-size: 14px; color: #1a1a1a; line-height: 1.6; max-width: 680px;">
{body_html}
</body>
</html>"""


def _format_email_body(body: str) -> str:
    """Ensure proper paragraph spacing in email body.

    - Blank line after greeting (Dear X,)
    - Blank line before sign-off (Best regards, etc.)
    - Blank line between paragraphs
    - Preserve bullet lists
    """
    lines = body.split("\n")
    formatted: list[str] = []

    greeting_patterns = re.compile(r"^(dear|hi|hello|hey|good morning|good afternoon)\b", re.IGNORECASE)
    signoff_patterns = re.compile(r"^(best|regards|sincerely|thanks|thank you|cheers|warm regards|kind regards|yours)", re.IGNORECASE)

    for i, line in enumerate(lines):
        stripped = line.strip()
        formatted.append(line)

        # Add blank line after greeting
        if greeting_patterns.match(stripped) and stripped.endswith(","):
            if i + 1 < len(lines) and lines[i + 1].strip():
                formatted.append("")

        # Add blank line before sign-off
        if signoff_patterns.match(stripped):
            if formatted and len(formatted) >= 2 and formatted[-2].strip():
                formatted.insert(-1, "")

    # Collapse 3+ blank lines to 2
    result = "\n".join(formatted)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# =========================================================================== #
#  draft_reply
# =========================================================================== #

class DraftReplyTool(BaseTool):
    @property
    def name(self) -> str:
        return "draft_reply"

    @property
    def description(self) -> str:
        return (
            "Save a draft email to the local drafts folder and return the content. "
            "CRITICAL: Write the COMPLETE, FINAL email body in the 'body' parameter. "
            "This is the ONLY version of the email — whatever you put here is exactly "
            "what gets saved as the .eml file and shown to the user. "
            "Include proper greeting, all details, bullet points if needed, and sign-off. "
            "Do NOT write a short summary — write the full professional email. "
            "Do NOT include 'Subject:' or email headers in the body."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient name or email address."},
                "subject": {"type": "string", "description": "Email subject line (DO NOT repeat this in the body)."},
                "body": {
                    "type": "string",
                    "description": (
                        "The COMPLETE email body — this is saved as-is to the .eml file. "
                        "Write a full, professional, well-structured email. "
                        "Include greeting, all relevant details, and sign-off. "
                        "Use \\n for line breaks. Use * for bullet points. "
                        "Do NOT include Subject line or headers. No HTML tags."
                    ),
                },
            },
            "required": ["to", "subject", "body"],
        }

    def run(self, **kwargs) -> ToolResult:
        drafts = Path("data/drafts")
        drafts.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = drafts / f"draft_{ts}.eml"

        to_addr = kwargs.get("to", "")
        subject = kwargs.get("subject", "")
        body = kwargs.get("body", "")

        # --- Fix unicode escapes the LLM sometimes produces ---
        for esc, char in [("\\u2019", "\u2019"), ("\\u2018", "\u2018"),
                          ("\\u201c", "\u201c"), ("\\u201d", "\u201d"),
                          ("\\u2014", "\u2014"), ("\\u2013", "\u2013")]:
            body = body.replace(esc, char)
            subject = subject.replace(esc, char)
        body = body.replace("\\n", "\n")
        subject = subject.replace("\\n", " ")

        # Strip HTML tags from LLM output
        body = re.sub(r"<br\s*/?>", "\n", body)
        body = re.sub(r"<[^>]+>", "", body)

        # Strip markdown bold but keep the text
        body = re.sub(r"\*\*([^*]+)\*\*", r"\1", body)
        body = re.sub(r"(?<=\s)\*([^*\n]+)\*(?=[\s\.,;:!?]|$)", r"\1", body)

        # Remove subject line if LLM put it in the body
        subject_clean = subject.strip()
        if subject_clean:
            body = re.sub(
                r"^Subject\s*:\s*" + re.escape(subject_clean) + r"\s*\n*",
                "", body, flags=re.IGNORECASE | re.MULTILINE
            )
            if body.strip().startswith(subject_clean):
                body = body.strip()[len(subject_clean):].lstrip(" ,.\n")

        body = body.strip()

        # --- Ensure proper paragraph spacing for email readability ---
        body = _format_email_body(body)

        # --- Build .eml using Python's email library (handles MIME correctly) ---
        html_body = _text_to_html(body)

        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["From"] = "user@halodesk.local"
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg["Date"] = email.utils.formatdate(localtime=True)

        # Plain text part (fallback)
        msg.attach(email.mime.text.MIMEText(body, "plain", "utf-8"))
        # HTML part (preferred by Outlook)
        msg.attach(email.mime.text.MIMEText(html_body, "html", "utf-8"))

        # Write with CRLF line endings (required by Outlook)
        eml_bytes = msg.as_bytes()
        # Ensure CRLF line endings throughout
        eml_bytes = eml_bytes.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        path.write_bytes(eml_bytes)
        logger.info("Draft saved: %s", path)
        return ToolResult(success=True, data=json.dumps({
            "message": "Draft email saved successfully.",
            "eml_file": str(path),
            "to": to_addr,
            "subject": subject,
            "body": body,
        }, ensure_ascii=False), generated_files=[{
            "type": "mailto",
            "path": str(path),
            "label": subject or "Email Draft",
            "to": to_addr,
            "subject": subject,
            "body": body,
        }])
