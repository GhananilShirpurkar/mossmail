from datetime import UTC, datetime

import pytest

from mossmail.models import Message


@pytest.fixture
def message():
    return Message(
        id="fixture",
        thread_id="thread-fixture",
        sender="digest@example.test",
        sender_name="Synthetic Digest",
        recipients=["reader@example.test"],
        subject="Reading list",
        body="A few essays for a quiet afternoon.",
        received_at=datetime.now(UTC),
        trusted_bulk=True,
    )
