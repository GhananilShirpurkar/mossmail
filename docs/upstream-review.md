# Upstream review and provenance

Reviewed with GitHub CLI on 25 October 2026:

- Repository: [Khushighosh/let-it-die](https://github.com/Khushighosh/let-it-die)
- Commit: `ed4415ba00deea76d366f8d22c6ddadcab6c8437`
- License: MIT, copyright 2026 Khushighosh. Reuse is permitted subject to its notice requirements.
- Read: README, LICENSE, `agent.py`, `activities.py`, `workflows.py`, `textclean.py`, `build.py`, and `compare.py`. No dedicated test suite was present in the inspected tree.
- The source was cloned into a temporary reference directory. None of its files or history was imported into this project.
- The linked DEV article could not be fetched (the public endpoint returned `403 Forbidden Bots`; the connected DevRelay tools required an MLH login). This review does not claim access to unseen article text or comments.

## Ideas retained

Local Gemma summarization avoids sending email text to a hosted language model. Temporal's durable wait-and-signal pattern suits deferred attention. Comparing a simple baseline against an optional tabular model is more honest than assuming a foundation model is always needed.

## Changes made independently

The upstream pipeline uses reply-within-seven-days as a target and score quantiles as buckets. Its own README describes that label as a proxy and documents missed replied-to messages. MossMail does not equate non-response with low importance: explicit risk and uncertainty rules take precedence, and unknown mail stays visible.

The upstream timer's archive activity appends a log entry. MossMail has no archive activity at all. Expiry re-evaluates and returns a message for review. SQLite enforces atomic idempotency and parking-cycle checks; UI labels distinguish simulation from actual durable workflow activity.

The upstream forwarding cleanup uses a short-reply length fallback. MossMail preserves short latest replies, recursively parses MIME, excludes attached old messages, handles charsets, and flags ambiguous content for review. It provides both original bytes and extracted text instead of silently treating a guessed parse as reliable.

The upstream Sentry configuration can record full prompts, outputs, and default PII when tracing is configured. MossMail initializes no such telemetry. Its local inference error log contains only a fixed event code. Email body text never enters workflow history.

The upstream feature pipeline includes sender histories and uses a chronological train/test split with an observation-window cutoff. Those are useful evaluation considerations, but its results are not transferable to MossMail. No upstream data or metrics were reused. Our optional hosted adapter exposes a small numeric schema and requires explicit consent; a real human-risk dataset and evaluation remain future work.

## Licensing decision

MIT was selected for independently written MossMail code, synthetic examples, styling, and real UI captures. No substantial upstream code was copied, so no upstream source files are redistributed. Inspiration is credited in the README and submission. Dependency licenses and Gemma's model terms apply separately; no model weights are included.

## Technical references consulted

- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs): JSON schema passed to `format`, then validated locally.
- [Temporal Python testing](https://docs.temporal.io/develop/python/best-practices/testing-suite): real time-skipping server, workers, activities, and integration tests.
- [Prior Labs client](https://github.com/PriorLabs/tabpfn-client): hosted-data boundary and classifier API; release 0.6.1 source inspected for `fit`, `predict_proba`, and class ordering.

DevRelay community searches were attempted but unavailable without a connected MLH account. No community consensus or discussion findings are invented.
