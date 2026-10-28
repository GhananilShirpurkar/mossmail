"""Mailbox provider abstractions and implementations."""

from mossmail.mailbox.base import MailboxProvider, MessageMetadata
from mossmail.mailbox.gmail import (
    AuthenticationRequiredError,
    GmailAPIError,
    GmailProvider,
    OAuthError,
    RateLimitError,
    ScopeViolationError,
    TokenRevokedError,
    extract_code_from_redirect,
)
from mossmail.mailbox.sync import SyncReport, sync_inbox

__all__ = [
    "AuthenticationRequiredError",
    "GmailAPIError",
    "GmailProvider",
    "MailboxProvider",
    "MessageMetadata",
    "OAuthError",
    "RateLimitError",
    "ScopeViolationError",
    "SyncReport",
    "TokenRevokedError",
    "extract_code_from_redirect",
    "sync_inbox",
]
