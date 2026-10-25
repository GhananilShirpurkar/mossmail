---
title: "MossMail: a calmer inbox that knows when to wait"
published: false
tags: devchallenge, hf26challenge, ai, opensource
---

*A submission draft for the [Hacktoberfest Open-Source AI Challenge Week 3: Slow and Steady](https://dev.to/challenges/hacktoberfest-week3-2026-10-19). Built with Codex assistance; source and validation are public. #devchallenge #hf26challenge*

## What I Built

An inbox is good at telling us that something arrived. It is much less helpful at telling us whether that thing deserves our attention now.

**MossMail** is a local-first email triage prototype with a simple promise: **a calmer inbox, less attention, better decisions.** It is for people who switch between meaningful work and a growing pile of messages, and want help deciding where to look first.

Open MossMail and you see a small, considered inbox: messages that need review, threads brought back by a follow-up, and subscriptions parked with a visible review deadline. Select a message to read a short local AI summary, a suggested next step, and the actual policy evidence behind its position.

The product favors safe inaction. A protected sender stays visible. An invoice, security notice, legal request, or deadline stays visible. An attachment or ambiguous message goes to a person. A low-risk subscription can wait. When its timer expires, it comes back for review; when a follow-up arrives, it escalates. The user can keep a message in review or mark it resolved.

This release is a working synthetic-data demo. It does not connect to a live mailbox, send messages, or delete or archive anything. That makes the behavior inspectable before trusting it with real correspondence.

## Demo

[Watch the genuine browser recording](https://github.com/GhananilShirpurkar/mossmail/blob/main/docs/mossmail-demo.webm).

The recording navigates the running Streamlit application, reads a locally generated Gemma summary, opens a protected financial message, and exercises follow-up escalation and timer expiry in the explicitly labeled dashboard simulation. It is a silent recording of real browser interactions, with entirely fictional messages. There is no deployed mailbox service.

![MossMail's real inbox dashboard](https://raw.githubusercontent.com/GhananilShirpurkar/mossmail/main/docs/screenshots/01-inbox.png)

![Visible review and escalation history](https://raw.githubusercontent.com/GhananilShirpurkar/mossmail/main/docs/screenshots/04-history.png)

The durable Temporal implementation is separate from those UI simulation controls and is validated with a real SDK test server. The repository includes exact commands to run the server, worker, timer, and signals yourself.

## Code

[MossMail on GitHub](https://github.com/GhananilShirpurkar/mossmail) · [MIT license](https://github.com/GhananilShirpurkar/mossmail/blob/main/LICENSE) · [Validation evidence](https://github.com/GhananilShirpurkar/mossmail/blob/main/docs/validation.md)

The project has its own source tree and Git history. The README includes setup instructions, architecture, privacy boundaries, screenshots, and a reproducible capture script.

## How I Built It

I used Python, Streamlit, Pydantic, SQLite, Ollama, and the Temporal Python SDK. Codex assisted with implementation, tests, documentation, and browser verification.

The inspiration was Khushighosh's [Let It Die](https://github.com/Khushighosh/let-it-die) and its [DEV article](https://dev.to/khushighosh/let-it-die-the-lazy-email-agent-on-tabpfn-gemma-and-temporal-10o0). I inspected the MIT-licensed repository before building. Its combination of local summaries and deferred-message workflows was a useful starting idea.

MossMail independently implements a different decision policy and product experience. It does not use a predicted lack of reply as proof that a message is unimportant. It adds explicit protection rules, uncertainty handling, a review-first dashboard, structured summaries, recursive MIME preparation, and a transactional event ledger. No upstream code, dataset, predictions, caches, or history was copied.

Gemma supplies the reading assistance. The configured default is `gemma3:4b`; the actual demonstration used the installed `gemma2:2b` through local Ollama. Each response must match a two-field schema. If the service is unavailable, the model is missing, parsing is uncertain, or the response is invalid, the UI honestly labels a deterministic excerpt. The language model offers advice and has no authority to change policy or execute actions.

Temporal supplies the durable waiting mechanism. A workflow records parking through an activity, waits for a signal or timer, then performs a safe local transition. Retried activities return the same ledger result instead of duplicating a write. Tests exercise expiry, follow-ups, new risk, user resolution, failure after commit, worker restart, and replay.

A transparent local scorer makes the app useful immediately. There is also an optional hosted TabPFN adapter with explicit consent and numeric-only features. Hosted inference was not run for this submission; no predictive metrics or TabPFN prize claim are made.

## Why Does Open Innovation Matter?

The local model is what lets the reading experience run without sending message text to a hosted language-model provider. The model can be changed through configuration, and failure does not make the product unusable. Gemma's weights are not bundled; its own terms apply.

Temporal's open-source workflow tools make waiting something I can inspect and test, including the difficult case where a write succeeds but its activity response fails. The policy is ordinary readable Python, so someone can change who is protected or how long a message may wait without relying on a hidden service policy.

The open contribution here is the whole decision boundary: code, examples, reasons, tests, and limitations. Other builders can improve the MIME handling, evaluate risk on permissioned data, or add read-only integrations while keeping the safety rules visible.

## My Agent Session

This project was built with Codex assistance. The implementation and validation steps are documented in the repository. No public agent-session transcript is attached; sharing one is optional, and I have not uploaded this conversation or private environment details.

## The Lazy Payoff

The intended payoff is fewer repeated decisions about low-risk mail: park it with a deadline, then look again when there is a reason. The demo shows that behavior, but it is not a user study. I have not measured real-world minutes saved, reduction in inbox checking, or risk-detection accuracy. Those measurements remain future work.

## Prize Categories

- **Best Use of Gemma** — actual local `gemma2:2b` inference in the running application; the recorded UI identifies the model and distinguishes it from fallback excerpts.
- **Best Use of Temporal** — an implemented durable workflow with activities, timers, signals, retries, and real SDK integration tests for worker recovery and replay. The UI recording clearly labels its separate simulation.

No other partner category is claimed.
