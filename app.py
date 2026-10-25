import html
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import streamlit as st

from mossmail.decision_engine import decide
from mossmail.models import Message, Override, State
from mossmail.storage import Store, load_demo
from mossmail.summarizer import LocalSummarizer, fallback

ROOT = Path(__file__).parent
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


store = Store(os.getenv("MOSSMAIL_DB", str(ROOT / ".local/mossmail.sqlite3")))
store.seed(load_demo(ROOT / "data/demo_emails.json"))
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
    view = st.radio("Workspace", ["Inbox", "Parked", "Activity"], label_visibility="collapsed")
    st.divider()
    st.html('<div class="eyebrow">YOUR WORKSPACE</div>')
    st.caption("Cedar Studio · synthetic collection")
    st.html(
        badge("DEMO MODE")
        + '<p class="micro">Every message is fictional.<br>No mailbox is connected.</p>'
    )
    st.divider()
    st.html('<div class="eyebrow">RUNNING LOCALLY</div>')
    st.caption("Policy · transparent baseline")
    st.caption("Workflow · demo simulation")
    st.caption("Summaries · Ollama or labeled fallback")
    st.html(
        '<div class="sidebar-bottom">Designed for safe inaction.<br>Always yours to decide.</div>'
    )

rows = store.all()
counts = {state: sum(r["state"] == state for r in rows) for state in State}
parked = [r for r in rows if r["parked"]]
st.html(
    '<div class="topline"><span>PERSONAL ATTENTION SPACE</span><span>LOCAL FIRST &nbsp; / &nbsp; PRIVACY BY DEFAULT</span></div>'
)
st.html(
    f'<div class="hero"><div class="eyebrow">LESS ATTENTION. BETTER DECISIONS.</div><h1>{"Your inbox, with room to breathe." if view == "Inbox" else "Let it wait. Keep it in sight." if view == "Parked" else "Every decision leaves a trail."}</h1><p>{"Focus on what needs you. Give everything else a little space." if view == "Inbox" else "A pause with a promise to return. Follow-ups bring a message straight back." if view == "Parked" else "Reversible choices, visible reasons, and a history you can inspect."}</p></div>'
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
                with st.spinner("Preparing a local summary…"):
                    st.session_state[key] = LocalSummarizer().summarize(message)
            except ValueError:
                st.session_state[key] = fallback(message, "Local model configuration is invalid.")
        summary = st.session_state[key]
        with st.container(border=True):
            source = (
                f"LOCAL AI · {summary.model}"
                if summary.source == "local_ai"
                else "DEMO FALLBACK · EXCERPT"
            )
            st.html('<div class="eyebrow">THE SHORT VERSION</div>' + badge(source))
            st.text(summary.summary)
            st.html('<div class="eyebrow">PROPOSED NEXT STEP · ADVICE ONLY</div>')
            st.text(summary.proposed_action)
            st.caption(summary.note)
            if st.button("Refresh local summary", key="refresh_" + selected_id):
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
