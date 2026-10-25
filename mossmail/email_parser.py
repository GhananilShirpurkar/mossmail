"""Conservative MIME preparation. Original bytes always remain available to the caller."""

import re
from dataclasses import dataclass
from email import policy
from email.message import Message
from email.parser import BytesParser
from html.parser import HTMLParser


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

        def extract(part: Message, depth: int = 0) -> str:
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
