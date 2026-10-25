import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from mossmail.activities import apply_transition
from mossmail.models import State
from mossmail.storage import Store
from mossmail.workflows import DeferredMessage

pytestmark = [
    pytest.mark.temporal,
    pytest.mark.skipif(
        os.getenv("MOSSMAIL_TEMPORAL_TESTS") != "1", reason="Opt-in: downloads Temporal test server"
    ),
]


@pytest.mark.parametrize(
    "signal,expected",
    [
        (None, State.REVIEW),
        ("followup", State.ESCALATED),
        ("risk", State.ESCALATED),
        ("resolve", State.RESOLVED),
    ],
)
async def test_real_workflow_time_and_signals(tmp_path, message, monkeypatch, signal, expected):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "temporal.db"))
    store = Store(tmp_path / "temporal.db")
    store.seed([message])
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = "test-" + str(uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[DeferredMessage], activities=[apply_transition]
        ):
            handle = await env.client.start_workflow(
                DeferredMessage.run, args=[message.id, 86400], id=str(uuid4()), task_queue=queue
            )
            if signal == "followup":
                await handle.signal(DeferredMessage.follow_up)
            elif signal == "risk":
                await handle.signal(DeferredMessage.new_risk)
            elif signal:
                await handle.signal(DeferredMessage.user_choice, signal)
            assert await handle.result() == expected
    assert store.get(message.id)["state"] == expected
    assert len(store.history()) == 2


async def test_worker_restart_and_history_replay(tmp_path, message, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "restart.db"))
    store = Store(tmp_path / "restart.db")
    store.seed([message])
    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = "restart-" + str(uuid4())
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[DeferredMessage],
            activities=[apply_transition],
            max_cached_workflows=0,
        ):
            handle = await env.client.start_workflow(
                DeferredMessage.run, args=[message.id, 86400], id=str(uuid4()), task_queue=queue
            )
            async with asyncio.timeout(10):
                while not store.get(message.id)["parked"]:
                    await asyncio.sleep(0.02)
        # Signal is persisted while no worker is running.
        await handle.signal(DeferredMessage.follow_up)
        async with Worker(
            env.client,
            task_queue=queue,
            workflows=[DeferredMessage],
            activities=[apply_transition],
            max_cached_workflows=0,
        ):
            assert await asyncio.wait_for(handle.result(), timeout=30) == State.ESCALATED
            history = await handle.fetch_history()
        await Replayer(workflows=[DeferredMessage]).replay_workflow(history)
    assert store.get(message.id)["state"] == State.ESCALATED
    assert all(e["mode"] == "temporal" for e in store.history())


async def test_real_retry_after_commit_is_idempotent(tmp_path, message, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "retry.db"))
    store = Store(tmp_path / "retry.db")
    store.seed([message])
    attempts = []

    @activity.defn(name="apply_transition")
    async def flaky(request: dict) -> dict:
        result = await apply_transition(request)
        attempts.append(activity.info().attempt)
        if activity.info().attempt == 1:
            raise RuntimeError("Synthetic failure after local commit")
        return result

    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = "retry-" + str(uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[DeferredMessage], activities=[flaky]
        ):
            result = await env.client.execute_workflow(
                DeferredMessage.run,
                args=[message.id, 1],
                id=str(uuid4()),
                task_queue=queue,
                execution_timeout=timedelta(minutes=5),
            )
    assert result == State.REVIEW and 2 in attempts
    assert len(store.history()) == 2


async def test_followup_during_expiry_activity_is_not_lost(tmp_path, message, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "race.db"))
    store = Store(tmp_path / "race.db")
    store.seed([message])
    started, release = asyncio.Event(), asyncio.Event()

    @activity.defn(name="apply_transition")
    async def delayed(request: dict) -> dict:
        if request["kind"] == "expire":
            started.set()
            await release.wait()
        return await apply_transition(request)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        queue = "race-" + str(uuid4())
        async with Worker(
            env.client, task_queue=queue, workflows=[DeferredMessage], activities=[delayed]
        ):
            handle = await env.client.start_workflow(
                DeferredMessage.run, args=[message.id, 1], id=str(uuid4()), task_queue=queue
            )
            result = asyncio.create_task(handle.result())
            try:
                await asyncio.wait_for(started.wait(), timeout=10)
                await handle.signal(DeferredMessage.follow_up)
                release.set()
                assert await asyncio.wait_for(result, timeout=20) == State.ESCALATED
            finally:
                release.set()
                if not result.done():
                    result.cancel()
                    await asyncio.gather(result, return_exceptions=True)
    assert [event["kind"] for event in store.history()] == ["followup", "expire", "park"]
