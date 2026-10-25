"""Run a worker or exercise real workflows on seeded synthetic messages."""

import argparse
import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from .activities import apply_transition
from .workflows import DeferredMessage

QUEUE = "mossmail-deferred"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["worker", "start", "followup", "risk", "review", "resolve", "status"]
    )
    parser.add_argument("--message", default="m06")
    parser.add_argument("--seconds", type=float, default=86400)
    args = parser.parse_args()
    client = await Client.connect(
        os.getenv("TEMPORAL_ADDRESS", "localhost:7233"),
        namespace=os.getenv("TEMPORAL_NAMESPACE", "default"),
    )
    if args.command == "worker":
        async with Worker(
            client, task_queue=QUEUE, workflows=[DeferredMessage], activities=[apply_transition]
        ):
            await asyncio.Event().wait()
        return
    workflow_id = "mossmail-" + args.message
    if args.command == "start":
        await client.start_workflow(
            DeferredMessage.run, args=[args.message, args.seconds], id=workflow_id, task_queue=QUEUE
        )
        print("Started durable workflow:", workflow_id)
        return
    handle = client.get_workflow_handle(workflow_id)
    if args.command == "status":
        print(await handle.query(DeferredMessage.status))
    elif args.command == "followup":
        await handle.signal(DeferredMessage.follow_up)
    elif args.command == "risk":
        await handle.signal(DeferredMessage.new_risk)
    else:
        await handle.signal(DeferredMessage.user_choice, args.command)


if __name__ == "__main__":
    asyncio.run(main())
