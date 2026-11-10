"""Streamlit UI startup smoke test (no market download triggered)."""
from streamlit.testing.v1 import AppTest


def test_dashboard_renders_without_runtime_exception():
    app = AppTest.from_file("app.py", default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "🇮🇳 India CRT Setup Scanner"
    assert app.button[0].label == "🔄 Scan market"
