from datetime import UTC, datetime, timedelta

from .models import Decision, Message, Override, State
from .policy import Policy, risk_evidence
from .scoring import BaselineScorer, Scorer


def decide(
    message: Message,
    policy: Policy | None = None,
    scorer: Scorer | None = None,
    override: Override | None = None,
    now: datetime | None = None,
) -> Decision:
    policy = policy or Policy()
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Use timezone-aware timestamps")
    score = (scorer or BaselineScorer()).score(message)
    guards = risk_evidence(message)
    protected = message.sender.strip().casefold() in policy.protected_senders
    if protected:
        guards.insert(0, "Sender is on your protected list.")
    unsafe = bool(guards) or message.parse_uncertain or message.has_attachments
    reasons = guards + score.evidence
    state, action = State.REVIEW, "Review the original message before deciding."
    review_at = None
    overridden = False
    if override and override.revision == message.revision:
        if override.state == State.DEFER and unsafe:
            reasons.insert(0, "Parking blocked by a protection rule; keep this message visible.")
        else:
            state = override.state
            overridden = True
            reasons.insert(0, "Your explicit choice takes precedence for this message revision.")
            action = "Your choice is recorded locally; no mailbox was modified."
            if state == State.DEFER:
                review_at = now + timedelta(hours=policy.defer_hours)
    elif message.follow_up:
        state, action = (
            State.ESCALATED,
            "Review the new follow-up; the previous parking is cancelled.",
        )
        reasons.insert(0, "A new follow-up or risk signal reactivated this thread.")
    elif guards:
        reasons.insert(0, "Safety rule: this message must stay visible.")
    elif (
        not unsafe
        and message.body.strip()
        and message.trusted_bulk
        and score.risk <= policy.max_defer_risk
        and score.uncertainty <= policy.max_uncertainty
    ):
        state, action = (
            State.DEFER,
            "Park locally, then return for review. No deletion or archival.",
        )
        review_at = now + timedelta(hours=policy.defer_hours)
    else:
        reasons.insert(0, "Insufficient confidence to defer; a person should review this.")
    return Decision(
        state=state,
        score=score,
        reasons=list(dict.fromkeys(reasons)),
        action=action,
        review_at=review_at,
        protected=protected,
        overridden=overridden,
    )
