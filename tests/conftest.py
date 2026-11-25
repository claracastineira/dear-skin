import pytest


@pytest.fixture
def bd(tmp_path):
    """Base de datos SQLite temporal para cada test."""
    return tmp_path / "dear_skin_test.db"
