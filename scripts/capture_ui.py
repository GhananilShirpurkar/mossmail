"""Capture current UI in a temporary workspace with explicitly labeled test data.

Run: PLAYWRIGHT_BROWSERS_PATH=/path/to/browsers python scripts/capture_ui.py
Requires the existing development dependency and `playwright install chromium`.
Never opens the user's database, credential file, or OS keyring.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mossmail.models import Message  # noqa: E402
from mossmail.storage import Store  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8503)
    args = parser.parse_args()
    images = ROOT / "docs/screenshots/current"
    images.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="mossmail-ui-") as workspace:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("GMAIL_", "GEMINI_", "MOSSMAIL_", "OLLAMA_"))
        }
        db_path = Path(workspace) / "capture.sqlite3"
        env.update(
            {
                "MOSSMAIL_DB": str(db_path),
                "MOSSMAIL_CREDS_FILE": str(Path(workspace) / "credentials.json"),
                "MOSSMAIL_SUMMARIZER": "fallback",
                "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            }
        )
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ROOT / "app.py"),
                "--server.address",
                "127.0.0.1",
                "--server.port",
                str(args.port),
                "--server.headless",
                "true",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            url = f"http://127.0.0.1:{args.port}"
            deadline = monotonic() + 30
            while True:
                try:
                    with urlopen(url + "/_stcore/health", timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if server.poll() is not None or monotonic() > deadline:
                        raise RuntimeError("Isolated screenshot server did not start") from None
                    sleep(0.2)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, reduced_motion="reduce"
                )
                page.on("pageerror", lambda error: print("Browser rendering error:", error))
                page.goto(url)
                expect(page.get_by_role("heading", name="Welcome to MossMail")).to_be_visible()
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(path=str(images / "01-welcome.png"), full_page=True)
                page.get_by_role("button", name="Set up now", exact=True).focus()
                page.keyboard.press("Tab")
                expect(page.get_by_role("button", name="Skip for now", exact=True)).to_be_focused()
                page.keyboard.press("Enter")
                expect(page.get_by_role("heading", name="No stored messages")).to_be_visible()
                assert Store(db_path).all() == []
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(path=str(images / "02-empty-inbox.png"), full_page=True)
                page.get_by_test_id("stSidebar").get_by_text("Settings", exact=True).click()
                expect(page.get_by_role("heading", name="Integrations", exact=True)).to_be_visible()
                expect(page.get_by_text("OAuth not configured", exact=False)).to_be_visible()
                page.set_viewport_size({"width": 1440, "height": 1500})
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(path=str(images / "03-settings.png"), full_page=True)
                page.get_by_text("Google Gemini API (BYOK)", exact=True).click()
                expect(page.get_by_role("button", name="Test & Save Key")).to_be_visible()
                expect(page.get_by_role("combobox")).to_be_visible()
                expect(page.get_by_text("Select Model", exact=True)).to_be_visible()
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(path=str(images / "04-gemini-settings.png"), full_page=True)
                store = Store(db_path)
                store.seed(
                    [
                        Message(
                            id=f"ui-test-{index}",
                            thread_id=f"ui-test-thread-{index}",
                            sender="fixture@example.test",
                            sender_name="UI test fixture · Morgan",
                            recipients=["test-reader@example.test"],
                            subject="[UI TEST FIXTURE] " + subject,
                            body=(
                                "Isolated screenshot test data. "
                                "Please review the original before making a local decision."
                            ),
                            received_at=datetime.now(UTC),
                        )
                        for index, subject in enumerate(
                            ["Review project notes", "Meeting agenda", "Reading list"]
                        )
                    ]
                )
                page.set_viewport_size({"width": 1440, "height": 1100})
                page.get_by_test_id("stSidebar").get_by_text("Inbox", exact=True).click()
                expect(page.get_by_role("button", name="Mark resolved", exact=True)).to_be_visible()
                expect(page.get_by_text("ORIGINAL EXCERPT · NO AI", exact=True)).to_be_visible()
                expect(page.get_by_test_id("stException")).to_have_count(0)
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(path=str(images / "05-inbox-test-fixtures.png"), full_page=True)
                page.get_by_role("button", name="Mark resolved", exact=True).focus()
                page.keyboard.press("Enter")
                expect(
                    page.get_by_role("button", name="Mark resolved", exact=True)
                ).to_be_disabled()
                assert any(row["state"] == "Resolved" for row in Store(db_path).all())
                page.reload()
                expect(
                    page.get_by_role("button", name="Mark resolved", exact=True)
                ).to_be_disabled()
                page.get_by_test_id("stSidebar").hover()
                page.get_by_role("button", name="Collapse sidebar", exact=True).click()
                page.set_viewport_size({"width": 760, "height": 1000})
                expect(page.get_by_test_id("stSidebar")).to_have_attribute("data-collapsed", "true")
                page.wait_for_function(
                    "document.querySelector('[data-testid=stSidebar]')"
                    ".getBoundingClientRect().right <= 1"
                )
                page.get_by_test_id("stMain").evaluate("el => { el.scrollTop = 0; }")
                expect(page.get_by_test_id("stApp")).to_have_attribute(
                    "data-test-script-state", "notRunning"
                )
                page.screenshot(
                    path=str(images / "06-narrow-inbox-test-fixtures.png"), full_page=True
                )
                expect(page.get_by_test_id("stException")).to_have_count(0)
                browser.close()
            print(
                "Captured six screens; verified empty start, configuration navigation, "
                "keyboard setup dismissal and resolution, restart and narrow layout."
            )
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
