# Current UI captures

Captured from local Chromium and Streamlit using `scripts/capture_ui.py`. All credential stores were isolated; no provider requests or personal messages were used.

- [Welcome and optional setup](01-welcome.png)
- [Unconfigured empty inbox](02-empty-inbox.png)
- [Gmail and local-provider settings](03-settings.png)
- [Optional Gemini configuration](04-gemini-settings.png)
- [Populated inbox — isolated test fixtures](05-inbox-test-fixtures.png)
- [Narrow inbox — isolated test fixtures](06-narrow-inbox-test-fixtures.png)

The populated screenshots intentionally identify every message as **UI TEST FIXTURE**. These records are created only by this explicitly invoked capture tool in a temporary SQLite database and removed when it exits. The capture also verifies Tab/Enter setup dismissal and keyboard activation of a local resolution that survives reload. Older screenshots in the parent directory show the historical prototype.

The README also links a [current 60-second video](../../demo.md) through an [animated GIF preview](../../mossmail-demo-current.gif). A [still poster from the recording](demo-preview.png) is retained here. Its two fictional messages are labeled **TEST INBOX** and come from a separate temporary database.
