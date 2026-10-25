"""Tests for inbox synchronization, deduplication, and thread escalation."""

from datetime import UTC, datetime

from mossmail.mailbox.base import MailboxProvider, MessageMetadata
from mossmail.mailbox.sync import SyncReport, sync_inbox
from mossmail.models import Message, State
from mossmail.storage import Store


class MockMailboxProvider(MailboxProvider):
    def __init__(self, messages: list[Message]):
        self._messages = {m.id: m for m in messages}
        self.connected = True

    def is_connected(self) -> bool:
        return self.connected

    def list_messages(
        self, limit: int = 20, page_token: str | None = None
    ) -> tuple[list[MessageMetadata], str | None]:
        items = [
            MessageMetadata(id=m.id, thread_id=m.thread_id)
            for m in list(self._messages.values())[:limit]
        ]
        return items, None

    def get_message_raw(self, provider_id: str) -> bytes:
        m = self._messages[provider_id]
        return f"From: {m.sender}\r\nSubject: {m.subject}\r\n\r\n{m.body}".encode()

    def get_message(self, provider_id: str) -> Message:
        if provider_id not in self._messages:
            raise KeyError(f"Message {provider_id} not found")
        return self._messages[provider_id]


def test_sync_inbox_deduplication_and_idempotency(tmp_path):
    store = Store(tmp_path / "test_store.sqlite3")
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    msg1 = Message(
        id="gmail_001",
        thread_id="thread_001",
        sender="bob@example.com",
        sender_name="Bob",
        recipients=["me@example.com"],
        subject="First Email",
        body="Hello world",
        received_at=now,
    )
    provider = MockMailboxProvider([msg1])

    # First sync: 1 new message imported
    report1: SyncReport = sync_inbox(provider, store, limit=10, now=now)
    assert report1.total_found == 1
    assert report1.new_count == 1
    assert report1.existing_count == 0
    assert len(store.all()) == 1

    # Second sync: idempotent, 0 new messages, 1 existing skipped
    report2: SyncReport = sync_inbox(provider, store, limit=10, now=now)
    assert report2.total_found == 1
    assert report2.new_count == 0
    assert report2.existing_count == 1
    assert len(store.all()) == 1


def test_sync_inbox_thread_escalation(tmp_path):
    store = Store(tmp_path / "test_store.sqlite3")
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    # Message 1 is a low-risk trusted bulk message eligible to park
    msg1 = Message(
        id="gmail_100",
        thread_id="thread_shared_project",
        sender="newsletter@updates.example",
        sender_name="Weekly Updates",
        recipients=["me@example.com"],
        subject="Project Status Update",
        body="General summary of the week.",
        received_at=now,
        trusted_bulk=True,
    )

    provider1 = MockMailboxProvider([msg1])
    sync_inbox(provider1, store, limit=10, now=now)

    # Verify msg1 is Safe to defer and park it
    assert store.get("gmail_100")["state"] == State.DEFER.value
    store.transition("gmail_100", "park", "test-park-gmail-100", now=now)
    assert store.get("gmail_100")["parked"] == 1

    # Message 2 arrives later in the exact same thread!
    msg2 = Message(
        id="gmail_101",
        thread_id="thread_shared_project",
        sender="colleague@updates.example",
        sender_name="Colleague",
        recipients=["me@example.com"],
        subject="Re: Project Status Update",
        body="Hey, there is an urgent change we need to discuss.",
        received_at=now,
    )

    provider2 = MockMailboxProvider([msg1, msg2])
    report: SyncReport = sync_inbox(provider2, store, limit=10, now=now)

    assert report.new_count == 1
    assert report.existing_count == 1
    assert report.escalated_count == 1

    # The previously parked message must have been reactivated (unparked & escalated)!
    row1 = store.get("gmail_100")
    assert row1["parked"] == 0
    assert row1["due"] is None
    assert row1["state"] == State.ESCALATED.value

    # Verify event ledger entry exists for the follow-up reactivation
    history = store.history("gmail_100")
    assert any(h["kind"] == "followup" and "sync:followup" in h["event_key"] for h in history)


def test_sync_partial_failure_tolerance(tmp_path):
    store = Store(tmp_path / "test_store.sqlite3")
    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=UTC)

    class FailingProvider(MailboxProvider):
        def is_connected(self) -> bool:
            return True

        def list_messages(self, limit=20, page_token=None):
            return [
                MessageMetadata(id="ok_01", thread_id="t1"),
                MessageMetadata(id="fail_02", thread_id="t2"),
                MessageMetadata(id="ok_03", thread_id="t3"),
            ], None

        def get_message_raw(self, provider_id: str) -> bytes:
            return b""

        def get_message(self, provider_id: str) -> Message:
            if provider_id == "fail_02":
                raise RuntimeError("Corrupted MIME payload on remote server")
            return Message(
                id=provider_id,
                thread_id=f"thread_{provider_id}",
                sender="sender@example.com",
                sender_name="Sender",
                recipients=["me@example.com"],
                subject=f"Subject {provider_id}",
                body="Message content",
                received_at=now,
            )

    provider = FailingProvider()
    report = sync_inbox(provider, store, limit=10, now=now)

    # ok_01 and ok_03 must be saved, fail_02 must be recorded in errors without crashing
    assert report.new_count == 2
    assert len(report.errors) == 1
    assert "fail_02" in report.errors[0]
    assert len(store.all()) == 2
