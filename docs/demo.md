# Current 60-second walkthrough

[Watch the video](mossmail-demo-current.mp4)

This is a continuous recording of the current local Streamlit application, using a temporary SQLite database. A **TEST INBOX** banner and message subjects identify fictional fixtures. The capture wrapper provides that banner; it is not a product mode or a claim that a fresh installation contains messages.

## Walkthrough

- **00–07 seconds:** optional first-run setup.
- **07–12 seconds:** skip setup and see a genuinely empty inbox.
- **12–24 seconds:** the capture tool explicitly loads two fictional messages into its temporary database, then reloads the UI. Inspect the invoice, financial review rule, and original text.
- **24–30 seconds:** open a locally curated reading-list fixture and inspect its safe-to-defer recommendation. The fixture explicitly sets trusted bulk metadata; this is not an automatic classification of unknown Gmail senders.
- **30–38 seconds:** choose **Park for later** and inspect its persisted local review deadline in **Parked**.
- **38–45 seconds:** mark that fixture resolved and inspect the actual local event history in **Activity**.
- **45–53 seconds:** inspect optional integration settings without configuring an account or key.
- **53–60 seconds:** return to the inbox and reload; the resolved decision persists and the financial message remains in review.

No real inbox, OAuth flow, provider account, AI inference, or Temporal worker is exercised here. All visible excerpts are labeled **ORIGINAL EXCERPT · NO AI**. No mailbox action or time-saving claim is implied. Local parking is real SQLite state; its deadline is checked when the UI runs, not by a background service.

## Capture boundary

The recorder strips Gmail, Gemini, Ollama, and MossMail environment variables, disables the OS keyring, sets a temporary credential-file path, and forces deterministic excerpts. It starts the real app on loopback in an isolated browser profile. The database and profile are removed afterward. The capture creates no credential file and verifies parking, resolution, reload persistence, and absence of browser errors.

This recording used the already installed system Chrome and FFmpeg with existing browser automation tooling. No browser, Python package, model, or other dependency was downloaded or installed for it. The delivered MP4 is a compatible encoding of the continuous raw WebM; no scenes are fabricated or sped up.

To repeat the sequence manually, use a new `MOSSMAIL_DB` and `MOSSMAIL_CREDS_FILE`, disable keyring access, and set `MOSSMAIL_SUMMARIZER=fallback`. Open the actual app, verify the empty state, and explicitly create labeled synthetic fixtures only in that separate database before recording the steps above. Never point capture tools at your normal inbox database. The existing `scripts/capture_ui.py` automates isolated still screenshots; it does not produce this video.

The [prototype recording](demo-prototype.md) is retained as historical evidence and shows retired behavior. It is not the video linked from the README or public landing entrypoint.
