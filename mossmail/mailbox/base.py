"""Abstract mailbox provider interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from mossmail.models import Message


@dataclass(frozen=True)
class MessageMetadata:
    id: str
    thread_id: str
    internal_date: datetime | None = None
    snippet: str | None = None


class MailboxProvider(ABC):
    """Abstract provider for email inboxes (e.g. Gmail, IMAP)."""

    @abstractmethod
    def list_messages(
        self, limit: int = 20, page_token: str | None = None
    ) -> tuple[list[MessageMetadata], str | None]:
        """List messages in the inbox with pagination. Returns (metadata_list, next_page_token)."""
        ...

    @abstractmethod
    def get_message_raw(self, provider_id: str) -> bytes:
        """Fetch raw RFC 822 email bytes by provider ID."""
        ...

    @abstractmethod
    def get_message(self, provider_id: str) -> Message:
        """Fetch and parse a message into a normalized domain Message object."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Check whether the mailbox provider is connected and authenticated."""
        ...
