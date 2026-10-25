# Validation evidence

Validated on 25 October 2026 on Linux with Python 3.13.7, Streamlit 1.66.1, Temporal Python SDK 1.34.0, and Playwright 1.64.1. Versions are recorded in `requirements.lock.txt`.

## Automated checks

Final combined test command:

```text
MOSSMAIL_TEMPORAL_TESTS=1 .venv/bin/pytest -q
66 passed in 2.17s
```

`ruff check .` and `ruff format --check .` passed. The default offline test suite consists of 59 tests; seven Temporal integration cases are skipped unless explicitly enabled. No mailbox credentials, external model account, or downloaded model weights are required by any test. The first Temporal integration run downloads its SDK test-server binary.

Coverage includes:

- MIME alternatives, nested attached messages, charsets, HTML extraction, short replies, quoted text, ambiguous forwards, empty and oversized messages.
- Protected senders; financial, urgent, legal, security, and deadline signals; Unicode normalization; exact risk/uncertainty boundaries; attachments and unknown mail; current and stale user overrides.
- Missing Ollama, missing models, malformed model lists, invalid/extra JSON fields, remote endpoint rejection, prompt-injection separation from policy, and privacy-safe error logging.
- Concurrent repeated events, duplicate scheduling, stale timers and signals, follow-up/risk reactivation, timer expiry, user resolution, and content-free ledger entries.
- Hosted-adapter consent and class-order handling with a fake SDK. This is a contract test, not a hosted inference run.
- Streamlit's real Python application via AppTest, with no model services: rendering, user resolution, waiting-room navigation, and follow-up simulation.

## Real Temporal SDK tests

Seven tests run real workers against Temporal's time-skipping test server: timer expiry, follow-up, risk signal, user resolution, retry after a committed database write, worker replacement with history replay, and a follow-up arriving during an in-flight expiry activity. The recovery case stops the first worker, persists a signal while no worker is running, starts another worker, then replays the history. Workflow caching is disabled in that case to force cold replay and avoid waiting for the previous worker's sticky queue.

An earlier recovery-test version hit its 15-second timeout while waiting on sticky-queue scheduling. The final test uses cold replay and a bounded 30-second result wait. The final full suite passed. A final review also identified and fixed a signal-versus-expiry race: the workflow now processes a newer signal after its in-flight activity returns. This is not a claim of production-scale availability, a multi-host database deployment, or a tested production server restart.

## Genuine local inference

Ollama's installed-model list contained `gemma2:2b` and `qwen2.5:3b`; `gemma3:4b` was not installed. The application default remains `gemma3:4b`, and the actual capture explicitly configured `OLLAMA_MODEL=gemma2:2b`.

An actual local call on synthetic message `m01` returned a schema-valid summary:

> The sender requests feedback on two cover directions for the field guide, asking for a simple preference.

Its proposed action was to review those directions and provide a preference before team sharing. The result was marked `source=local_ai`, `model=gemma2:2b`. This confirms execution on that example; it is not a quality benchmark. The browser captures also display successful local inference and identify the model.

## Browser evidence

The screenshot and video script controls a real Chromium browser against the running Streamlit app. It uses only the fictional example collection. It checks for Streamlit exceptions and verifies that follow-up and expiry events appear in the activity view. Screenshots are inspected for readable layout; no UI state or model output is painted into an image.

See `docs/demo.md` for capture reproduction and artifact descriptions. Model inference and page readiness are awaited before capturing message details. A preliminary screenshot caught a Streamlit rerun before the selected message finished rendering; the capture script was corrected to wait for that message's financial-risk evidence before taking the final screenshot.

The installed application was additionally checked in Chromium at 1440 × 1100 and 390 × 844: the default missing-model fallback rendered without Streamlit exceptions or horizontal overflow.

## Unverified or intentionally absent

- Hosted TabPFN inference and its quality: no hosted account was used or mailbox feature data transmitted.
- `gemma3:4b` inference: default configuration provided, model not installed on this machine.
- Real mailbox synchronization, OAuth, write access, attachments, production authentication, and production mailbox deployment: not implemented.
- Real-user feedback, time savings, training metrics, and generalization: not measured.
- DEV publication: a prepared article in the repository only. Eligibility and publishing remain with the author.


## Community Cloud release

The hosted release is available at [mossmail.streamlit.app](https://mossmail.streamlit.app/). A real browser verified the deployed inbox, synthetic collection, session-isolation notice, labeled fallback excerpts, and absence of the developer toolbar. `docs/screenshots/05-hosted-demo.png` is a genuine capture of that deployment.

The cloud entrypoint adds a regression test proving that two independent sessions use different databases, that one visitor's resolution does not change the other visitor's state, and that the hosted demo never invokes Ollama. Both published GitHub Actions jobs passed for commit `879f1e9`: 60 offline tests and seven real Temporal cases passed (67 tests across the two jobs); the original 66-test result above records the initial local release. The hosted demo is not evidence of cloud Gemma inference or a live Temporal server.
