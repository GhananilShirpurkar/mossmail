"""Conservative MIME preparation. Original bytes always remain available to the caller."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.message import Message as EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser

from .models import Message as DomainMessage


class VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.hidden += 1
        if tag in {"p", "div", "br", "li", "blockquote"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {"p", "div", "li"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


@dataclass(frozen=True)
class PreparedText:
    original: bytes
    full_text: str
    latest_text: str
    uncertain: bool
    notes: tuple[str, ...]


def latest_reply(text: str) -> tuple[str, bool]:
    lines = text.strip().splitlines()
    kept = []
    uncertain = False
    for index, line in enumerate(lines):
        marker = re.match(
            r"^\s*(On .{1,250}wrote:|[- ]*(Original Message|Forwarded message)[- :]*|"
            r"Begin forwarded message:)",
            line,
            flags=re.I,
        )
        if marker:
            # Bottom-posted replies cannot be safely separated: preserve and flag.
            tail = lines[index + 1 :]
            if any(s.strip() and not s.lstrip().startswith(">") for s in tail):
                uncertain = True
            latest = "\n".join(kept).strip()
            return (latest if latest else text.strip()), (uncertain or not latest)
        if line.lstrip().startswith(">"):
            uncertain = True  # Inline/bottom replies may depend on quoted context.
            continue
        kept.append(line)
    latest = "\n".join(kept).strip()
    return latest or text.strip(), uncertain or not latest


def prepare_message(raw: bytes) -> PreparedText:
    notes: list[str] = []
    if len(raw) > 2_000_000:
        return PreparedText(raw, "", "", True, ("Message exceeds safe parsing size.",))
    try:
        root = BytesParser(policy=policy.default).parsebytes(raw)

        def extract(part: EmailMessage, depth: int = 0) -> str:
            if depth > 30:
                notes.append("MIME nesting limit reached.")
                return ""
            if part.defects:
                notes.append("Malformed MIME structure.")
            if part.get_content_disposition() == "attachment" or part.get_filename():
                notes.append("Attachment omitted; manual review may be needed.")
                return ""
            if part.get_content_type() == "message/rfc822":
                notes.append("Attached message omitted to preserve the current sender's reply.")
                return ""
            if part.is_multipart():
                children = part.get_payload()
                if part.get_content_subtype() == "alternative":
                    ordered = sorted(children, key=lambda p: p.get_content_type() != "text/plain")
                    for child in ordered:
                        result = extract(child, depth + 1)
                        if result.strip():
                            return result
                    return ""
                return "\n".join(filter(None, (extract(p, depth + 1) for p in children)))
            if part.get_content_type() not in {"text/plain", "text/html"}:
                notes.append("Non-text content omitted.")
                return ""
            payload = part.get_payload(decode=True) or b""
            try:
                decoded = payload.decode(part.get_content_charset() or "utf-8", errors="strict")
            except (LookupError, UnicodeError):
                notes.append("Charset decoding uncertain; original bytes preserved.")
                decoded = payload.decode("utf-8", errors="replace")
            if part.get_content_type() == "text/html":
                notes.append("HTML fallback: quoted regions may be ambiguous.")
                parser = VisibleHTML()
                parser.feed(decoded)
                decoded = "".join(parser.parts)
            return decoded

        text = extract(root).strip()
        latest, uncertain = latest_reply(text)
        if not text:
            notes.append("No usable message text; inspect the original.")
        return PreparedText(raw, text, latest, uncertain or bool(notes), tuple(notes))
    except (ValueError, TypeError, RecursionError):
        return PreparedText(raw, "", "", True, ("Parsing failed; inspect the original.",))


def parse_email_to_message(
    raw: bytes,
    provider_id: str,
    thread_id: str | None = None,
    internal_date: datetime | None = None,
) -> DomainMessage:
    """Parse raw RFC 822 email bytes into a normalized domain Message object."""
    prepared = prepare_message(raw)
    try:
        root = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception:
        root = None

    subject = ""
    sender_name = ""
    sender = ""
    recipients: list[str] = []
    received_at = internal_date
    references: list[str] = []
    categories: list[str] = []
    trusted_bulk = False
    has_attachments = any("attachment" in n.lower() for n in prepared.notes)

    if root is not None:
        raw_subj = root.get("Subject", "")
        subject = str(raw_subj).strip() or "(no subject)"

        raw_from = root.get("From", "")
        if raw_from:
            parsed_name, parsed_addr = parseaddr(str(raw_from))
            sender = parsed_addr.strip().lower()
            sender_name = parsed_name.strip() or (sender.split("@")[0] if "@" in sender else sender)

        for hdr in ("To", "Cc"):
            for addr_val in root.get_all(hdr, []):
                for part in str(addr_val).split(","):
                    _, email_addr = parseaddr(part)
                    clean_addr = email_addr.strip().lower()
                    if clean_addr and clean_addr not in recipients:
                        recipients.append(clean_addr)

        if received_at is None:
            raw_date = root.get("Date")
            if raw_date:
                try:
                    dt = parsedate_to_datetime(str(raw_date))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=UTC)
                    received_at = dt
                except Exception:
                    pass

        ref_header = root.get("References", "")
        in_reply_to = root.get("In-Reply-To", "")
        for val in (str(ref_header), str(in_reply_to)):
            for token in re.findall(r"<[^>]+>", val):
                if token not in references:
                    references.append(token)

        if root.get("List-Unsubscribe") or str(root.get("Precedence", "")).lower() == "bulk":
            trusted_bulk = True
            if "newsletter" not in categories:
                categories.append("newsletter")

        try:
            for part in root.walk():
                if part.get_content_disposition() == "attachment" or bool(part.get_filename()):
                    has_attachments = True
                    break
        except Exception:
            pass

    if not sender:
        sender = "unknown@unknown.local"
        sender_name = "Unknown Sender"

    if received_at is None:
        received_at = datetime.now(UTC)
    elif received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=UTC)

    body_text = prepared.full_text if prepared.full_text else prepared.latest_text

    return DomainMessage(
        id=provider_id,
        thread_id=thread_id or provider_id,
        sender=sender,
        sender_name=sender_name,
        recipients=recipients or [sender],
        subject=subject[:300],
        body=body_text,
        received_at=received_at,
        references=references,
        categories=categories,
        trusted_bulk=trusted_bulk,
        has_attachments=has_attachments,
        parse_uncertain=prepared.uncertain,
        follow_up=False,
    )
