import pytest
from pathlib import Path

from mira.config.loader import load_settings


@pytest.fixture
def settings():
    root = Path(__file__).resolve().parents[1]
    return load_settings(root=root, environ={"MIRA_PROFILE": "test"})
