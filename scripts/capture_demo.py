"""Capture the real UI. Start Streamlit separately with a fresh capture database.

Run: python scripts/capture_demo.py --url http://127.0.0.1:8502
Requires: playwright install chromium ffmpeg
"""

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8502")
    args = parser.parse_args()
    images = ROOT / "docs/screenshots"
    images.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1100},
            record_video_dir=str(ROOT / ".local/video"),
            record_video_size={"width": 1440, "height": 1100},
            reduced_motion="reduce",
        )
        page = context.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(30000)
        page.goto(args.url)
        page.get_by_role("button", name="Mark resolved", exact=True).wait_for(timeout=120000)
        expect(page.get_by_test_id("stException")).to_have_count(0)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(images / "01-inbox.png"))
        print("Inbox captured", flush=True)
        page.get_by_role("button", name="Open", exact=True).first.click()
        heading = page.get_by_role("heading", name="Invoice 1048 needs your approval", exact=True)
        heading.wait_for(timeout=120000)
        page.get_by_role("button", name="Mark resolved", exact=True).wait_for(timeout=120000)
        page.get_by_test_id("stSpinner").wait_for(state="hidden", timeout=120000)
        expect(
            page.get_by_text("· Financial signal in message or trusted metadata.", exact=True)
        ).to_be_visible(timeout=120000)
        expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible(
            timeout=120000
        )
        page.get_by_text("Read the original message", exact=True).click()
        page.get_by_test_id("stMain").evaluate("el => { el.scrollTop = 400; }")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(images / "02-message.png"))
        print("Message captured", flush=True)
        page.get_by_test_id("stSidebar").get_by_text("Parked", exact=True).click()
        page.get_by_role("button", name="Simulate follow-up", exact=True).wait_for(timeout=120000)
        expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible(
            timeout=120000
        )
        page.get_by_test_id("stSpinner").wait_for(state="hidden", timeout=120000)
        page.get_by_test_id("stMain").evaluate("el => { el.scrollTop = 0; }")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(images / "03-parked.png"))
        print("Parked view captured", flush=True)
        page.get_by_role(
            "button", name="Simulate follow-up", exact=True
        ).scroll_into_view_if_needed()
        page.wait_for_timeout(2000)
        page.get_by_role("button", name="Simulate follow-up", exact=True).click()
        page.get_by_role(
            "heading", name="Your weekly collection of good ideas", exact=True
        ).wait_for(timeout=120000)
        page.get_by_test_id("stSpinner").wait_for(state="hidden", timeout=120000)
        page.get_by_role("button", name="Preview timer expiry", exact=True).click()
        page.get_by_role("heading", name="Notes from around the neighborhood", exact=True).wait_for(
            timeout=120000
        )
        page.get_by_test_id("stSpinner").wait_for(state="hidden", timeout=120000)
        page.get_by_test_id("stSidebar").get_by_text("Activity", exact=True).click()
        page.get_by_role("heading", name="Your decision history", exact=True).wait_for(
            timeout=120000
        )
        page.get_by_test_id("stMain").evaluate("el => { el.scrollTop = 0; }")
        page.wait_for_timeout(2500)
        page.screenshot(path=str(images / "04-history.png"))
        expect(page.get_by_text("Timer expired · returned for review", exact=True)).to_be_visible()
        expect(page.get_by_text("Follow-up received · escalated", exact=True).first).to_be_visible()
        expect(page.get_by_test_id("stException")).to_have_count(0)
        page.wait_for_timeout(3500)
        video = page.video
        await_path = ROOT / "docs/mossmail-demo.webm"
        context.close()
        video.save_as(str(await_path))
        browser.close()
        print("Saved four genuine screenshots and", await_path)


if __name__ == "__main__":
    main()
