from concurrent.futures import ThreadPoolExecutor

import pytest

from mossmail.models import State
from mossmail.storage import Store


def test_idempotent_concurrent_retry(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message])

    def park(_):
        return store.transition(message.id, "park", "same-event")

    with ThreadPoolExecutor(max_workers=4) as pool:
        events = list(pool.map(park, range(8)))
    assert all(event == events[0] for event in events)
    assert len(store.history()) == 1
    assert store.get(message.id)["cycle"] == 1


@pytest.mark.parametrize(
    "kind,state",
    [("followup", State.ESCALATED), ("risk", State.ESCALATED), ("expire", State.REVIEW)],
)
def test_reactivation(tmp_path, message, kind, state):
    store = Store(tmp_path / "test.db")
    store.seed([message])
    event = store.transition(message.id, "park", "p")
    store.transition(message.id, kind, "finish", cycle=event["cycle"])
    row = store.get(message.id)
    assert row["state"] == state and not row["parked"] and row["due"] is None


def test_expiry_preserves_user_resolution_and_followup_reopens(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message])
    store.transition(message.id, "park", "p")
    store.transition(message.id, "resolve", "user")
    store.transition(message.id, "expire", "timer", cycle=1)
    assert store.get(message.id)["state"] == State.RESOLVED
    store.transition(message.id, "followup", "new")
    assert store.get(message.id)["state"] == State.ESCALATED


def test_stale_timer_does_not_change_new_cycle(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message])
    store.transition(message.id, "park", "p1")
    store.transition(message.id, "expire", "e1", cycle=1)
    store.transition(message.id, "park", "p2")
    store.transition(message.id, "expire", "stale", cycle=1)
    assert store.get(message.id)["parked"] and store.get(message.id)["cycle"] == 2


def test_ledger_does_not_contain_message_content(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message])
    store.transition(message.id, "park", "p")
    text = str(store.history())
    assert message.body not in text and message.sender not in text and message.subject not in text


def test_duplicate_schedule_and_stale_user_signal(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message])
    store.transition(message.id, "park", "first")
    with pytest.raises(ValueError, match="active parking cycle"):
        store.transition(message.id, "park", "different-workflow")
    store.transition(message.id, "expire", "expiry", cycle=1)
    store.transition(message.id, "park", "second")
    store.transition(message.id, "resolve", "stale-signal", cycle=1)
    assert store.get(message.id)["parked"]
    assert store.get(message.id)["state"] == State.DEFER


def test_safety_and_idempotency_key_misuse(tmp_path, message):
    store = Store(tmp_path / "test.db")
    store.seed([message, message.model_copy(update={"id": "risky", "body": "urgent"})])
    with pytest.raises(ValueError):
        store.transition("risky", "park", "unsafe")
    store.transition(message.id, "park", "p")
    with pytest.raises(ValueError):
        store.transition(message.id, "resolve", "p")
