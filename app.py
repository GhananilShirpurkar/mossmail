import html
import os
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import streamlit as st

from mossmail.credentials import (
    SUPPORTED_GEMINI_MODELS,
    CredentialStore,
    InsecureStorageError,
    validate_gemini_key,
)
from mossmail.decision_engine import decide
from mossmail.mailbox import (
    GmailProvider,
    OAuthError,
    sync_inbox,
)
from mossmail.models import Message, Override, State
from mossmail.storage import Store, load_demo
from mossmail.summarizer import fallback, get_summarizer

ROOT = Path(__file__).parent
HOSTED_DEMO = globals().get("HOSTED_DEMO", False)
st.set_page_config(page_title="MossMail · A calmer inbox", page_icon="🌿", layout="wide")
st.html((ROOT / "mossmail/style.html").read_text())


def safe(value):
    return html.escape(str(value))


def badge(text, kind="green"):
    return f'<span class="badge {kind}">{safe(text)}</span>'


def event_label(event):
    return {
        "park": "Parked with a review timer",
        "resolve": "You marked it resolved",
        "review": "Returned to your review queue",
        "followup": "Follow-up received · escalated",
        "risk": "New risk signal · escalated",
        "expire": "Timer expired · returned for review",
    }[event["kind"]]


if HOSTED_DEMO:
    if "_demo_dir" not in st.session_state:
        st.session_state["_demo_dir"] = TemporaryDirectory(prefix="mossmail-demo-")
    db_path = Path(st.session_state["_demo_dir"].name) / "session.sqlite3"
else:
    db_path = Path(os.getenv("MOSSMAIL_DB", str(ROOT / ".local/mossmail.sqlite3")))
store = Store(db_path)
store.seed(load_demo(ROOT / "data/demo_emails.json"))
cred_store = CredentialStore()
gmail_provider = GmailProvider(credential_store=cred_store)

# Idempotent, explicitly simulated seed events. No real mailbox is connected.
for mid in ("m06", "m07", "m08"):
    if not store.history(mid):
        store.transition(mid, "park", "demo-seed-" + mid)
if not store.history("m05"):
    store.transition("m05", "followup", "demo-seed-m05")
if not store.history("m10"):
    store.transition("m10", "resolve", "demo-seed-m10")

with st.sidebar:
    st.html(
        '<div class="brand"><span class="brand-icon">m</span> mossmail<span class="brand-dot">BETA</span></div>'
    )
    st.html('<div class="sidebar-note">A little less noise.<br>A little more room to think.</div>')
    view = st.radio(
        "Workspace", ["Inbox", "Parked", "Activity", "Settings"], label_visibility="collapsed"
    )
    st.divider()
    st.html('<div class="eyebrow">YOUR WORKSPACE</div>')
    if gmail_provider.is_connected():
        st.html(
            badge("GMAIL CONNECTED", kind="green")
            + '<p class="micro">Read-only inbox access active.<br>No emails can be modified.</p>'
        )
        if st.button(
            "Sync Inbox Now",
            type="primary",
            use_container_width=True,
            key="sidebar_sync_btn",
        ):
            with st.spinner("Syncing inbox messages from Gmail..."):
                report = sync_inbox(gmail_provider, store, limit=20)
            if report.errors:
                st.warning(
                    f"Sync finished with {len(report.errors)} issue(s). "
                    f"Imported {report.new_count} new message(s)."
                )
            else:
                st.success(
                    f"Sync complete: {report.new_count} new message(s), "
                    f"{report.escalated_count} thread(s) escalated."
                )
            st.rerun()
    else:
        st.caption("Cedar Studio · synthetic collection")
        st.html(
            badge("DEMO MODE")
            + '<p class="micro">Every message is fictional.<br>No mailbox is connected.</p>'
        )
        st.caption("Connect real Gmail in Settings.")
    st.divider()
    st.html(f'<div class="eyebrow">{"HOSTED DEMO" if HOSTED_DEMO else "RUNNING LOCALLY"}</div>')
    st.caption("Policy · transparent baseline")
    st.caption("Workflow · demo simulation")
    st.caption(
        "Summaries · demo excerpts" if HOSTED_DEMO else "Summaries · Ollama or labeled fallback"
    )
    if HOSTED_DEMO:
        st.caption("Your demo changes are private to this session and reset when it ends.")
    st.html(
        '<div class="sidebar-bottom">Designed for safe inaction.<br>Always yours to decide.</div>'
    )

rows = store.all()
counts = {state: sum(r["state"] == state for r in rows) for state in State}
parked = [r for r in rows if r["parked"]]
st.html(
    '<div class="topline"><span>PERSONAL ATTENTION SPACE</span><span>'
    + (
        "HOSTED DEMO &nbsp; / &nbsp; SYNTHETIC DATA ONLY"
        if HOSTED_DEMO
        else "LOCAL FIRST &nbsp; / &nbsp; PRIVACY BY DEFAULT"
    )
    + "</span></div>"
)
hero_h1 = (
    "Your inbox, with room to breathe."
    if view == "Inbox"
    else "Let it wait. Keep it in sight."
    if view == "Parked"
    else "Every decision leaves a trail."
    if view == "Activity"
    else "Your tools, your keys, your terms."
)
hero_p = (
    "Focus on what needs you. Give everything else a little space."
    if view == "Inbox"
    else "A pause with a promise to return. Follow-ups bring a message straight back."
    if view == "Parked"
    else "Reversible choices, visible reasons, and a history you can inspect."
    if view == "Activity"
    else "Configure local and cloud AI providers with strict privacy boundaries."
)
st.html(
    f'<div class="hero"><div class="eyebrow">LESS ATTENTION. BETTER DECISIONS.</div><h1>{hero_h1}</h1><p>{hero_p}</p></div>'
)

metrics = [
    ("IN YOUR INBOX", len(rows), "synthetic messages", "neutral"),
    ("NEEDS YOUR EYES", counts[State.REVIEW], "protected or uncertain", "amber"),
    ("BROUGHT BACK", counts[State.ESCALATED], "follow-up received", "rose"),
    ("PARKED FOR LATER", len(parked), "with a review deadline", "green"),
]
for column, (title, number, detail, color) in zip(st.columns(4), metrics, strict=True):
    with column:
        st.html(
            f'<div class="metric {color}"><div class="eyebrow">{title}</div><div class="metric-value">{number:02}</div><div class="metric-detail">{detail}</div></div>'
        )
st.write("")


def show_history(events):
    if not events:
        st.info("No actions yet. This message is still in your hands.")
    for event in events:
        timestamp = datetime.fromisoformat(event["created_at"]).strftime("%d %b · %H:%M UTC")
        st.html(
            f'<div class="event"><div class="event-dot"></div><div><strong>{safe(event_label(event))}</strong><div class="micro">{safe(event["message_id"])} · {timestamp} · {safe(event["mode"].upper())}</div><div class="event-state">{safe(event["state"])}</div></div></div>'
        )


if view == "Activity":
    st.subheader("Your decision history")
    st.caption(
        "Local state transitions only. Simulation events never represent mailbox operations."
    )
    left, right = st.columns([1.5, 1])
    with left:
        with st.container(border=True):
            show_history(store.history())
    with right:
        st.html(
            '<div class="principle"><div class="eyebrow">THE MOSSMAIL PROMISE</div><h2>A pause is reversible.</h2><p>Nothing is deleted or archived. Timers return messages for review. New context can change a decision. Your choices are recorded.</p></div>'
        )
        st.info(
            "This dashboard simulates waiting. Run the separate Temporal worker for durable workflows; see the README."
        )
    st.stop()

if view == "Settings":
    st.subheader("Settings & AI Configuration")
    st.caption("Manage AI inference providers and credentials. Keys never leave your machine.")
    cred_store = CredentialStore()
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.html('<div class="eyebrow">INFERENCE PROVIDER</div>')
        has_key = cred_store.get_secret("gemini_api_key") is not None
        provider_choice = st.radio(
            "Select Provider",
            ["Google Gemini API (BYOK)", "Local Ollama (100% Offline)"],
            index=0 if has_key else 1,
            label_visibility="collapsed",
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
                if chosen_model != current_model:
                    if st.button("Update Model", type="primary"):
                        cred_store.set_secret(
                            "gemini_model", chosen_model, allow_unencrypted_file=True
                        )
                        st.rerun()

                if key_status in ("keyring", "unencrypted_file"):
                    if st.button("Remove Gemini API Key", type="secondary"):
                        cred_store.delete_secret("gemini_api_key")
                        cred_store.delete_secret("gemini_model")
                        st.rerun()
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
                chosen_model = st.selectbox(
                    "Select Model", SUPPORTED_GEMINI_MODELS, index=0
                )

                keyring_usable = cred_store.is_keyring_usable()
                consent = False
                if not keyring_usable:
                    st.warning(
                        "⚠️ No secure OS keyring is available on this system. Saving this key requires writing to an unencrypted "
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
                                st.success("Key validated and stored successfully!")
                                st.rerun()
                            except InsecureStorageError as exc:
                                st.error(str(exc))

    with right:
        with st.container(border=True):
            st.html(
                '<div class="principle"><div class="eyebrow">PRIVACY & DATA BOUNDARY</div>'
                '<h2>What leaves your machine?</h2>'
                '<p>Safe inaction means your privacy is explicit, never assumed.</p></div>'
            )
            st.markdown(
                """
                - **When does data leave?** Only when you open an email and active provider is set to Gemini.
                - **What is sent?** Subject (truncated to 300 chars) and latest reply body (truncated to 6,000 chars).
                - **What is NOT sent?** Email headers, DKIM/auth tokens, attachments, IP addresses, and recipient lists are strictly excluded.
                - **Offline option:** Select Local Ollama for complete air-gapped processing on your own hardware.
                - **Google Terms:** Free-tier keys are governed by Google AI Studio Terms. Paid tier keys provide zero-data-retention.
                """
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
                st.success("Gmail is connected (Read-Only).")
                st.caption(
                    "MossMail has permission only to read inbox messages. "
                    "It cannot send, modify, delete, or archive any email."
                )
                sync_col1, sync_col2 = st.columns(2)
                with sync_col1:
                    if st.button("Sync Inbox Now", type="primary", key="sync_btn_settings"):
                        with st.spinner("Syncing recent messages from Gmail..."):
                            report = sync_inbox(gmail_provider, store, limit=20)
                        if report.errors:
                            st.warning(
                                f"Sync finished with {len(report.errors)} issue(s). "
                                f"Imported {report.new_count} new message(s)."
                            )
                        else:
                            st.success(
                                f"Sync complete: {report.new_count} new message(s), "
                                f"{report.escalated_count} thread(s) escalated."
                            )
                        st.rerun()
                with sync_col2:
                    if st.button("Disconnect Gmail", type="secondary", key="disconnect_gmail"):
                        gmail_provider.disconnect()
                        st.success("Disconnected Gmail and purged credentials from your vault.")
                        st.rerun()
            else:
                st.caption(
                    "Bring your own Google OAuth Client ID (type: 'Desktop app'). "
                    "Credentials are encrypted in your OS Keyring."
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
                    value=cred_store.get_secret("gmail_client_secret") or "",
                    type="password",
                    placeholder="GOCSPX-...",
                    help="Client secret for your Desktop app OAuth client.",
                    key="input_gmail_client_secret",
                )

                keyring_usable = cred_store.is_keyring_usable()
                gmail_consent = False
                if not keyring_usable:
                    st.warning(
                        "⚠️ Secure OS keyring unavailable. Storing OAuth tokens requires writing to "
                        "`.local/credentials.json` (mode 0600, unencrypted at rest)."
                    )
                    gmail_consent = st.checkbox(
                        "Authorize storing Gmail OAuth tokens in unencrypted local file (mode 0600)",
                        key="gmail_consent_unencrypted",
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
                            gmail_provider.client_secret = client_secret_val.strip()
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
                            st.success("Gmail successfully connected!")
                            st.rerun()
                        except OAuthError as err:
                            st.error(f"Authentication failed: {err}")
                        except Exception as err:
                            st.error(f"Failed to connect Gmail: {err}")
    with g_right:
        with st.container(border=True):
            st.html(
                '<div class="principle"><div class="eyebrow">RESTRICTED SCOPE DISCLOSURE</div>'
                '<h2>Google OAuth & Privacy Guarantees</h2>'
                '<p>Your mailbox access is strictly limited by design.</p></div>'
            )
            st.markdown(
                """
                - **Scope:** `https://www.googleapis.com/auth/gmail.readonly` only.
                - **Zero Mutations:** MossMail contains no code to send, delete, label, archive, or modify emails.
                - **Restricted Scope Policy:** Google designates `gmail.readonly` as a Restricted Scope. Public multi-user cloud applications must undergo CASA Tier 2 security assessments and Google verification.
                - **Local-First Architecture:** As a local self-hosted open-source application, MossMail runs on your machine. You bring your own Google Cloud OAuth 2.0 Desktop Client ID.
                - **Token Storage:** Refresh tokens are stored locally in your operating system credential store (Keyring/SecretService) and never uploaded.
                """
            )
    st.stop()

left, right = st.columns([1.1, 1], gap="large")
with left:
    st.subheader("The waiting room" if view == "Parked" else "A considered inbox")
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
        st.caption("Simulation · timers are shown below. Use preview to exercise expiry now.")
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
        with st.container(border=True):
            st.html(
                f'<div class="mail-heading"><span class="sender">{safe(message.sender_name)}</span>{badge(label, color)}</div><div class="mail-subject">{safe(message.subject)}</div><div class="mail-preview">{safe(message.body[:100])}…</div>'
            )
            meta, button = st.columns([3, 1])
            with meta:
                if row["due"]:
                    due = datetime.fromisoformat(row["due"]).strftime("%d %b · %H:%M UTC")
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
                        f"{priority} risk · {'Protected sender' if decision.protected else 'Human review' if decision.score.uncertainty > 0.25 else 'Policy checked'}"
                    )
            with button:
                if st.button(
                    "Reading" if selected else "Open",
                    key="open_" + message.id,
                    use_container_width=True,
                    type="primary" if selected else "secondary",
                ):
                    st.session_state[selected_key] = message.id
                    st.rerun()
    if not visible:
        st.success("Nothing waiting here. Your other messages are in the inbox.")

with right:
    selected_id = st.session_state[selected_key]
    if selected_id:
        row = store.get(selected_id)
        message = Message.model_validate_json(row["payload"])
        override = Override.model_validate_json(row["override"]) if row["override"] else None
        decision = decide(message, store.policy, override=override)
        st.html('<div class="eyebrow detail-kicker">A CLOSER LOOK</div>')
        st.subheader(message.subject)
        st.caption(f"{message.sender_name} · {message.sender}")
        st.caption(
            f"To {', '.join(message.recipients)} · {message.received_at.strftime('%d %b %Y · %H:%M %Z')}"
        )
        key = f"summary_{message.id}_{message.revision}"
        if key not in st.session_state:
            try:
                if HOSTED_DEMO:
                    st.session_state[key] = fallback(
                        message,
                        "Hosted demo excerpt. Run MossMail locally to use Ollama and Gemma.",
                    )
                else:
                    with st.spinner("Preparing summary…"):
                        st.session_state[key] = get_summarizer().summarize(message)
            except ValueError:
                st.session_state[key] = fallback(message, "Model configuration is invalid.")
        summary = st.session_state[key]
        with st.container(border=True):
            source = (
                f"LOCAL AI · {summary.model}"
                if summary.source == "local_ai"
                else f"GEMINI AI · {summary.model}"
                if summary.source == "gemini_ai"
                else "DEMO FALLBACK · EXCERPT"
            )
            st.html('<div class="eyebrow">THE SHORT VERSION</div>' + badge(source))
            st.text(summary.summary)
            st.html('<div class="eyebrow">PROPOSED NEXT STEP · ADVICE ONLY</div>')
            st.text(summary.proposed_action)
            st.caption(summary.note)
            if st.button(
                "Refresh excerpt" if HOSTED_DEMO else "Refresh summary",
                key="refresh_" + selected_id,
            ):
                del st.session_state[key]
                st.rerun()
        st.html('<div class="eyebrow">WHY IT LANDED HERE</div>')
        # Stored state may reflect a timer transition after the original recommendation.
        st.markdown(f"**Current state: {safe(row['state'])}**")
        for reason in decision.reasons:
            st.text("· " + reason)
        if row["state"] != decision.state:
            st.caption("The recorded event below supersedes the initial recommendation.")
        st.caption("Risk is a heuristic indicator, not a calibrated probability.")
        st.info(decision.action)
        with st.expander("Read the original message", expanded=False):
            st.text(message.body)
            if message.has_attachments:
                st.caption("Synthetic attachment marker. No attachment is included or analyzed.")

        def act(kind):
            store.transition(selected_id, kind, str(uuid4()), cycle=row["cycle"])
            st.rerun()

        c1, c2 = st.columns(2)
        if c1.button(
            "Mark resolved", use_container_width=True, disabled=row["state"] == State.RESOLVED
        ):
            act("resolve")
        if c2.button("Keep in review", use_container_width=True):
            act("review")
        if row["parked"]:
            st.html('<div class="eyebrow">TRY THE WAITING WORKFLOW</div>')
            st.caption(
                "These controls simulate events immediately. No durable server is running here."
            )
            a, b = st.columns(2)
            if a.button("Simulate follow-up", type="primary", use_container_width=True):
                act("followup")
            if b.button("Preview timer expiry", use_container_width=True):
                act("expire")
        elif decision.state == State.DEFER:
            if st.button("Park for later", type="primary", use_container_width=True):
                act("park")
        with st.expander("Decision history", expanded=view == "Parked"):
            show_history(store.history(selected_id))

st.html(
    '<div class="footer">MOSSMAIL &nbsp; / &nbsp; A CALMER INBOX &nbsp; <span>Nothing sent. Nothing deleted. You stay in control.</span></div>'
)
