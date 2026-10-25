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
