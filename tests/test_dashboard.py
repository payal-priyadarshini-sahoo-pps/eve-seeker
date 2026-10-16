from pathlib import Path

import pytest

streamlit_testing = pytest.importorskip("streamlit.testing.v1")

DASH = Path(__file__).resolve().parents[1] / "eveseeker" / "visualization" / "dashboard.py"


def test_dashboard_runs_and_steps():
    at = streamlit_testing.AppTest.from_file(str(DASH), default_timeout=120).run()
    assert not at.exception
    buttons = {b.label: b for b in at.sidebar.button}
    buttons["+10"].click()
    at.run()
    assert not at.exception
    assert any(b.label == "Run" for b in at.sidebar.button)
    for b in at.sidebar.button:
        if b.label == "Run":
            b.click()
    at.run()
    assert not at.exception
    assert at.success or at.error or at.warning   # mission ended with a visible status
