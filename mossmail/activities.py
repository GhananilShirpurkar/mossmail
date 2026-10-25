import os

from temporalio import activity
from temporalio.exceptions import ApplicationError

from .storage import Store


@activity.defn
async def apply_transition(request: dict) -> dict:
    """History receives opaque IDs and state only, never email content or summaries."""
    try:
        store = Store(os.getenv("MOSSMAIL_DB", ".local/mossmail.sqlite3"))
        return store.transition(**request, mode="temporal")
    except (ValueError, KeyError) as exc:
        raise ApplicationError(
            "Transition rejected by policy or missing message", non_retryable=True
        ) from exc
