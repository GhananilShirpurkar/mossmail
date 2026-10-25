# Real UI demo

All shown messages, sender identities, and organizations are fictional. The recording is captured with Playwright from the actual running Streamlit application. The delivered recording is 107.08 seconds at 1440 × 1100. It has no voiceover, fabricated frames, or real mailbox content.

Artifacts:

- `screenshots/01-inbox.png` — primary dashboard, attention counts, and local Gemma reading assistance.
- `screenshots/02-message.png` — selected invoice with summary, next-step advice, risk reasons, and original message.
- `screenshots/03-parked.png` — waiting room with visible review deadlines.
- `screenshots/04-history.png` — simulated follow-up escalation, timer expiry, and seed user resolution.
- `mossmail-demo.webm` — genuine browser session showing the above navigation and workflow simulation.

The application is configured with `OLLAMA_MODEL=gemma2:2b` for this capture. That model was already installed locally. Model loading/inference may be visible in the recording. The source label in the UI is authoritative: `LOCAL AI` means a validated Ollama response; `DEMO FALLBACK` means an excerpt.

The waiting-room controls are simulations. The real Temporal workflow is exercised separately by `MOSSMAIL_TEMPORAL_TESTS=1 pytest -q tests/test_temporal.py`, or by running the server and worker commands in the README. No screenshot implies that an email has been archived or that the UI simulation is a durable server.

## Reproduce

```bash
source .venv/bin/activate
python -m playwright install chromium ffmpeg
# First terminal, from the repository root. Use a new database filename on each run.
OLLAMA_MODEL=gemma2:2b OLLAMA_TIMEOUT=90 \
  MOSSMAIL_DB=.local/capture-new.sqlite3 \
  streamlit run app.py --server.port 8502
# Second terminal, same activated environment:
python scripts/capture_demo.py --url http://127.0.0.1:8502
```

The capture script writes PNGs and a WebM file under `docs/`. Raw temporary recordings remain under ignored `.local/video/`. It changes only the synthetic state in the configured capture database. It navigates Inbox → financial message → Parked → follow-up → timer expiry → Activity.

For a fallback-only demonstration, set `MOSSMAIL_SUMMARIZER=fallback` on the Streamlit process; the UI will label the source honestly. Use an independent database for the actual Temporal demonstration.
