from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"


def test_streamlit_page_renders_headless():
    """Runs the page the way Streamlit would, without a browser, and checks it does not
    raise. Simulations inside take a few seconds."""
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=120)
    at.run()
    assert not at.exception
    assert at.title[0].value.startswith("Incubator heater control")
    assert len(at.dataframe) == 1
    assert len(at.dataframe[0].value) == 4  # one metrics row per controller
