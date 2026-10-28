from datetime import UTC, datetime, timedelta

import pytest

from mossmail.decision_engine import decide
from mossmail.models import Override, Score, State
from mossmail.policy import Policy


def test_low_risk_has_bounded_review_deadline(message):
    now = datetime.now(UTC)
    result = decide(message, now=now)
    assert result.state == State.DEFER
    assert result.review_at == now + timedelta(hours=24)
    assert "No deletion" in result.action


@pytest.mark.parametrize(
    "text",
    [
        "URGENT",
        "invoice",
        "bank payment",
        "contract",
        "legal",
        "security alert",
        "password",
        "deadline tomorrow",
        "due Friday",
        "expires tonight",
        "ＵＲＧＥＮＴ",
        "pa\u200byment",
    ],
)
def test_high_risk_is_never_automatically_suppressed(message, text):
    result = decide(message.model_copy(update={"body": text}))
    assert result.state == State.REVIEW
    assert result.review_at is None


def test_protected_sender_is_case_insensitive(message):
    result = decide(
        message.model_copy(update={"sender": " MAYA@CEDAR.EXAMPLE "}),
        policy=Policy(protected_senders=frozenset({"maya@cedar.example"})),
    )
    assert result.state == State.REVIEW and result.protected


@pytest.mark.parametrize(
    "update",
    [
        {"trusted_bulk": False},
        {"has_attachments": True},
        {"parse_uncertain": True},
        {"body": ""},
        {"deadline": datetime.now(UTC) + timedelta(days=20)},
    ],
)
def test_uncertain_or_deadline_content_stays_visible(message, update):
    assert decide(message.model_copy(update=update)).state == State.REVIEW


@pytest.mark.parametrize(
    "risk,uncertainty,expected",
    [
        (0.25, 0.25, State.DEFER),
        (0.251, 0.1, State.REVIEW),
        (0.1, 0.251, State.REVIEW),
    ],
)
def test_policy_boundaries(message, risk, uncertainty, expected):
    class Fixed:
        def score(self, _):
            return Score(risk=risk, uncertainty=uncertainty, method="fixture", evidence=[])

    assert decide(message, scorer=Fixed()).state == expected


def test_followup_and_current_override(message):
    updated = message.model_copy(update={"follow_up": True, "revision": 1})
    old = Override(state=State.RESOLVED, revision=0)
    assert decide(updated, override=old).state == State.ESCALATED
    current = Override(state=State.RESOLVED, revision=1)
    assert decide(updated, override=current).state == State.RESOLVED
    assert decide(updated, override=current).overridden


def test_protected_deferral_override_rejected_but_resolution_allowed(message):
    message = message.model_copy(update={"body": "urgent payment"})
    assert decide(message, override=Override(state=State.DEFER, revision=0)).state == State.REVIEW
    assert (
        decide(message, override=Override(state=State.RESOLVED, revision=0)).state == State.RESOLVED
    )


def test_risk_guard_independent_of_model(message):
    class Optimistic:
        def score(self, _):
            return Score(risk=0, uncertainty=0, method="bad-model", evidence=[])

    assert (
        decide(message.model_copy(update={"body": "legal contract"}), scorer=Optimistic()).state
        == State.REVIEW
    )


def test_invalid_timer_rejected():
    with pytest.raises(ValueError):
        Policy(defer_hours=-1)
