"""Real Temporal workflow. The dashboard simulator does not invoke this module."""

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from .activities import apply_transition


@workflow.defn
class DeferredMessage:
    def __init__(self):
        self.signal_kind: str | None = None
        self.signal_version = 0
        self.state = "Starting"

    @workflow.signal
    def follow_up(self):
        self.signal_kind = "followup"
        self.signal_version += 1

    @workflow.signal
    def new_risk(self):
        self.signal_kind = "risk"
        self.signal_version += 1

    @workflow.signal
    def user_choice(self, choice: str):
        if choice in {"review", "resolve"}:
            self.signal_kind = choice
            self.signal_version += 1

    @workflow.query
    def status(self) -> str:
        return self.state

    async def apply(self, request: dict) -> dict:
        return await workflow.execute_activity(
            apply_transition,
            request,
            start_to_close_timeout=timedelta(seconds=15),
            schedule_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=15),
                maximum_attempts=5,
            ),
        )

    @workflow.run
    async def run(self, message_id: str, wait_seconds: float = 86400) -> str:
        run_key = workflow.info().run_id
        parked = await self.apply(
            {
                "message_id": message_id,
                "kind": "park",
                "key": run_key + ":park",
                "wait_seconds": wait_seconds,
            }
        )
        self.state = "Parked"
        try:
            await workflow.wait_condition(
                lambda: self.signal_kind is not None, timeout=timedelta(seconds=wait_seconds)
            )
        except TimeoutError:
            pass
        self.state = "Re-evaluating"
        while True:
            version = self.signal_version
            kind = self.signal_kind or "expire"
            result = await self.apply(
                {
                    "message_id": message_id,
                    "kind": kind,
                    "key": f"{run_key}:finish:{version}",
                    "cycle": parked["cycle"],
                }
            )
            self.state = result["state"]
            # A signal delivered while an activity is in flight must be processed too.
            if version == self.signal_version:
                return self.state
