*This is a submission for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19). Built with Codex assistance. #devchallenge #hf26challenge*

## What I Built

An inbox tells us that something arrived. It rarely helps us decide whether that message deserves our attention right now.

I built **MossMail**, a local-first email triage prototype for people whose inbox keeps pulling them away from their work. Its promise is simple: **a calmer inbox, less attention, better decisions.**

MossMail makes waiting an explicit, reversible choice. Protected senders stay visible. Financial, legal, security, urgent, and deadline-sensitive messages go to review. Uncertain content and attachments also need a person. A low-risk subscription can be parked with a visible review deadline, and a follow-up brings its thread back.

Select a message to see its short summary or excerpt, suggested next step, and the actual rules behind its recommendation. You can keep it in review or mark it resolved. The product helps you decide where to look; it does not quietly delete mail.

The current release uses entirely fictional messages. It demonstrates the decision workflow without connecting to a live mailbox or sending, deleting, or archiving anything.

## Demo

**[Try MossMail live →](https://mossmail.streamlit.app/)**

No mailbox connection or model download is needed. Each visitor gets an isolated demo session. Try this small walkthrough:

1. Open the invoice and read the financial and deadline reasons keeping it visible.
2. Open **Parked**, then choose **Simulate follow-up** on a subscription.
3. Open **Activity** to inspect the escalation, or try **Preview timer expiry** to return a message for review.

![The live MossMail demo on Streamlit Community Cloud](https://raw.githubusercontent.com/GhananilShirpurkar/mossmail/main/docs/screenshots/05-hosted-demo.png)

The hosted app uses clearly labeled deterministic excerpts and simulated waiting controls. It does not run Gemma or a Temporal server in Community Cloud.

**[Watch the 107-second local Gemma demo](https://github.com/GhananilShirpurkar/mossmail/blob/main/docs/mossmail-demo.webm)** to see actual local AI summaries. This genuine, silent browser recording uses the same fictional collection and explicitly labels its workflow simulation.

The separate durable Temporal implementation is exercised by real SDK integration tests and can be run using the server and worker commands in the README.

## Code

**[MossMail on GitHub](https://github.com/GhananilShirpurkar/mossmail)** · [MIT license](https://github.com/GhananilShirpurkar/mossmail/blob/main/LICENSE) · [Validation](https://github.com/GhananilShirpurkar/mossmail/blob/main/docs/validation.md)

The repository includes the application, synthetic examples, tests, genuine captures, local setup instructions, and the Community Cloud entrypoint. Its policy and inference code are separate from the Streamlit interface, so the important behavior can be tested directly.

## How I Built It

I used Python, Streamlit, Pydantic, SQLite, Ollama, and the Temporal Python SDK. Codex assisted with implementation, tests, documentation, and browser verification.

The inspiration was Khushighosh's [Let It Die repository](https://github.com/Khushighosh/let-it-die) and its [DEV article](https://dev.to/khushighosh/let-it-die-the-lazy-email-agent-on-tabpfn-gemma-and-temporal-10o0). I inspected the MIT-licensed repository before building. Local summaries and deferred-message workflows were the conceptual starting point.

MossMail independently implements a risk-first policy, review interface, structured summary boundary, MIME preparation, and transactional event ledger. No upstream source, dataset, predictions, caches, credentials, or Git history was copied. It also avoids treating a predicted lack of reply as proof that an email is unimportant.

**Gemma helps with reading.** The default model is configurable `gemma3:4b`; the actual local demonstration used the installed `gemma2:2b` through Ollama. Responses must match a JSON schema. Missing models, connection failures, uncertain parsing, and invalid output produce an honestly labeled excerpt. Email text is untrusted data, and the summarizer has no mailbox tools or policy authority.

**Temporal makes waiting durable.** A workflow records parking through an activity, waits for a timer or signal, and applies a safe local transition. Expiry returns a message for review. Activity retries are deduplicated, stale parking cycles cannot overwrite newer ones, and signals arriving during an in-flight expiry activity are processed before completion. Integration tests cover timers, signals, retry after commit, worker replacement, replay, and that signal race.

**The cloud demo stays lightweight.** A separate entrypoint isolates each visitor's synthetic state in a temporary database and bypasses Ollama. The local application retains its Gemma integration and persistent local state.

An optional hosted TabPFN adapter is implemented with explicit consent and numeric-only features. Hosted inference was not run for this submission, and no model-quality metric or TabPFN prize claim is made.

## Why Does Open Innovation Matter?

Running Gemma locally lets the reading assistance work without sending message text to a hosted language-model provider. The model can be swapped through configuration, while the application remains usable if inference fails. Model weights are not bundled, and Gemma's own terms apply.

Temporal's open-source workflow tools make the waiting behavior inspectable and testable. I can reproduce a failure after a committed write, restart a worker, replay history, and check whether a follow-up still reaches the review queue.

The policy is readable Python. Someone can change protected senders, shorten the waiting period, or improve MIME handling while keeping those decisions visible. The useful open contribution is that whole boundary: code, examples, explanations, tests, and limitations.

## My Agent Session

This project was built with Codex assistance. The implementation, validation notes, and commit history document the work. A public agent-session transcript is not included.

## The Lazy Payoff

The intended payoff is fewer repeated decisions about low-risk messages: give them a deadline, let them wait, and return when there is new context or a reason to review.

The demo shows that behavior. Real-world time saved, changes in inbox-checking habits, and risk-detection accuracy have not been measured; those remain future evaluation work.

## Prize Categories

- **Best Use of Gemma** — actual local `gemma2:2b` inference through Ollama, demonstrated in the recorded application with model and source labels.
- **Best Use of Temporal** — a durable workflow with activities, timers, signals, bounded retries, idempotent local effects, worker-recovery tests, and history replay.

The live Streamlit demo is a convenient way to explore the product. The local recording and integration tests provide the evidence for these two partner integrations. No other partner category is claimed.
