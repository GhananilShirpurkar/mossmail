"""Seed synthetic messages for a separate real Temporal demonstration."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mossmail.storage import Store, load_demo  # noqa: E402

store = Store(os.getenv("MOSSMAIL_DB", ".local/temporal.sqlite3"))
store.seed(load_demo(ROOT / "data/demo_emails.json"))
print("Synthetic messages seeded. No messages parked yet.")
