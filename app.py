import html
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from mossmail.credentials import (
    SUPPORTED_GEMINI_MODELS,
    CredentialRemovalError,
    CredentialStore,
    InsecureStorageError,
    validate_gemini_key,
)
from mossmail.decision_engine import decide
from mossmail.mailbox import GmailProvider, OAuthError, sync_inbox
from mossmail.models import Message, Override, State
from mossmail.storage import Store
from mossmail.summarizer import fallback, get_summarizer

ROOT = Path(__file__).parent
st.set_page_config(page_title="MossMail", layout="wide")
st.html((ROOT / "mossmail/style.html").read_text())
if globals().get("HOSTED_PREVIEW", False):
    st.title("MossMail")
    st.write("Read-only Gmail triage with transparent rules and local decisions.")
    st.video(str(ROOT / "docs/mossmail-demo-current.mp4"))
    st.caption(
        "60-second local UI recording · Labeled fictional test inbox · No Gmail connection, AI inference, or Temporal service."
    )
    st.info(
        "Run MossMail on your own machine to connect Gmail and store private messages. This page is a recorded walkthrough, not an interactive mailbox."
    )
    st.code(
        "git clone https://github.com/GhananilShirpurkar/mossmail.git\n"
        "cd mossmail\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "python -m pip install -r requirements.txt\n"
        "streamlit run app.py --server.address 127.0.0.1",
        language="bash",
    )
    st.markdown(
        "[Setup and security boundaries](https://github.com/GhananilShirpurkar/mossmail#readme)"
    )
    st.caption(
        "Gmail requires your own Desktop OAuth client. AI summaries and background timers are optional. This page does not access credentials, create an inbox, or make provider requests."
    )
    st.stop()
store = Store(Path(os.getenv("MOSSMAIL_DB", str(ROOT / ".local/mossmail.sqlite3"))))
cred_store = CredentialStore()
gmail_provider = GmailProvider(credential_store=cred_store)


def safe(value):
    return html.escape(str(value))


def badge(text, kind="green"):
    return f'<span class="badge {kind}">{safe(text)}</span>'


def close_setup():
    store.set_setting("onboarding_dismissed", "yes")
    st.session_state["setup_open"] = False
    st.rerun()


def run_sync():
    with st.spinner("Synchronizing recent Gmail messages…"):
        try:
            report = sync_inbox(gmail_provider, store, limit=20)
            if report.errors:
                level = "warning" if report.new_count or report.existing_count else "error"
                text = (
                    f"Synchronization incomplete. Saved {report.new_count} new messages. "
                    + " ".join(report.errors)
                )
            else:
                level = "success"
                text = (
                    f"Synchronized: {report.new_count} new, {report.existing_count} already stored."
                )
                store.set_setting("last_sync", datetime.now(UTC).isoformat())
            store.set_setting("sync_error", text if report.errors else "")
        except Exception:
            level, text = (
                "error",
                "Synchronization failed. Check your connection and retry. Local messages are preserved.",
            )
            store.set_setting("sync_error", text)
    st.session_state["notice"] = (level, text)
    st.rerun()


def show_history(events):
    labels = {
        "park": "Parked",
        "resolve": "Marked resolved",
        "review": "Returned to review",
        "followup": "Follow-up received",
        "risk": "Risk changed",
        "expire": "Review deadline reached",
    }
    if not events:
        st.info("No local decisions recorded yet.")
    for event in events:
        st.html(
            f'<div class="event"><strong>{safe(labels[event["kind"]])}</strong><span>{safe(event["created_at"])} · {safe(event["message_id"])} · {safe(event["mode"])}</span></div>'
        )


with st.sidebar:
    st.html('<div class="brand">mossmail</div><p class="micro">Local email triage</p>')
    view = st.radio(
        "Workspace",
        ["Inbox", "Parked", "Activity", "Settings"],
        key="workspace",
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(
        "Gmail · credentials saved" if gmail_provider.is_connected() else "Gmail · not connected"
    )
    st.caption("Connection is checked during synchronization.")
    if gmail_provider.is_connected():
        if st.button("Sync inbox", type="primary", use_container_width=True):
            run_sync()
    st.caption("Read-only access. All decisions stay local.")
    st.caption(
        "Gemini · key configured"
        if cred_store.get_secret("gemini_api_key")
        else "Gemini · optional key not configured"
    )
    st.caption("AI runs only when you request a summary.")
    if store.setting("last_sync"):
        st.caption("Last complete sync: " + store.setting("last_sync"))
    if st.button("Open setup", use_container_width=True):
        st.session_state["setup_open"] = True
        st.rerun()

if "notice" in st.session_state:
    level, text = st.session_state.pop("notice")
    getattr(st, level)(text)
setup_active = (
    st.session_state.get("setup_open", False) or store.setting("onboarding_dismissed") != "yes"
)
if setup_active:
    st.title("Welcome to MossMail")
    st.write(
        "A local-first email triage assistant that helps organize your attention. Review recommendations and keep consequential decisions under your control."
    )
    st.caption(
        "Gmail is optional to explore; connect it to import real messages. AI is optional: policy checks and original-message excerpts work without it."
    )
    gmail_step, ai_step = st.columns(2)
    with gmail_step:
        st.subheader("1. Connect your inbox")
        st.write(
            "Use your own Google Desktop OAuth credentials to grant read-only Gmail access. Synchronization is manual; your mailbox is never changed."
        )
    with ai_step:
        st.subheader("2. Choose summaries, optionally")
        st.write(
            "Add a Gemini API key for cloud summaries, or use Ollama locally. You can read messages and use policy checks without either."
        )
    a, b, c = st.columns(3)
    if a.button("Set up now", type="primary"):
        st.session_state["setup_configure"] = True
    if b.button("Skip for now"):
        close_setup()
    if c.button("Close setup"):
        close_setup()
    if not st.session_state.get("setup_configure"):
        st.stop()
    st.caption("Skip either integration by leaving it unconfigured, then choose Finish setup.")
else:
    st.title(view)
    st.caption(
        {
            "Inbox": "Stored messages and the decisions that need your attention.",
            "Parked": "Deferred locally. Deadlines are checked while the app is open; use Temporal for background timers.",
            "Activity": "Persisted local decisions. No Gmail messages are modified.",
            "Settings": "Configure integrations or reopen setup at any time.",
        }[view]
    )

if view == "Settings" and not setup_active:
    if st.button("Reopen setup"):
        st.session_state["setup_open"] = True
        st.session_state["setup_configure"] = False
        st.rerun()

if view == "Settings" or setup_active:
    st.subheader("Integrations")
    st.caption(
        "Credentials are stored locally. Gemini sends selected message text to Google only when you request a summary."
    )
    cred_store = CredentialStore()
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.html('<div class="eyebrow">INFERENCE PROVIDER</div>')
        has_key = cred_store.get_secret("gemini_api_key") is not None
        provider_choice = st.radio(
            "Select Provider",
            ["Google Gemini API (BYOK)", "Local Ollama (100% Offline)"],
            index=0
            if store.setting("ai_provider", "gemini" if has_key else "local") == "gemini"
            else 1,
            label_visibility="collapsed",
        )
        store.set_setting(
            "ai_provider", "local" if provider_choice.startswith("Local") else "gemini"
        )
        if provider_choice == "Local Ollama (100% Offline)":
            st.info(
                "Local Ollama inference connects strictly to loopback HTTP (127.0.0.1:11434). "
                "No email data is ever sent to external cloud servers."
            )
            st.caption(f"Default local model: {os.getenv('OLLAMA_MODEL', 'gemma3:4b')}")
        else:
            st.markdown("### Google Gemini Configuration")
            key_status = cred_store.get_storage_type("gemini_api_key")
            current_model = cred_store.get_secret("gemini_model") or SUPPORTED_GEMINI_MODELS[0]

            if has_key:
                if key_status == "env":
                    st.info(
                        "Gemini API key is detected from your environment variable (GEMINI_API_KEY). "
                        "To remove or change it, unset or modify GEMINI_API_KEY in your shell or .env file."
                    )
                else:
                    storage_desc = (
                        "Secure OS Keyring"
                        if key_status == "keyring"
                        else "Local file (.local/credentials.json, mode 0600)"
                    )
                    st.success(
                        f"Gemini API key is configured ({storage_desc}). Value is protected and never displayed."
                    )
                model_idx = (
                    SUPPORTED_GEMINI_MODELS.index(current_model)
                    if current_model in SUPPORTED_GEMINI_MODELS
                    else 0
                )
                chosen_model = st.selectbox(
                    "Active Gemini Model", SUPPORTED_GEMINI_MODELS, index=model_idx
                )
                model_consent = (
                    st.checkbox(
                        "Allow unencrypted storage of this model preference", key="model_consent"
                    )
                    if not cred_store.is_keyring_usable()
                    else False
                )
                if chosen_model != current_model:
                    if st.button("Update Model", type="primary"):
                        try:
                            cred_store.set_secret(
                                "gemini_model", chosen_model, allow_unencrypted_file=model_consent
                            )
                            st.rerun()
                        except (InsecureStorageError, OSError):
                            st.error(
                                "Model preference could not be saved. Check credential storage and consent."
                            )

                if key_status in ("keyring", "unencrypted_file"):
                    if st.button("Remove Gemini API Key", type="secondary"):
                        try:
                            cred_store.delete_secret("gemini_api_key")
                            cred_store.delete_secret("gemini_model")
                            st.session_state["notice"] = (
                                "info",
                                "Saved Gemini credentials removed. Environment credentials must be unset separately.",
                            )
                            st.rerun()
                        except (CredentialRemovalError, OSError):
                            st.error(
                                "Credential removal incomplete. Check your keyring and file permissions, then retry."
                            )
            else:
                st.caption(
                    "Bring your own API key from Google AI Studio. The key is stored locally "
                    "and used only when you choose to summarize an email."
                )
                key_input = st.text_input(
                    "Gemini API Key",
                    type="password",
                    placeholder="AIzaSy...",
                    help="Stored securely in your operating system credential vault.",
                )
                chosen_model = st.selectbox("Select Model", SUPPORTED_GEMINI_MODELS, index=0)

                keyring_usable = cred_store.is_keyring_usable()
                consent = False
                if not keyring_usable:
                    st.warning(
                        "No secure OS keyring is available on this system. Saving this key requires writing to an unencrypted "
                        "local file (`.local/credentials.json` with permissions `0600`). Note: filesystem permissions restrict "
                        "access to your user account, but do NOT provide encryption at rest."
                    )
                    consent = st.checkbox(
                        "I understand and authorize storing credentials in an unencrypted file with 0600 permissions",
                        key="consent_unencrypted_file",
                    )

                if st.button("Test & Save Key", type="primary"):
                    if not key_input.strip():
                        st.error("Please enter a valid API key.")
                    else:
                        with st.spinner("Validating API key with Google Gemini API..."):
                            ok, msg = validate_gemini_key(key_input, model=chosen_model)
                        if not ok:
                            st.error(msg)
                        else:
                            try:
                                cred_store.set_secret(
                                    "gemini_api_key",
                                    key_input,
                                    allow_unencrypted_file=consent,
                                )
                                cred_store.set_secret(
                                    "gemini_model",
                                    chosen_model,
                                    allow_unencrypted_file=consent,
                                )
                                st.session_state["notice"] = (
                                    "success",
                                    "Gemini key validated and saved.",
                                )
                                st.rerun()
                            except (InsecureStorageError, OSError):
                                st.error(
                                    "Could not save credentials. Check keyring availability or explicitly consent to unencrypted storage."
                                )

    with right:
        st.subheader("Summary privacy")
        st.write(
            "Summaries are optional. Original excerpts and deterministic policy work without an AI provider."
        )
        with st.expander("What leaves this machine?"):
            st.write(
                "Gemini receives the selected subject (up to 300 characters) and latest reply (up to 6,000 characters), only when you request a summary. Those fields may contain personal information or secrets. Full headers and attachment files are excluded."
            )
            st.write(
                "Ollama connects only to loopback HTTP. Review the original and provider terms before requesting cloud summaries."
            )

    st.divider()
    st.subheader("Gmail Integration (Read-Only)")
    st.caption(
        "Connect your real Gmail inbox for local email triage. "
        "MossMail requests strictly read-only access."
    )
    g_left, g_right = st.columns([1.4, 1], gap="large")
    with g_left:
        with st.container(border=True):
            if gmail_provider.is_connected():
                st.info("Gmail credentials saved · read-only. Synchronize to check access.")
                st.caption(
                    "MossMail has permission only to read inbox messages. "
                    "It cannot send, modify, delete, or archive any email."
                )
                sync_col1, sync_col2 = st.columns(2)
                with sync_col1:
                    if st.button("Sync Inbox Now", type="primary", key="sync_btn_settings"):
                        run_sync()
                with sync_col2:
                    if st.button("Disconnect Gmail", type="secondary", key="disconnect_gmail"):
                        try:
                            gmail_provider.disconnect()
                            st.session_state["notice"] = (
                                "info",
                                "Local Gmail credentials removed. Remote revocation is best effort. Environment credentials must be unset separately.",
                            )
                            st.rerun()
                        except (CredentialRemovalError, OSError):
                            st.error(
                                "Disconnect incomplete. Check your keyring and file permissions, then retry. Local messages are preserved."
                            )
            else:
                st.caption(
                    "Bring your own Google OAuth Client ID (type: 'Desktop app'). "
                    "Secure OS keyring is preferred; unencrypted storage requires consent."
                )
                client_id_val = st.text_input(
                    "Google OAuth Client ID",
                    value=cred_store.get_secret("gmail_client_id") or "",
                    placeholder="xxxxxxxxxxxx-xxxxxxxxxxxxxxxx.apps.googleusercontent.com",
                    help="Obtain this from Google Cloud Console under Credentials > OAuth 2.0 Client IDs.",
                    key="input_gmail_client_id",
                )
                client_secret_val = st.text_input(
                    "Google OAuth Client Secret (Optional for Desktop PKCE)",
                    value="",
                    type="password",
                    placeholder="GOCSPX-...",
                    help="Client secret for your Desktop app OAuth client.",
                    key="input_gmail_client_secret",
                )

                keyring_usable = cred_store.is_keyring_usable()
                gmail_consent = False
                if not keyring_usable:
                    st.warning(
                        "Secure OS keyring unavailable. Storing OAuth tokens requires writing to "
                        "`.local/credentials.json` (mode 0600, unencrypted at rest)."
                    )
                    gmail_consent = st.checkbox(
                        "Authorize storing Gmail OAuth tokens in unencrypted local file (mode 0600)",
                        key="gmail_consent_unencrypted",
                    )

                if st.button("Save OAuth configuration"):
                    if not client_id_val.strip():
                        st.error("Enter a Desktop OAuth client ID first.")
                    else:
                        try:
                            cred_store.set_secret(
                                "gmail_client_id",
                                client_id_val,
                                allow_unencrypted_file=gmail_consent,
                            )
                            if client_secret_val.strip():
                                cred_store.set_secret(
                                    "gmail_client_secret",
                                    client_secret_val,
                                    allow_unencrypted_file=gmail_consent,
                                )
                            st.success("OAuth configuration saved. Connect Gmail when ready.")
                        except (InsecureStorageError, OSError):
                            st.error(
                                "Could not save OAuth configuration. Check credential storage and consent."
                            )
                st.caption(
                    "OAuth configured · ready to connect"
                    if cred_store.get_secret("gmail_client_id")
                    else "OAuth not configured · Desktop client required before connecting"
                )

                if st.button("Connect Gmail Account", type="primary", key="connect_gmail_btn"):
                    if not client_id_val.strip():
                        st.error("Please enter a valid Google OAuth Client ID.")
                    elif not keyring_usable and not gmail_consent:
                        st.error(
                            "Explicit user consent is required before saving credentials "
                            "without a secure keyring."
                        )
                    else:
                        try:
                            gmail_provider.client_id = client_id_val.strip()
                            gmail_provider.client_secret = (
                                client_secret_val.strip() or gmail_provider.client_secret
                            )
                            auth_info = gmail_provider.start_auth_flow()
                            auth_url, verifier, state, redirect_uri = auth_info
                            with st.spinner(
                                f"Waiting for authorization on {redirect_uri}... "
                                "Your browser has opened Google's consent screen."
                            ):
                                gmail_provider.authenticate_via_loopback(
                                    open_browser=True,
                                    timeout_seconds=90.0,
                                    allow_unencrypted_fallback=gmail_consent,
                                    auth_info=auth_info,
                                )
                            st.session_state["notice"] = (
                                "success",
                                "Gmail connected. Synchronize to import messages.",
                            )
                            st.rerun()
                        except OAuthError:
                            st.error(
                                "Authorization failed. Check your Desktop OAuth client, consent screen, and read-only permissions; then reconnect."
                            )
                        except Exception:
                            st.error(
                                "Could not connect Gmail. Check your network and OAuth configuration, then retry."
                            )
    with g_right:
        st.subheader("Read-only by design")
        st.write(
            "Gmail access imports messages. Resolve, review, and park affect only local state."
        )
        with st.expander("OAuth and credential details"):
            st.code("https://www.googleapis.com/auth/gmail.readonly", language=None)
            st.write(
                "Create a Desktop OAuth client in your Google Cloud project and configure consent before connecting. The browser and MossMail must run on the same machine."
            )
            st.write(
                "OS keyring storage is preferred. Unencrypted file storage requires explicit consent. This application is intended for a single user on their own machine."
            )
    if setup_active:
        if st.button("Finish setup", type="primary"):
            close_setup()
    st.stop()

# Enforce due review deadlines on app runs; no background scheduler is implied.
for row in store.all():
    if row["parked"] and row["due"] and datetime.fromisoformat(row["due"]) <= datetime.now(UTC):
        store.transition(
            row["id"],
            "expire",
            f"local:expire:{row['id']}:{row['cycle']}",
            cycle=row["cycle"],
            mode="local",
        )
rows = sorted(
    store.all(), key=lambda r: Message.model_validate_json(r["payload"]).received_at, reverse=True
)
parked = [r for r in rows if r["parked"]]
if view == "Activity":
    show_history(store.history())
    st.stop()
if store.setting("sync_error"):
    st.warning(store.setting("sync_error"))
if not gmail_provider.is_connected():
    if rows:
        st.caption(
            "Gmail is disconnected. Stored messages are available; reconnect in Settings to synchronize."
        )
    else:
        st.info(
            "Gmail is not connected. Open setup or Settings to configure a Desktop OAuth client and connect with read-only access."
        )
elif not store.setting("last_sync"):
    st.info("Ready to import messages. Choose Sync inbox to synchronize recent Gmail messages.")
if not rows:
    st.subheader("No stored messages")
    if gmail_provider.is_connected() and store.setting("last_sync"):
        st.write(
            "The last synchronization returned no stored inbox messages. You can synchronize again at any time."
        )
    elif gmail_provider.is_connected():
        st.write("Choose Sync inbox to import recent messages.")
    else:
        st.write(
            "Connect Gmail in Settings, then synchronize your inbox. Nothing is added until you import it."
        )
    st.caption("No AI credentials are needed for deterministic triage or reading messages.")
    st.stop()
left, right = st.columns([1.1, 1], gap="large")
with left:
    with st.container(key="message_list"):
        st.caption(f"{len(rows)} stored messages")
        if view == "Inbox":
            chosen_filter = st.segmented_control(
                "Filter messages",
                ["All", "Review", "Escalated", "Resolved"],
                default="All",
                label_visibility="collapsed",
            )
            state_filter = {
                "Review": State.REVIEW,
                "Escalated": State.ESCALATED,
                "Resolved": State.RESOLVED,
            }
            visible = [
                r
                for r in rows
                if chosen_filter not in state_filter or r["state"] == state_filter[chosen_filter]
            ]
        else:
            visible = parked
            st.caption("Local deferrals; follow-ups are checked during synchronization.")
        selected_key = "selected_" + view
        valid_ids = [r["id"] for r in visible]
        if st.session_state.get(selected_key) not in valid_ids:
            st.session_state[selected_key] = valid_ids[0] if valid_ids else None
        for row in visible:
            message = Message.model_validate_json(row["payload"])
            decision = decide(message, store.policy)
            color = (
                "rose"
                if row["state"] == State.ESCALATED
                else "amber"
                if row["state"] == State.REVIEW
                else "green"
            )
            label = "Parked" if row["parked"] else row["state"]
            selected = row["id"] == st.session_state[selected_key]
            with st.container(border=False):
                st.html(
                    f'<div class="mail-heading"><span class="sender">{safe(message.sender_name)}</span>{badge(label, color)}</div><div class="mail-subject">{safe(message.subject)}</div><div class="mail-preview">{safe(message.body[:100])}…</div>'
                )
                meta, button = st.columns([3, 1])
                with meta:
                    if row["due"]:
                        due = (
                            datetime.fromisoformat(row["due"])
                            .astimezone(UTC)
                            .strftime("%d %b · %H:%M UTC")
                        )
                        st.caption(f"Review {due}")
                    else:
                        priority = (
                            "High"
                            if decision.score.risk >= 0.7
                            else "Moderate"
                            if decision.score.risk > 0.25
                            else "Low"
                        )
                        st.caption(
                            f"{message.received_at.strftime('%d %b %H:%M')} · {priority} risk · {'Protected sender' if decision.protected else 'Human review' if decision.score.uncertainty > 0.25 else 'Policy checked'}"
                        )
                with button:
                    if st.button(
                        "Selected" if selected else "Open",
                        key="open_" + message.id,
                        use_container_width=True,
                        type="primary" if selected else "secondary",
                    ):
                        st.session_state[selected_key] = message.id
                        st.rerun()
        if not visible:
            st.info("No messages in this view. Choose another filter or connect Gmail in Settings.")
with right:
    selected_id = st.session_state[selected_key]
    if selected_id:
        row = store.get(selected_id)
        message = Message.model_validate_json(row["payload"])
        override = Override.model_validate_json(row["override"]) if row["override"] else None
        decision = decide(message, store.policy, override=override)
        st.caption("Selected message")
        st.html(
            f"<h2>{safe(message.subject)}</h2>"
            f'<div class="message-meta">{safe(message.sender_name)} · {safe(message.sender)}</div>'
            f'<div class="message-meta">To {safe(", ".join(message.recipients))} · {safe(message.received_at.strftime("%d %b %Y · %H:%M %Z"))}</div>'
        )

        def act(kind):
            try:
                store.transition(selected_id, kind, str(uuid4()), cycle=row["cycle"], mode="local")
                st.rerun()
            except (ValueError, OSError, sqlite3.Error):
                st.error("Decision was not saved. Check policy and local storage, then retry.")

        c1, c2 = st.columns(2)
        if c1.button(
            "Mark resolved", use_container_width=True, disabled=row["state"] == State.RESOLVED
        ):
            act("resolve")
        if c2.button("Keep in review", use_container_width=True):
            act("review")
        if not row["parked"] and decision.state == State.DEFER:
            if st.button("Park for later", type="primary", use_container_width=True):
                act("park")
        key = f"summary_{message.id}_{message.revision}_{store.setting('ai_provider')}"
        if key not in st.session_state:
            st.session_state[key] = fallback(
                message, "Original-message excerpt. AI has not been requested."
            )
        if st.button("Generate summary", key="generate_" + selected_id):
            with st.spinner("Requesting summary…"):
                try:
                    st.session_state[key] = get_summarizer(
                        provider=store.setting("ai_provider") or None
                    ).summarize(message)
                except (ValueError, OSError):
                    st.session_state[key] = fallback(
                        message, "AI configuration unavailable. Check Settings."
                    )
        summary = st.session_state[key]
        with st.container(border=True):
            source = (
                f"LOCAL AI · {summary.model}"
                if summary.source == "local_ai"
                else f"GEMINI AI · {summary.model}"
                if summary.source == "gemini_ai"
                else "ORIGINAL EXCERPT · NO AI"
            )
            st.html(
                '<div class="eyebrow">'
                + ("Excerpt" if summary.source == "deterministic_excerpt" else "Summary")
                + "</div>"
                + badge(source)
            )
            st.text(summary.summary)
            st.html('<div class="eyebrow">Suggested next step · advice only</div>')
            st.text(summary.proposed_action)
            if (
                summary.source == "deterministic_excerpt"
                and "has not been requested" not in summary.note
            ):
                st.warning(summary.note + " Configure or retry the provider in Settings.")
            else:
                st.caption(summary.note)
        st.html('<div class="eyebrow">Policy</div>')
        # Stored state may reflect a timer transition after the original recommendation.
        st.markdown(f"**Current state: {safe(row['state'])}**")
        for reason in decision.reasons:
            st.text("· " + reason)
        if row["state"] != decision.state:
            st.caption("The recorded event below supersedes the initial recommendation.")
        st.caption("Risk is a heuristic indicator, not a calibrated probability.")
        st.caption(decision.action)
        with st.expander("Read the original message", expanded=False):
            st.text(message.body)
            if message.has_attachments:
                st.caption(
                    "This message has attachments. Attachment content is not imported or analyzed."
                )

        with st.expander("Decision history", expanded=view == "Parked"):
            show_history(store.history(selected_id))

st.html(
    '<div class="footer">MOSSMAIL &nbsp; / &nbsp; A CALMER INBOX &nbsp; <span>Nothing sent. Nothing deleted. You stay in control.</span></div>'
)
