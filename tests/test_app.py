from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from mossmail.credentials import CredentialStore
from mossmail.models import State
from mossmail.storage import Store


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("MOSSMAIL_CREDS_FILE", str(tmp_path / "creds.json"))
    monkeypatch.setenv("MOSSMAIL_SUMMARIZER", "fallback")
    monkeypatch.setattr(CredentialStore, "get_secret", lambda *a: None)
    return tmp_path / "ui.db"


def launch():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


@pytest.mark.parametrize("action", ["Skip for now", "Close setup"])
def test_fresh_start_dismissal_persists(app_env, action):
    app = launch()
    assert not app.exception
    assert app.title[0].value == "Welcome to MossMail"
    assert Store(app_env).all() == []
    assert Store(app_env).history() == []
    click(app, action)
    assert any("No stored messages" == s.value for s in app.subheader)
    restarted = launch()
    assert restarted.title[0].value == "Inbox"
    assert Store(app_env).all() == []
    restarted.sidebar.radio[0].set_value("Settings").run()
    click(restarted, "Reopen setup")
    assert restarted.title[0].value == "Welcome to MossMail"
    click(restarted, "Set up now")
    assert any("Gemini" in r.options[0] for r in restarted.radio if r.options)
    click(restarted, "Finish setup")
    assert Store(app_env).setting("onboarding_dismissed") == "yes"


def test_persisted_message_and_override(app_env, message, monkeypatch):
    from mossmail.summarizer import LocalSummarizer

    def forbidden(*args, **kwargs):
        raise AssertionError("Opening a message must not call AI")

    monkeypatch.setattr(LocalSummarizer, "summarize", forbidden)
    store = Store(app_env)
    store.seed([message])
    store.set_setting("onboarding_dismissed", "yes")
    app = launch()
    assert not app.exception
    click(app, "Mark resolved")
    assert Store(app_env).get(message.id)["state"] == State.RESOLVED
    assert not launch().exception
    assert len(Store(app_env).all()) == 1
    assert not any("Simulate" in b.label for b in app.button)


def test_failed_sync_is_visible_and_preserves_data(app_env, message, monkeypatch):
    from mossmail.mailbox import GmailProvider
    from mossmail.mailbox.sync import SyncReport

    Store(app_env).seed([message])
    Store(app_env).set_setting("onboarding_dismissed", "yes")
    monkeypatch.setattr(GmailProvider, "is_connected", lambda *a: True)
    monkeypatch.setattr(
        "mossmail.mailbox.sync_inbox",
        lambda *a, **k: SyncReport(errors=["Access expired. Reconnect."]),
    )
    app = launch()
    click(app, "Sync inbox")
    assert app.error
    assert not app.success
    assert Store(app_env).setting("last_sync") == ""
    assert len(Store(app_env).all()) == 1


def test_public_landing_never_opens_private_state(app_env, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Public landing must not access private state")

    monkeypatch.setattr(Store, "__init__", forbidden)
    monkeypatch.setattr(CredentialStore, "__init__", forbidden)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "streamlit_app.py")).run()
    assert not app.exception
    assert not app_env.exists()
    assert any("hosted sample inbox has been retired" in item.value for item in app.info)


def test_failed_ai_request_shows_real_excerpt_without_success(app_env, message):
    store = Store(app_env)
    store.seed([message])
    store.set_setting("onboarding_dismissed", "yes")
    store.set_setting("ai_provider", "gemini")
    app = launch()
    click(app, "Generate summary")
    assert not app.success
    assert any("disabled" in item.value for item in app.warning)
    assert any(message.body in item.value for item in app.text)
    assert len(Store(app_env).all()) == 1
    assert Store(app_env).history() == []


def test_missing_gmail_configuration_cannot_connect(app_env):
    app = launch()
    click(app, "Set up now")
    click(app, "Connect Gmail Account")
    assert any("Client ID" in item.value for item in app.error)
    assert not app.success
    assert Store(app_env).all() == []


def test_overdue_local_parking_returns_for_review(app_env, message):
    from datetime import UTC, datetime, timedelta

    store = Store(app_env)
    store.seed([message])
    store.set_setting("onboarding_dismissed", "yes")
    store.transition(message.id, "park", "old-park", now=datetime.now(UTC) - timedelta(days=2))
    app = launch()
    assert not app.exception
    assert Store(app_env).get(message.id)["state"] == State.REVIEW
    assert not Store(app_env).get(message.id)["parked"]
    assert Store(app_env).history()[0]["mode"] == "local"


def test_untrusted_headers_render_as_escaped_text(app_env, message):
    store = Store(app_env)
    store.set_setting("onboarding_dismissed", "yes")
    malicious = '<img src="https://example.test/track">'
    store.seed([message.model_copy(update={"subject": malicious, "sender_name": malicious})])
    app = launch()
    assert not app.exception
    assert any("&lt;img" in item.value for item in app.html)
    assert all(malicious not in item.value for item in app.html)


@pytest.mark.parametrize("partial", [False, True])
def test_sync_outcomes_are_distinct(app_env, monkeypatch, partial):
    from mossmail.mailbox import GmailProvider
    from mossmail.mailbox.sync import SyncReport

    store = Store(app_env)
    store.set_setting("onboarding_dismissed", "yes")
    monkeypatch.setattr(GmailProvider, "is_connected", lambda *a: True)
    report = (
        SyncReport(existing_count=1, errors=["One request failed."]) if partial else SyncReport()
    )
    monkeypatch.setattr("mossmail.mailbox.sync_inbox", lambda *a, **k: report)
    app = launch()
    click(app, "Sync inbox")
    if partial:
        assert app.warning
        assert not app.success
        assert store.setting("last_sync") == ""
    else:
        assert app.success
        assert store.setting("last_sync")
        assert any("last synchronization" in item.value for item in app.markdown)
    assert store.all() == []
