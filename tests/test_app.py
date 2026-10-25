from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_dashboard_and_override_without_services(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("MOSSMAIL_SUMMARIZER", "fallback")
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20).run()
    assert not app.exception
    assert any("Mark resolved" == button.label for button in app.button)
    next(b for b in app.button if b.label == "Mark resolved").click().run()
    assert not app.exception
    app.sidebar.radio[0].set_value("Parked").run()
    assert not app.exception
    next(b for b in app.button if b.label == "Simulate follow-up").click().run()
    assert not app.exception


def test_hosted_sessions_are_isolated_and_never_call_ollama(tmp_path, monkeypatch):
    from mossmail.models import State
    from mossmail.storage import Store
    from mossmail.summarizer import LocalSummarizer

    def forbidden(*args, **kwargs):
        raise AssertionError("Hosted demo must not call Ollama")

    monkeypatch.setattr(LocalSummarizer, "summarize", forbidden)
    shared = tmp_path / "must-not-be-used.db"
    monkeypatch.setenv("MOSSMAIL_DB", str(shared))
    entrypoint = str(Path(__file__).parents[1] / "streamlit_app.py")
    first = AppTest.from_file(entrypoint, default_timeout=20).run()
    assert not first.exception
    first_path = Path(first.session_state["_demo_dir"].name) / "session.sqlite3"
    next(b for b in first.button if b.label == "Mark resolved").click().run()
    assert Store(first_path).get("m01")["state"] == State.RESOLVED
    second = AppTest.from_file(entrypoint, default_timeout=20).run()
    assert not second.exception
    second_path = Path(second.session_state["_demo_dir"].name) / "session.sqlite3"
    assert first_path != second_path
    assert Store(second_path).get("m01")["state"] == State.REVIEW
    assert not shared.exists()
    assert any("Hosted demo excerpt" in caption.value for caption in second.caption)


def test_settings_workspace_navigation_and_rendering(tmp_path, monkeypatch):
    monkeypatch.setenv("MOSSMAIL_DB", str(tmp_path / "ui.db"))
    monkeypatch.setenv("MOSSMAIL_CREDS_FILE", str(tmp_path / "creds.json"))
    entrypoint = str(Path(__file__).parents[1] / "app.py")
    app = AppTest.from_file(entrypoint, default_timeout=20).run()
    assert not app.exception

    # Navigate to Settings
    app.sidebar.radio[0].set_value("Settings").run()
    assert not app.exception
    assert any("Settings & AI Configuration" in sub.value for sub in app.subheader)
    assert any("PRIVACY & DATA BOUNDARY" in h.value for h in app.html)
