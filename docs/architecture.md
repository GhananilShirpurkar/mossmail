# Architecture and safety boundaries

MossMail is a single-user local prototype. Its two execution paths are deliberately explicit: a fully usable Streamlit simulation and a real Temporal worker exercised through the CLI and integration tests.

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | Validated message, score, decision, override, and summary schemas |
| `policy.py` | Protected senders, configurable time limits, normalized risk detection |
| `scoring.py` | Transparent baseline and opt-in hosted TabPFN adapter |
| `decision_engine.py` | Pure policy decision with explanations and review deadlines |
| `email_parser.py` | MIME/charset extraction, latest-reply preparation, original preservation |
| `summarizer.py` | Local-only HTTP inference, schema validation, truthful fallback |
| `credentials.py` | OS Keyring storage, explicit unencrypted fallback consent, secret lifecycle |
| `mailbox/` | Read-only mailbox provider abstraction, loopback OAuth PKCE, inbox sync |
| `storage.py` | SQLite state and atomic idempotent event ledger |
| `workflows.py` | Deterministic Temporal state machine, timer, signals, retry policy |
| `activities.py` | Local state side effects, policy rejection, no mailbox operations |
| `temporal_cli.py` | Worker and workflow lifecycle commands |
| `hosted_cli.py` | Explicit numeric-feature experiment, separate from dashboard |

## Decision precedence

1. A user choice for the current message revision wins, except a deferral that violates protection or incomplete-content guards. Explicit resolution is allowed and remains available in the resolved filter.
2. A follow-up or risk signal increments the revision, clears the old override, and escalates. A person can resolve that new revision afterward.
3. Protected senders or urgent, financial, legal, security, and deadline evidence keep mail visible, even if a model score is low.
4. Only curated bulk messages with readable, complete text and both low risk and low uncertainty can be automatically recommended for deferral.
5. Everything else goes to review. Lack of a reply is never evidence of unimportance.

Scores and explanations describe the initial recommendation; persisted events describe the current state. The UI shows both when timer expiry changes that state. A `Safe to defer` recommendation is distinct from `parked=true`, which means a local simulated or Temporal activity has actually recorded a waiting period.

## Waiting state machine

```mermaid
stateDiagram-v2
    [*] --> Starting
    Starting --> Parked: policy-approved activity
    Parked --> ReEvaluating: timer expires
    Parked --> Escalated: follow-up or risk signal
    Parked --> Resolved: user resolves current revision
    Parked --> NeedsReview: user requests review
    ReEvaluating --> NeedsReview: safe review-on-expiry policy
    ReEvaluating --> Resolved: preserve a newer user resolution
    Escalated --> [*]
    Resolved --> [*]
    NeedsReview --> [*]
```

`BEGIN IMMEDIATE` serializes local transitions. A unique event key makes a retried write return the prior result. Each parking cycle has a generation number; stale workflow actions cannot mutate a newer cycle. This gives idempotent **local database effects**, not exactly-once email delivery or archival. Activities retry at most five times with 15-second execution and three-minute total limits. Policy rejections are non-retryable. A version counter catches signals delivered during a terminal activity; newer signals receive their own idempotency key before the workflow completes.

Temporal receives opaque IDs and transition commands. The activity resolves content locally and re-evaluates current policy when the timer expires. The dashboard never pretends to have scheduled a Temporal workflow. A signal after a workflow has completed requires application-level reconciliation; no live mailbox listener exists in this version.

## Mailbox integration and OAuth 2.0 security

MossMail supports read-only mailbox synchronization via the `MailboxProvider` abstraction (`mossmail/mailbox/base.py`) and a Google Gmail implementation (`mossmail/mailbox/gmail.py`).

1. **Strict Read-Only Enforcement:**
   - Scope is restricted to `https://www.googleapis.com/auth/gmail.readonly`. The authorization URL generator and token exchange validator strictly reject broader scopes (such as `mail.google.com` or `gmail.modify`).
   - `GmailProvider` contains zero methods for sending, drafting, deleting, trashing, archiving, or modifying emails or labels.
2. **RFC 8252 Loopback Native App Flow with RFC 7636 PKCE:**
   - Follows Google's native application guidance. Deprecated out-of-band (OOB) copy-paste redirection is completely removed.
   - Binds an embedded HTTP server strictly to `127.0.0.1:{port}` with dynamic ephemeral port fallback.
   - Generates a high-entropy cryptographic `code_verifier` and `code_challenge` (S256), paired with an unguessable 256-bit random `state` parameter to prevent authorization code interception and CSRF.
   - Automatically filters out secondary browser probes (`/favicon.ico`) with HTTP 204 to prevent premature listener termination.
   - Client secrets in installed native desktop applications are non-confidential under RFC 8252; security is guaranteed by PKCE code verification on Google's token endpoint.
3. **Token Lifecycle & Keyring Storage:**
   - OAuth refresh tokens are stored in the user's OS credential vault via `CredentialStore`. Storing to unencrypted local files requires explicit user confirmation.
   - Expired access tokens refresh automatically before API calls. Revoked tokens (`invalid_grant`) raise `TokenRevokedError` prompting re-authentication.
   - Disconnecting attempts best-effort remote revocation via Google's revocation endpoint and unconditionally deletes all local tokens from the credential vault.
4. **Restricted Scope & Verification Disclosures:**
   - Google designates `gmail.readonly` as a Restricted Scope. Multi-tenant public commercial apps require Cloud App Security Assessment (CASA) Tier 2 and Google verification.
   - MossMail operates as an open-source, local-first personal tool where users bring their own private Google Cloud project Desktop Client ID ("Bring Your Own Key/Client"), exempt from third-party app verification for authorized test accounts.
5. **Idempotent Sync & Thread Escalation:**
   - `sync_inbox` deduplicates messages by provider ID against the SQLite store, preventing duplicate processing.
   - When a new message arrives for a thread that is currently in a parked/deferred state, the existing parked message is reactivated (`followup` event in the ledger) and returned to review, preserving inbox safety.

## Untrusted data and privacy

Mail is data, not instructions. The parser excludes attachments and nested forwarded messages from the current body, prefers plain text, and flags uncertain HTML/charset/quote cases. It retains original bytes and full extracted text. The latest short reply is not replaced by a longer old forward merely to meet a minimum length. Ambiguous parsing returns to human review.

Ollama must use a loopback HTTP origin. Redirects and environment proxies are disabled. Prompt instructions and JSON validation reduce malformed output, but do not prove factual accuracy or defeat every injection. The policy never consumes the summary, and the inference module has no action tools. Model text is rendered as plain text.

The local database contains synthetic email bodies and metadata. It is excluded from Git and is not encrypted. Event entries contain message IDs, modes, timestamps, actions, and state, not bodies or addresses. Logging uses a fixed inference-failure code. The optional hosted feature path cannot run without consent; its probabilities are treated as uncalibrated and cannot authorize parking on their own.

## Evaluation boundary

The tests validate software behavior and safety invariants on synthetic cases. They are not an estimate of real-mail classification accuracy. There is no training dataset, accuracy figure, or measured time saving in this release. A future evaluation must use permissioned risk labels, completed observation windows, chronological splits, and sender/thread leakage controls, and must report false suppression of high-risk mail separately.
