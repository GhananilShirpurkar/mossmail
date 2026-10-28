"""Local SQLite state and idempotent event ledger; never a mailbox action adapter."""

import json
import sqlite3
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .decision_engine import decide
from .models import Message, Override, State
from .policy import Policy


class Store:
    def __init__(self, path: str | Path, policy: Policy | None = None):
        self.path = str(path)
        self.policy = policy or Policy.from_env()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, state TEXT NOT NULL,
                    parked INTEGER NOT NULL DEFAULT 0, due TEXT, override TEXT,
                    cycle INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_key TEXT PRIMARY KEY, message_id TEXT NOT NULL,
                    kind TEXT NOT NULL, state TEXT NOT NULL, mode TEXT NOT NULL,
                    created_at TEXT NOT NULL, cycle INTEGER NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def setting(self, key: str, default: str = "") -> str:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def seed(self, messages: list[Message], now: datetime | None = None):
        now = now or datetime.now(UTC)
        with self.connect() as db:
            for message in messages:
                decision = decide(message, self.policy, now=now)
                db.execute(
                    "INSERT OR IGNORE INTO messages(id,payload,state) VALUES(?,?,?)",
                    (message.id, message.model_dump_json(), decision.state.value),
                )

    def all(self) -> list[dict]:
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM messages ORDER BY id")]

    def get(self, message_id: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if row is None:
            raise KeyError("Unknown message")
        return dict(row)

    def history(self, message_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if message_id:
                rows = db.execute(
                    "SELECT * FROM events WHERE message_id=? ORDER BY rowid DESC", (message_id,)
                )
            else:
                rows = db.execute("SELECT * FROM events ORDER BY rowid DESC")
            return [dict(row) for row in rows]

    def transition(
        self,
        message_id: str,
        kind: str,
        key: str,
        *,
        mode: str = "simulation",
        cycle: int | None = None,
        now: datetime | None = None,
        wait_seconds: float | None = None,
        _db=None,
    ) -> dict:
        if kind not in {"park", "resolve", "review", "followup", "risk", "expire"}:
            raise ValueError("Unknown transition")
        if mode not in {"simulation", "temporal", "local"}:
            raise ValueError("Unknown event mode")
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Use timezone-aware timestamps")
        with self.connect() if _db is None else nullcontext(_db) as db:
            if not db.in_transaction:
                db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM events WHERE event_key=?", (key,)).fetchone()
            if prior:
                if prior["message_id"] != message_id or prior["kind"] != kind:
                    raise ValueError("Idempotency key reused for a different operation")
                return dict(prior)
            row = db.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if not row:
                raise KeyError("Unknown message")
            message = Message.model_validate_json(row["payload"])
            current_cycle = row["cycle"]
            parked, due, state, override = row["parked"], row["due"], row["state"], row["override"]
            if (
                kind in {"followup", "risk", "expire", "resolve", "review"}
                and cycle is not None
                and cycle != current_cycle
            ):
                # Old workflow retries must never mutate a newer parking cycle.
                pass
            elif kind == "park":
                current_override = Override.model_validate_json(override) if override else None
                decision = decide(message, self.policy, override=current_override, now=now)
                if decision.state != State.DEFER:
                    raise ValueError("Policy does not permit parking this message")
                if parked:
                    raise ValueError("Message already has an active parking cycle")
                if not parked:
                    seconds = (
                        wait_seconds if wait_seconds is not None else self.policy.defer_hours * 3600
                    )
                    if not 0 < seconds <= 604800:
                        raise ValueError("Timer must be greater than zero and at most seven days")
                    current_cycle += 1
                    parked, state = 1, State.DEFER.value
                    due = (now + timedelta(seconds=seconds)).isoformat()
            elif kind in {"review", "resolve"}:
                state = State.REVIEW.value if kind == "review" else State.RESOLVED.value
                override = Override(state=State(state), revision=message.revision).model_dump_json()
                parked, due = 0, None
            elif kind in {"followup", "risk"}:
                message = message.model_copy(
                    update={"follow_up": True, "revision": message.revision + 1}
                )
                state = decide(message, self.policy, now=now).state.value
                parked, due, override = 0, None, None
            elif kind == "expire" and parked:
                # Re-evaluate current policy. Even low-risk mail returns for human review.
                decision = decide(message, self.policy, now=now)
                state = (
                    State.ESCALATED.value
                    if decision.state == State.ESCALATED
                    else State.REVIEW.value
                )
                parked, due, override = 0, None, None
            db.execute(
                "UPDATE messages SET payload=?,state=?,parked=?,due=?,override=?,cycle=? "
                "WHERE id=?",
                (
                    message.model_dump_json(),
                    state,
                    parked,
                    due,
                    override,
                    current_cycle,
                    message_id,
                ),
            )
            event = {
                "event_key": key,
                "message_id": message_id,
                "kind": kind,
                "state": state,
                "mode": mode,
                "created_at": now.isoformat(),
                "cycle": current_cycle,
            }
            db.execute(
                "INSERT INTO events VALUES"
                "(:event_key,:message_id,:kind,:state,:mode,:created_at,:cycle)",
                event,
            )
            return event


def load_demo(path: str | Path) -> list[Message]:
    return [Message.model_validate(row) for row in json.loads(Path(path).read_text())]
