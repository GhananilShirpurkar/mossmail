import os
import re
import unicodedata
from dataclasses import dataclass

from .models import Message

RISK_TERMS = {
    "urgent": r"\b(urgent|asap|emergency|immediate|action required)\b",
    "financial": r"\b(invoice|payment|bank|wire|refund|payroll|tax|billing|overdue)\b",
    "legal": r"\b(legal|contract|lawsuit|subpoena|compliance|court|nda)\b",
    "security": r"\b(security|password|breach|suspicious|sign.in|verification code|otp)\b",
    "deadline": r"\b(deadline|due|expires?|expiry|by tomorrow|by tonight|by eod|by friday)\b",
}


@dataclass(frozen=True)
class Policy:
    protected_senders: frozenset[str] = frozenset()
    defer_hours: float = 24
    max_defer_risk: float = 0.25
    max_uncertainty: float = 0.25

    def __post_init__(self):
        if not 0 < self.defer_hours <= 168:
            raise ValueError("Deferral must be greater than zero and at most 168 hours")

    @classmethod
    def from_env(cls) -> "Policy":
        default = ""
        return cls(
            protected_senders=frozenset(
                s.strip().casefold()
                for s in os.getenv("MOSSMAIL_PROTECTED_SENDERS", default).split(",")
                if s.strip()
            ),
            defer_hours=float(os.getenv("MOSSMAIL_DEFER_HOURS", "24")),
        )


def risk_evidence(message: Message) -> list[str]:
    text = unicodedata.normalize("NFKC", message.subject + "\n" + message.body).casefold()
    # Remove zero-width formatting characters used to split obvious keywords.
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    evidence = []
    for category, pattern in RISK_TERMS.items():
        if category in message.categories or re.search(pattern, text):
            evidence.append(f"{category.title()} signal in message or trusted metadata.")
    if message.deadline:
        evidence.append("Explicit deadline metadata: keep visible until reviewed.")
    return evidence
