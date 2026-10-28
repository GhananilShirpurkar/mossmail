# Verification — UI and first-run overhaul

Verified locally on 2026-10-28. These checks establish tested behavior, not a production-readiness certification.

## Commands executed

- `.venv/bin/ruff check .` — passed.
- `.venv/bin/ruff format --check .` — passed.
- `MOSSMAIL_TEMPORAL_TESTS=1 .venv/bin/pytest -q` — **153 passed**, including all seven opt-in Temporal tests and the local OAuth callback socket test.
- `.venv/bin/pytest -q` was also run during implementation, with Temporal disabled as documented.
- `PLAYWRIGHT_BROWSERS_PATH=/tmp/mossmail-playwright .venv/bin/python scripts/capture_ui.py` — passed; Chromium launched an isolated Streamlit instance, navigated setup/settings/inbox, verified no seeded messages, dismissed setup using Tab/Enter, activated a local resolution using Enter, verified persistence after reload, and checked the collapsed sidebar at a narrow viewport.
- `git diff --check` — passed.

The existing Playwright development dependency was used. Chromium was downloaded into `/tmp/mossmail-playwright`; no application dependencies were added. The initial sandboxed suite could not bind the OAuth callback socket; successful complete runs used permission to bind loopback. The dedicated browser tool exposed no browsers, so the repository's Playwright tooling supplied rendered verification.

## Coverage and safety review

Regression coverage includes empty installations, persistent dismissal via skip/close, reopening and finishing optional setup, missing OAuth configuration, persistence across app reload, failed and partial synchronization, successful empty synchronization, deterministic excerpts without inference success, overdue local deferrals, untrusted header escaping, strict granted-scope validation, missing OAuth tokens, sanitized failure guidance, failed keyring removal, consent-gated file storage, transactional import/escalation rollback, and a hosted landing page that cannot access private state.

Existing policy, parser, credential, summarizer, synchronization, storage, scoring and Temporal regression coverage remains in the complete suite. Import and escalation counts advance only after database commit. Existing messages and history are never automatically removed. Previously seeded sample messages in older databases are intentionally retained as existing data.

## Screenshots

The [current screenshots](screenshots/current/README.md) were captured from the actual local Streamlit application. Populated inbox screenshots use conspicuously labeled **UI TEST FIXTURE** messages in a temporary database. The capture process disables OS keyring access, strips provider environment credentials, and points file credentials at a temporary path. No personal inbox or credential values were captured.

Screens reviewed: welcome, unconfigured empty inbox, settings with local provider, Gemini settings, populated fixture inbox, and narrow fixture inbox. Reduced-motion settings and explicit sidebar-position checks avoid screenshots taken during responsive transitions.

## Still requires manual verification

- Real Gmail consent, token refresh/revocation, testing-account restrictions, and synchronization against a permitted account.
- Real Gemini model availability, API-key validation, quotas, and response behavior for the user's account.
- The default `gemma3:4b` model is not installed in this environment. Set `OLLAMA_MODEL=gemma2:2b` to use the installed model verified below, or install the default model yourself.
- The target desktop's actual OS keyring backend, including locked-vault behavior.
- Broader screen-reader, mobile, and cross-browser testing beyond Chromium navigation, keyboard setup dismissal/local resolution, and the tested narrow layout.

Google requests in automated tests use mocks. Temporal integration tests run the real SDK test server; they do not validate a deployed Temporal cluster. No live Gmail, Gemini or hosted TabPFN integration was exercised for this overhaul. The local Ollama check below used a real installed model.

## Follow-up live local checks

A secret-safe credential-status check found no configured Gmail OAuth client, refresh token, or Gemini API key, and no usable OS keyring in this session. No secrets were printed, created, or changed; no consent to unencrypted storage was inferred.

A read-only loopback request to Ollama `/api/tags` succeeded. Installed models were `gemma2:2b` and `qwen2.5:3b`; the configured default `gemma3:4b` was absent. Calling `LocalSummarizer(model="gemma2:2b", timeout=45).summarize(...)` with isolated synthetic text succeeded with `source="local_ai"`. The deterministic decision was identical before and after inference. No mailbox content was read, no messages were persisted, no model was downloaded, and no application settings were changed by this check.

The isolated Chromium capture script was rerun successfully with keyboard checks: Tab from **Set up now** focused **Skip for now**, Enter dismissed setup, and Enter on **Mark resolved** persisted the local decision across reload. The six screenshots were refreshed. Lint, format checking, and `git diff --check` passed again. Application code did not change during this follow-up; the previously completed full suite remains **153 passed**, including real Temporal tests.

## Current-demo presentation update — 2026-10-28

- `.venv/bin/pytest -q` — **146 passed, 7 skipped**. The separate Temporal tests remain opt-in; no workflow code changed in this update.
- `.venv/bin/ruff check --no-cache .`, `.venv/bin/ruff format --check --no-cache .`, and `git diff --check` — passed. Local documentation/media links were also checked.
- Recorded a continuous **59.6-second**, **1440 × 1000** walkthrough of the actual app with a labeled fictional test inbox. The capture verified empty start, policy-approved local parking, persisted resolution, reload behavior, and no browser errors. It created no credential file and removed the temporary workspace afterward.
- Encoded that raw WebM as a **1.71 MB H.264 MP4** for README access and hosted playback. Visually reviewed representative frames from the recording.
- Launched `streamlit_app.py` separately in system Chrome, loaded the local MP4, verified its duration, actual playback and seeking, and reviewed the rendered page. No inbox database or credential file was created. The existing hosted-boundary regression test still prevents database/keyring construction and now checks the recorded-video element and fictional-data label.
- Used existing system Chrome, FFmpeg, and existing browser automation tooling. No dependency, browser, or model was installed for this update. No live Gmail, AI provider, Temporal service, or public deployment was tested.
