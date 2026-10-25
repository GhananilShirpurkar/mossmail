"""Manual inbox synchronization with deduplication and thread follow-up escalation."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from mossmail.decision_engine import decide
from mossmail.mailbox.base import MailboxProvider
from mossmail.models import Message
from mossmail.storage import Store

logger = logging.getLogger("mossmail.mailbox.sync")


@dataclass
class SyncReport:
    total_found: int = 0
    new_count: int = 0
    existing_count: int = 0
    escalated_count: int = 0
    errors: list[str] = field(default_factory=list)


def sync_inbox(
    provider: MailboxProvider,
    store: Store,
    limit: int = 20,
    now: datetime | None = None,
) -> SyncReport:
    """Synchronize recent messages from the mailbox provider into local storage.

    - Safe and read-only.
    - Deduplicates by stable message ID.
    - Preserves existing user decisions on older messages.
    - Automatically escalates previously parked threads when a new reply arrives.
    - Resilient to individual message errors or missing payloads.
    """
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("Use timezone-aware timestamps")

    report = SyncReport()

    try:
        messages_meta, _ = provider.list_messages(limit=limit)
    except Exception as e:
        logger.info("sync_list_messages_failed")
        report.errors.append(f"Failed to list messages: {e}")
        return report

    report.total_found = len(messages_meta)

    # Pre-load known message IDs and active parked threads from the local store
    with store.connect() as db:
        existing_rows = db.execute("SELECT id, payload, parked, state FROM messages").fetchall()

    known_ids = {row["id"] for row in existing_rows}
    # Map thread_id -> list of parked message IDs
    parked_by_thread: dict[str, list[str]] = {}
    for row in existing_rows:
        if row["parked"]:
            try:
                m_payload = Message.model_validate_json(row["payload"])
                parked_by_thread.setdefault(m_payload.thread_id, []).append(row["id"])
            except Exception:
                pass

    for meta in messages_meta:
        if meta.id in known_ids:
            report.existing_count += 1
            continue

        try:
            msg: Message = provider.get_message(meta.id)
        except Exception as err:
            logger.info("sync_get_message_failed", extra={"id": meta.id})
            report.errors.append(f"Could not fetch message '{meta.id}': {err}")
            continue

        # Check for thread escalation: did a new message arrive in a parked thread?
        matching_parked = parked_by_thread.get(msg.thread_id, [])
        for parked_id in matching_parked:
            try:
                store.transition(
                    parked_id,
                    "followup",
                    key=f"sync:followup:{parked_id}:{msg.id}",
                    now=now,
                )
                report.escalated_count += 1
            except Exception as e:
                logger.info("sync_escalation_failed", extra={"parked_id": parked_id})
                report.errors.append(f"Failed to escalate parked thread for {parked_id}: {e}")

        # Once a thread is escalated, it's no longer parked
        if matching_parked:
            parked_by_thread.pop(msg.thread_id, None)

        # Compute deterministic decision for the newly imported message
        decision = decide(msg, store.policy, now=now)

        # Insert new message into local store
        with store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO messages(id, payload, state) VALUES(?, ?, ?)",
                (msg.id, msg.model_dump_json(), decision.state.value),
            )

        known_ids.add(msg.id)
        report.new_count += 1

    return report
